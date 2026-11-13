"""ICP config: the declared ideal customer profile (ADR-0006).

Who we sell to is a business decision, so it lives in an editable config
file (icp.toml), not in code. The engine uses it in two places: companies
outside the ICP are excluded with a stated reason, and companies closest to
it earn published bonus points in the score breakdown. Unknown attributes
never exclude and never boost - unknown stays unknown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:  # stdlib on 3.11+; the conditional dependency covers older interpreters
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Lookup order for the ICP file: --icp flag, then ./icp.toml, then the
# shipped example (so a cold clone runs immediately, with a printed note).
# The example also ships inside the package so an installed `soe` finds it
# no matter which directory it runs from.
ICP_FILE = Path("icp.toml")
EXAMPLE_FILE = Path("data/icp.example.toml")  # repo checkout convenience
PACKAGE_EXAMPLE = Path(__file__).with_name("icp.example.toml")  # always present

# Published ICP closeness points (README.md#scoring).
INDUSTRY_POINTS = 10
SIZE_POINTS = 5
COUNTRY_POINTS = 5

_TOP_KEYS = {
    "name",
    "industries",
    "countries",
    "target_roles",
    "company_size",
    "signal_weights",
    "exclude",
    "sender_name",
}


class ICPError(ValueError):
    """A config problem the user can fix; the CLI prints it, never a traceback."""


@dataclass(frozen=True)
class CompanyProfile:
    """What we know about a company, independent of its signals."""

    name: str
    industry: str | None = None
    size: int | None = None
    country: str | None = None


@dataclass(frozen=True)
class ICP:
    name: str
    industries: tuple[str, ...]
    size_min: int | None
    size_max: int | None
    countries: tuple[str, ...]
    target_roles: tuple[str, ...]
    signal_weights: dict[str, int] | None
    exclude_industries: tuple[str, ...]
    sender_name: str | None = None

    def exclusion(self, meta: CompanyProfile | None) -> str | None:
        """Why this company is out of the ICP, or None when it is in (or unknown)."""
        if meta is None:
            return None
        industry = (meta.industry or "").lower()
        excluded = {i.lower() for i in self.exclude_industries}
        if industry and industry in excluded:
            return f"industry '{meta.industry}' is explicitly excluded"
        wanted = {i.lower() for i in self.industries}
        if wanted and industry and industry not in wanted:
            return f"industry '{meta.industry}' not in ICP"
        if meta.size is not None:
            if self.size_min is not None and meta.size < self.size_min:
                return f"size {meta.size} below ICP min {self.size_min}"
            if self.size_max is not None and meta.size > self.size_max:
                return f"size {meta.size} above ICP max {self.size_max}"
        country = (meta.country or "").upper()
        countries = {c.upper() for c in self.countries}
        if countries and country and country not in countries:
            return f"country '{meta.country}' not in ICP"
        return None

    def boost(self, meta: CompanyProfile | None) -> tuple[int, tuple[str, ...]]:
        """ICP-closeness points, each with a published reason."""
        if meta is None:
            return (0, ())
        points = 0
        reasons: list[str] = []
        industry = (meta.industry or "").lower()
        if self.industries and industry and industry in {i.lower() for i in self.industries}:
            points += INDUSTRY_POINTS
            reasons.append(f"+{INDUSTRY_POINTS} icp_industry ({meta.industry})")
        if meta.size is not None and self._size_in_range(meta.size):
            points += SIZE_POINTS
            reasons.append(f"+{SIZE_POINTS} icp_size ({meta.size})")
        country = (meta.country or "").upper()
        if self.countries and country and country in {c.upper() for c in self.countries}:
            points += COUNTRY_POINTS
            reasons.append(f"+{COUNTRY_POINTS} icp_country ({meta.country})")
        return (points, tuple(reasons))

    def _size_in_range(self, size: int) -> bool:
        if self.size_min is not None and size < self.size_min:
            return False
        if self.size_max is not None and size > self.size_max:
            return False
        return self.size_min is not None or self.size_max is not None


def _str_list(raw: object, field_name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ICPError(f"icp: '{field_name}' must be a list of strings")
    return tuple(raw)


def load_icp(path: Path) -> ICP:
    """Load and validate an icp.toml. Raises ICPError with the field at fault."""
    if not path.exists():
        raise ICPError(f"icp: file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ICPError(f"icp: {path} is not valid TOML: {exc}") from exc
    unknown = set(raw) - _TOP_KEYS
    if unknown:
        raise ICPError(f"icp: unknown field(s): {', '.join(sorted(unknown))}")
    name = raw.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise ICPError("icp: 'name' must be a non-empty string")
    size_raw = raw.get("company_size", {})
    if not isinstance(size_raw, dict):
        raise ICPError("icp: 'company_size' must be a table like {min = 50, max = 500}")
    size_min = size_raw.get("min")
    size_max = size_raw.get("max")
    for label, value in (("company_size.min", size_min), ("company_size.max", size_max)):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ICPError(f"icp: '{label}' must be a non-negative integer")
    if size_min is not None and size_max is not None and size_min > size_max:
        raise ICPError("icp: company_size.min must be <= company_size.max")
    weights_raw = raw.get("signal_weights")
    weights: dict[str, int] | None = None
    if weights_raw is not None:
        if not isinstance(weights_raw, dict):
            raise ICPError("icp: 'signal_weights' must be a table of signal type = points")
        from engine.signals import SignalType

        valid = {t.value for t in SignalType}
        weights = {}
        for key, value in weights_raw.items():
            if key not in valid:
                raise ICPError(
                    f"icp: unknown signal type '{key}' (valid: {', '.join(sorted(valid))})"
                )
            if not isinstance(value, int) or value < 0:
                raise ICPError(f"icp: signal_weights.{key} must be a non-negative integer")
            weights[key] = value
    sender_raw = raw.get("sender_name")
    if sender_raw is not None and (not isinstance(sender_raw, str) or not sender_raw.strip()):
        raise ICPError("icp: 'sender_name' must be a non-empty string when present")
    exclude_raw = raw.get("exclude", {})
    if not isinstance(exclude_raw, dict):
        raise ICPError("icp: 'exclude' must be a table like {industries = [...]}")
    exclude_unknown = set(exclude_raw) - {"industries"}
    if exclude_unknown:
        raise ICPError(f"icp: unknown exclude field(s): {', '.join(sorted(exclude_unknown))}")
    return ICP(
        name=name.strip(),
        industries=_str_list(raw.get("industries"), "industries"),
        size_min=size_min,
        size_max=size_max,
        countries=_str_list(raw.get("countries"), "countries"),
        target_roles=_str_list(raw.get("target_roles"), "target_roles"),
        signal_weights=weights,
        exclude_industries=_str_list(exclude_raw.get("industries"), "exclude.industries"),
        sender_name=sender_raw.strip() if isinstance(sender_raw, str) else None,
    )


def resolve_icp(flag_path: Path | None = None) -> tuple[ICP | None, str]:
    """Find the ICP to use. Returns (icp or None, note); note is '' for owned files."""
    if flag_path is not None:
        return (load_icp(flag_path), "")
    if ICP_FILE.exists():
        return (load_icp(ICP_FILE), "")
    example = EXAMPLE_FILE if EXAMPLE_FILE.exists() else PACKAGE_EXAMPLE
    if example.exists():
        icp = load_icp(example)
        return (
            icp,
            "using the example customer profile (mid-market B2B SaaS)"
            " - make yours: soe icp setup",
        )
    return (
        None,
        "who you sell to is not set up yet, so companies are not filtered by "
        "industry, size, country or role. Set it up with a few guided "
        "questions: soe icp setup",
    )


def load_companies(path: Path) -> dict[str, CompanyProfile]:
    """Company metadata for ICP matching. A missing file means 'unknown'."""
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    profiles = {}
    for row in rows:
        profiles[row["name"]] = CompanyProfile(
            name=row["name"],
            industry=row.get("industry"),
            size=row.get("size"),
            country=row.get("country"),
        )
    return profiles


def role_matches(title: str | None, target_roles: tuple[str, ...]) -> bool:
    """Token-subset match: 'vp sales' matches 'VP of Sales'. Unknown titles pass."""
    if not target_roles or not title:
        return True
    title_tokens = set(title.lower().split())
    for role in target_roles:
        role_tokens = set(role.lower().split())
        if role_tokens and role_tokens <= title_tokens:
            return True
    return False


def render_icp(icp: ICP, source: str) -> str:
    """Plain table for `soe icp show`."""
    size = "-"
    if icp.size_min is not None or icp.size_max is not None:
        size = f"{icp.size_min or 0} - {icp.size_max if icp.size_max is not None else 'no cap'}"
    lines = [
        f"ICP: {icp.name}",
        f"source: {source}",
        "",
        f"  industries:        {', '.join(icp.industries) or '(any)'}",
        f"  company size:      {size}",
        f"  countries:         {', '.join(icp.countries) or '(any)'}",
        f"  target roles:      {', '.join(icp.target_roles) or '(any)'}",
        f"  exclude:           {', '.join(icp.exclude_industries) or '(none)'}",
        f"  email signature:   {icp.sender_name or '(engine demo signature)'}",
    ]
    if icp.signal_weights:
        weights = ", ".join(f"{k}={v}" for k, v in sorted(icp.signal_weights.items()))
        lines.append(f"  signal weights:    {weights}")
    else:
        lines.append("  signal weights:    (published defaults)")
    return "\n".join(lines)


def _toml_str(value: str) -> str:
    """One TOML basic string, escaped. Without this a quote bricks the file and
    a backslash silently mangles the value (a real newline appears)."""
    quote = chr(34)
    backslash = chr(92)
    out = value.replace(backslash, backslash * 2).replace(quote, backslash + quote)
    for ch, esc in ((chr(9), "t"), (chr(10), "n"), (chr(13), "r")):
        out = out.replace(ch, backslash + esc)
    return quote + out + quote


def write_icp(icp: ICP, path: Path) -> None:
    """Write the fixed TOML structure (hand-rolled: no new dependencies)."""

    def fmt_list(values: tuple[str, ...]) -> str:
        return "[" + ", ".join(_toml_str(v) for v in values) + "]"

    lines = [
        "# Ideal Customer Profile - who this engine sells to (edit: soe icp edit).",
        f"name = {_toml_str(icp.name)}",
    ]
    if icp.sender_name:
        lines.append(f"sender_name = {_toml_str(icp.sender_name)}")
    lines += [
        f"industries = {fmt_list(icp.industries)}",
        f"countries = {fmt_list(icp.countries)}",
        f"target_roles = {fmt_list(icp.target_roles)}",
        "",
        "[company_size]",
    ]
    if icp.size_min is not None:
        lines.append(f"min = {icp.size_min}")
    if icp.size_max is not None:
        lines.append(f"max = {icp.size_max}")
    if icp.signal_weights:
        lines += ["", "[signal_weights]"]
        lines += [f"{key} = {value}" for key, value in sorted(icp.signal_weights.items())]
    lines += ["", "[exclude]", f"industries = {fmt_list(icp.exclude_industries)}", ""]
    path.write_text("\n".join(lines))
