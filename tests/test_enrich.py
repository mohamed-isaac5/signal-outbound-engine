from engine.enrich import Contact, EmailStatus, LookupHit, run_waterfall


class StubProvider:
    def __init__(self, name: str, cost: float, result: LookupHit | None) -> None:
        self.name = name
        self.unit_cost_usd = cost
        self.result = result
        self.calls = 0

    def find_email(self, contact: Contact) -> LookupHit | None:
        self.calls += 1
        return self.result


def test_first_hit_wins_and_stops_the_waterfall() -> None:
    miss = StubProvider("apollo", 0.06, None)
    hit = StubProvider("clay", 0.12, LookupHit("found@acme.com", EmailStatus.VERIFIED))
    never = StubProvider("backup", 0.20, LookupHit("other@acme.com", EmailStatus.RISKY))
    out = run_waterfall(Contact(name="A", company="Acme"), [miss, hit, never])
    assert out.contact.email == "found@acme.com"
    assert out.contact.email_status is EmailStatus.VERIFIED
    assert out.found_by == "clay"
    assert never.calls == 0
    assert out.cost_usd == 0.18  # every lookup is billed, hit or miss


def test_unknown_stays_none_when_all_providers_miss() -> None:
    out = run_waterfall(
        Contact(name="A", company="Acme"),
        [StubProvider("apollo", 0.06, None), StubProvider("clay", 0.12, None)],
    )
    assert out.contact.email is None
    assert out.contact.email_status is EmailStatus.UNKNOWN
    assert len(out.attempts) == 2
    assert out.cost_usd == 0.18


def test_existing_email_is_kept_without_provider_calls() -> None:
    provider = StubProvider("apollo", 0.06, LookupHit("x@acme.com", EmailStatus.VERIFIED))
    out = run_waterfall(Contact(name="A", company="Acme", email="known@acme.com"), [provider])
    assert out.contact.email == "known@acme.com"
    assert provider.calls == 0
    assert out.cost_usd == 0.0


def test_attempts_record_billed_misses() -> None:
    miss = StubProvider("apollo", 0.06, None)
    hit = StubProvider("clay", 0.12, LookupHit("a@acme.com", EmailStatus.RISKY))
    out = run_waterfall(Contact(name="A", company="Acme"), [miss, hit])
    assert [(a.provider, a.hit) for a in out.attempts] == [("apollo", False), ("clay", True)]
