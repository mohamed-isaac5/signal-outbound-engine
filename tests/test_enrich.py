from engine.enrich import Contact, run_waterfall


class StubProvider:
    def __init__(self, name: str, result: str | None) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    def find_email(self, contact: Contact) -> str | None:
        self.calls += 1
        return self.result


def test_first_hit_wins_and_stops_the_waterfall() -> None:
    miss = StubProvider("apollo", None)
    hit = StubProvider("clay", "found@acme.com")
    never = StubProvider("backup", "other@acme.com")
    out = run_waterfall(Contact(name="A", company="Acme"), [miss, hit, never])
    assert out.email == "found@acme.com"
    assert miss.calls == 1
    assert hit.calls == 1
    assert never.calls == 0


def test_unknown_stays_none_when_all_providers_miss() -> None:
    out = run_waterfall(
        Contact(name="A", company="Acme"),
        [StubProvider("apollo", None), StubProvider("clay", None)],
    )
    assert out.email is None


def test_existing_email_is_kept_without_provider_calls() -> None:
    provider = StubProvider("apollo", "x@acme.com")
    out = run_waterfall(Contact(name="A", company="Acme", email="known@acme.com"), [provider])
    assert out.email == "known@acme.com"
    assert provider.calls == 0
