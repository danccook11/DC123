#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""octlib — shared library for the owner-contact-trace skill.

Every other script in scripts/ imports from here. Nothing in this module performs
network I/O, spends vendor money, or writes files.

Three things this module exists to make impossible:

  1. Collapsing the three conclusions. Record ownership, documented human authority,
     and phone attribution are three separate verdicts. The predicates below never
     let one raise another (see `mobile_confirmed` -> line type answers a different
     question than ownership).
  2. Coercing missing evidence to "no". `tri()` returns UNKNOWN for anything absent,
     and no predicate treats absence as a pass or a fail (doctrine 18).
  3. Silently mis-normalizing line type. Three vendors spell the same fact three
     ways; `normalize_line_type` collapses them before any comparison. A build that
     maps only "wire*" scores every Tracerfy row has_wire=False and reads the whole
     backbone as landlines.

Python 3.9 compatible. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import pathlib
import re
import sys

__all__ = [
    "UNKNOWN", "OWNERSHIP_STATUS", "ROLE_STATUS", "PHONE_ATTRIBUTION_STATUS",
    "LINE_TYPE_STATUS", "COMPLIANCE_STATUS", "COVERAGE_DISPOSITIONS",
    "CONTROL_TITLES", "EDGE_TYPES", "CONTROL_EDGES", "NONCONTROL_EDGES",
    "AGENT_DESK_MIN", "TYPE_RANK", "NOT_SCRUBBED_STAMP", "APPROVED_PHONE_COLUMNS",
    "LINE_TYPE_SOURCE_ALLOWLIST", "SEED_INSTITUTIONAL", "PHONE_RE",
    "DNC_REFRESH_DAYS", "STATE_CODES",
    "utcnow_iso", "cache_root", "run_dir", "norm_owner", "strip_suffix",
    "is_company", "classify", "split_owner_string", "csz_split", "naddr",
    "addr_key", "napn", "split_apns", "normalize_line_type",
    "surname5_prefix_match", "levenshtein", "fuzzy_owner_merge_ok",
    "is_commercial_agent", "institutional_match", "mail_class", "month_num",
    "phone_sort_key", "tri", "provenance", "redact_phones",
    "title_ok", "entity_ok", "role_ok", "person_ok", "strong_address_match",
    "phone_attributed", "mobile_confirmed", "outreach_eligible",
]

# --------------------------------------------------------------------------
# Vocabularies. These are the controlled enums the schemas validate against.
# UNKNOWN is a member of every truth-valued vocabulary on purpose (doctrine 18).
# --------------------------------------------------------------------------

UNKNOWN = "UNKNOWN"

OWNERSHIP_STATUS = (
    "VERIFIED-OWNER", "TAX-ROLL-OWNER", "OWNERSHIP-CONFLICT",
    "RECORD-OWNER-RESOLVED", "UNKNOWN",
)
ROLE_STATUS = (
    "VERIFIED-AUTHORITY", "PROBABLE-AUTHORITY", "AUTHORIZED-CONTACT",
    "BENEFICIAL-CONTROL-UNKNOWN", "UNKNOWN",
)
PHONE_ATTRIBUTION_STATUS = (
    "VERIFIED-PHONE", "SINGLE-SOURCE-PHONE", "HOUSEHOLD-PHONE",
    "CONTRADICTED", "UNKNOWN",
)
LINE_TYPE_STATUS = ("VERIFIED-MOBILE", "REPORTED-MOBILE", "LANDLINE", "UNKNOWN")
COMPLIANCE_STATUS = (
    "OUTREACH-ELIGIBLE", "DNC-BLOCKED", "UNSCRUBBED", "LITIGATOR", "DECEASED-HOLD",
)
COVERAGE_DISPOSITIONS = (
    "CONTACTED-MOBILE", "CONTACTED-NONMOBILE", "PIERCED-NO-REACHABLE-HUMAN",
    "NO-SOS-MATCH", "TRUST-NEEDS-DEED", "SUPPRESSED-INSTITUTIONAL", "CRM-HIT",
    "NO-OWNER-NAME", "NO-ROUTE-STATE", "UNEVALUATED",
)

# Corrected set. GRM/GR/RM are gone -- they were artifacts of the ra_start+125
# stride bug, not real titles. D (9,571) and PD (3,943) are added on the corrected
# 60k-record frequency evidence. See references/veil_piercing.md.
CONTROL_TITLES = frozenset({
    "MGR", "MGRM", "MEM", "AMBR", "P", "PRES", "CEO", "MP", "TRUS", "TR", "D", "PD",
})

EDGE_TYPES = (
    "title-holder", "member", "managing-member", "manager", "general-partner",
    "limited-partner", "officer", "director", "trustee", "personal-representative",
    "registered-agent", "parent", "successor", "unknown",
)
# Edges that establish control. Everything else may order review but may never by
# itself produce a resolved controller.
CONTROL_EDGES = frozenset({
    "managing-member", "manager", "general-partner", "trustee",
    "personal-representative", "title-holder",
})
NONCONTROL_EDGES = frozenset({
    "registered-agent", "director", "officer", "limited-partner",
})

AGENT_DESK_MIN = 15
TYPE_RANK = {"wireless": 0, "mobile": 0, "voip": 2, "landline": 3, "": 4}

NOT_SCRUBBED_STAMP = "NOT YET SCRUBBED — do not dial or text"

APPROVED_PHONE_COLUMNS = frozenset({
    "primary_mobile", "alt_phone_1", "alt_phone_2",
    "Phone1", "Phone2", "Phone3", "phone", "best_phone",
})

# The only three provenances that may produce the word "mobile". US number
# portability makes any libphonenumber-derived value structurally incapable.
LINE_TYPE_SOURCE_ALLOWLIST = frozenset({
    "tracerfy.phones[].type", "sherpa.PhoneNumber.type", "one-api.Phone-N Type",
})

# Federal DNC access generally must be refreshed on a 31-day cycle; an older scrub
# is stale and re-renders UNSCRUBBED.
DNC_REFRESH_DAYS = 31

STATE_CODES = frozenset("""
AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT
NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY
""".split())
TERRITORY_CODES = frozenset({"PR", "GU", "VI", "AS", "MP"})

# Seed institutional list (19 entries, spec s6). These are held back with a
# recorded matched pattern -- never deleted silently.
SEED_INSTITUTIONAL = (
    "C S X TRANSPORTATION INC",
    "SEABOARD COAST LINE RR CO",
    "SEABOARD COASTLINE RR CO",
    "FLORIDA EAST COAST RAILWAY CO",
    "GEORGIA SOUTHERN & FLORIDA RAILWAY CO",
    "FLORIDA ROCK INDUSTRIES INC",
    "MARTIN MARIETTA MATERIALS INC",
    "SMYRNA READY MIX CONCRETE LLC",
    "CON WAY TRANSPORTATION SERVICES INC % MS MARGARET BONG",
    "OVERNITE TRANSPORTATION CO",
    "ST JOHNS RIVER TERMINAL COMPANY",
    "TANDEM LEASING CORPORATION",
    "ST LUKES ST VINCENTS HEALTHCARE INC",
    "CITY NATIONAL BANK OF FLORIDA TRUSTEE",
    "MILAM STEPHEN WESLEY TR % FIRST TENNESSEE BANK ATTN LINDA FLENNIKEN",
    "HGC GETTYSVUE LLC",
    "ASSN FOR PRESERVATION OF TENNESSEE ANTIQUITIES KNOXVILLE CHAPTER",
    "VOLUNTEER LODGE 2 FRATERNAL ORDER OF POLICE",
    "TENNESSEE STATE OF",
)

CULL_REASONS = (
    "Railroad", "Quarry/materials major", "Transport/logistics major",
    "Health system", "Institutional trustee/bank", "Church/civic (rarely sells)",
    "Club/golf", "Government/public",
)

# --------------------------------------------------------------------------
# Time and paths. "now" is always computed; no absolute path is ever hardcoded.
# --------------------------------------------------------------------------


def utcnow_iso() -> str:
    """ISO-8601 UTC, second precision, Z-suffixed. Computed, never hardcoded."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_root() -> "pathlib.Path":
    """Resolve the run/cache root. Creates nothing.

    Precedence, in order:
      1. $OWNER_TRACE_CACHE
      2. ~/Library/Caches/claude-owner-enrich   (macOS -- Mitch's machine)
      3. $XDG_CACHE_HOME/claude-owner-enrich
      4. ~/.cache/claude-owner-enrich

    Intermediates, fixtures, caches and the ledger live here and nowhere else.
    They are outside any synced tree on purpose: CENSUS.json, HUMANS.json and
    phone_verdicts.json carry names, home addresses, phones and deceased flags.
    """
    env = os.environ.get("OWNER_TRACE_CACHE")
    if env:
        return pathlib.Path(env).expanduser()
    home = pathlib.Path.home()
    mac = home / "Library" / "Caches"
    if mac.is_dir():
        return mac / "claude-owner-enrich"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser() / "claude-owner-enrich"
    return home / ".cache" / "claude-owner-enrich"


def run_dir(state: str, county: str, when: "_dt.datetime | None" = None) -> "pathlib.Path":
    """cache_root()/runs/<state>_<county>_<YYYYMMDD-HHMM>/ -- creates nothing."""
    when = when or _dt.datetime.now()
    slug = re.sub(r"[^a-z0-9]+", "_", str(county).lower()).strip("_")
    st = re.sub(r"[^a-z0-9]+", "", str(state).lower())
    return cache_root() / "runs" / "{}_{}_{}".format(st, slug, when.strftime("%Y%m%d-%H%M"))


# --------------------------------------------------------------------------
# Owner-name normalization
# --------------------------------------------------------------------------

_CO_PREFIX_RE = re.compile(r"^\s*(?:C\s*/\s*O|C\s+O|ATTN\.?|ATTENTION|%)\s*:?\s*", re.I)
_ETAL_RE = re.compile(r"\b(?:ET\s*AL|ETAL|ET\s*UX|ET\s*VIR|AND\s+OTHERS)\b", re.I)

_SUFFIX_TOKENS = (
    "LLC", "L L C", "LC", "INC", "INCORPORATED", "CORP", "CORPORATION",
    "COMPANY", "CO", "LP", "LLP", "LLLP", "LTD", "LIMITED", "PLLC",
    "PARTNERSHIP", "TRUST", "TR", "PA",
)
# Longest-first so "COMPANY" is consumed before "CO".
_SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(t) for t in _SUFFIX_TOKENS),
                               key=len, reverse=True)) + r")\b"
)

# Corporate markers used by is_company()/classify(). Deliberately narrower than
# the strip list: these are suffixes that *make* something a company.
_COMPANY_RE = re.compile(
    r"\b(?:LLC|L\s+L\s+C|LC|INC|INCORPORATED|CORP|CORPORATION|COMPANY|CO|LP|LLP|"
    r"LLLP|LTD|LIMITED|PLLC|PC|PA|PARTNERSHIP|ASSN|ASSOCIATION|HOLDINGS?)\b"
)

# Trust markers. Bare ESTATE is NOT one -- otherwise REAL ESTATE INVESTMENTS INC
# escapes the company block and classifies as a trust.
_TRUST_RE = re.compile(
    r"\b(?:TRUST|TRUSTS|TRUSTEE|TRUSTEES|TRUSTE|TR|TRS|LIVING\s+TRUST|"
    r"REVOCABLE|IRREVOCABLE|TESTAMENTARY|LAND\s+TRUST|LIFE\s+EST(?:ATE)?|"
    r"REMAINDER|LIFE\s+TENANT)\b"
)
_ESTATE_OF_RE = re.compile(r"\bEST(?:ATE)?\s+OF\b")
# "CO TR" is co-trustee. Neutralized before company detection or the CO reads
# as Company and a co-trustee row classifies as an entity.
_CO_TR_RE = re.compile(r"\bCO[\s\-]*(TR|TRS|TRUSTEE|TRUSTEES)\b")

_GOV_RE = re.compile(
    r"\b(?:STATE\s+OF|COUNTY\s+OF|CITY\s+OF|TOWN\s+OF|VILLAGE\s+OF|BOROUGH\s+OF|"
    r"UNITED\s+STATES|U\s*S\s*A|FEDERAL|DEPARTMENT\s+OF|DEPT\s+OF|BOARD\s+OF|"
    r"BUREAU\s+OF|COMMISSION|MUNICIPAL|MUNICIPALITY|SCHOOL\s+(?:BOARD|DISTRICT)|"
    r"HOUSING\s+AUTHORITY|PORT\s+AUTHORITY|WATER\s+MANAGEMENT|"
    r"PUBLIC\s+(?:WORKS|UTILIT\w+)|CONSERVATION\s+DISTRICT)\b"
)
_GOV_TAIL_RE = re.compile(r"\b(?:STATE|COUNTY|CITY|TOWN)\s+OF\s*$")

_TRUST_CO_RE = re.compile(r"\bTRUST\b.*\b(?:LLC|INC|CORP|COMPANY|BANK|ADVISORS|SERVICES)\b")
_INSTITUTIONAL_TRUSTEE_RE = re.compile(
    r"\b(?:BANK|BANKERS|TRUST\s+COMPANY|ADVISORS|ADVISERS|SERVICES|FIDUCIARY|"
    r"WEALTH|CAPITAL\s+MANAGEMENT|N\s*A)\b"
)


def norm_owner(s):
    """-> {"spaced": str, "tight": str}.

    Strips a leading C/O | ATTN | %, removes ET AL / ETAL / ET UX / ET VIR /
    AND OTHERS, maps every character outside [A-Z0-9& ] to a space, and collapses
    runs of whitespace. The tight form drops all spaces -- it is what caught the
    13 `C S X TRANSPORTATION` parcels that the spaced form missed.
    """
    s = "" if s is None else str(s)
    s = s.strip().upper()
    s = _CO_PREFIX_RE.sub("", s)
    s = _ETAL_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9& ]+", " ", s)
    spaced = re.sub(r"\s+", " ", s).strip()
    return {"spaced": spaced, "tight": spaced.replace(" ", "").replace("&", "")}


def strip_suffix(s):
    """norm_owner()["spaced"] with entity suffixes and leading/trailing THE removed.

    `ET AL` and a trailing `+` caused three registry misses; both are handled
    here rather than at the call site.
    """
    spaced = norm_owner(s)["spaced"]
    out = _SUFFIX_RE.sub(" ", spaced)
    out = re.sub(r"^\s*THE\b", " ", out)
    out = re.sub(r"\bTHE\s*$", " ", out)
    out = re.sub(r"[+&]\s*$", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _has_trust_marker(spaced):
    return bool(_TRUST_RE.search(spaced) or _ESTATE_OF_RE.search(spaced))


def is_company(s):
    """True when a corporate suffix is present AND no trust marker is.

    This is the guard that stops `MARTIN MARIETTA MATERIALS INC` parsing to
    "Marietta Martin" and `CARTER MILL LLC` to "Mill Carter". CARTER and MILL are
    both legitimate personal names -- the lexicon cannot save you here, only the
    suffix can.
    """
    spaced = norm_owner(s)["spaced"]
    if _has_trust_marker(spaced):
        return False
    return bool(_COMPANY_RE.search(spaced))


def classify(owner_raw):
    """-> {"owner_class", "entity_type", "reason", "matched_pattern"}.

    Evaluation order is load-bearing:
        gov -> trust_company -> trust/estate -> entity -> individual

    owner_class routes the whole pipeline: individual -> trace, entity -> pierce,
    trust -> deed, gov -> suppress.
    """
    spaced = norm_owner(owner_raw)["spaced"]
    if not spaced:
        return {"owner_class": "individual", "entity_type": "unknown",
                "reason": "empty owner string", "matched_pattern": ""}

    m = _GOV_RE.search(spaced) or _GOV_TAIL_RE.search(spaced)
    if m:
        return {"owner_class": "gov", "entity_type": "gov",
                "reason": "government/public owner pattern",
                "matched_pattern": m.group(0)}

    trust_marker = _has_trust_marker(spaced)
    # Neutralize co-trustee before any company test.
    de_cotr = _CO_TR_RE.sub(" TRUSTEE ", spaced)

    if trust_marker:
        m = _TRUST_CO_RE.search(spaced)
        if m:
            return {"owner_class": "trust_company", "entity_type": "trust_company",
                    "reason": "trust marker with institutional suffix",
                    "matched_pattern": m.group(0)}
        m = _INSTITUTIONAL_TRUSTEE_RE.search(de_cotr)
        if m:
            return {"owner_class": "trust_company", "entity_type": "trust_company",
                    "reason": "institutional trustee (bank/advisor/trust company)",
                    "matched_pattern": m.group(0)}
        et = "estate" if _ESTATE_OF_RE.search(spaced) else "trust"
        return {"owner_class": "trust", "entity_type": et,
                "reason": "trust/estate marker present, no institutional suffix",
                "matched_pattern": (_TRUST_RE.search(spaced) or
                                    _ESTATE_OF_RE.search(spaced)).group(0)}

    m = _COMPANY_RE.search(de_cotr)
    if m:
        tok = m.group(0).replace(" ", "")
        et = {"LLC": "llc", "LLC": "llc", "LC": "llc", "PLLC": "llc",
              "LP": "lp", "LLP": "lp", "LLLP": "lp", "PARTNERSHIP": "lp"}.get(tok, "corp")
        return {"owner_class": "entity", "entity_type": et,
                "reason": "corporate suffix, no trust marker",
                "matched_pattern": m.group(0)}

    return {"owner_class": "individual", "entity_type": "individual",
            "reason": "no gov/trust/corporate marker", "matched_pattern": ""}


def split_owner_string(s):
    """Split a packed assessor owner string on the ampersand rule.

    Knox packs both owners into one field:
        "FUGATE RONALD ALLEN & VIRGINIA M"
            -> ["FUGATE RONALD ALLEN", "FUGATE VIRGINIA M"]
    while Union NC writes both surnames out:
        "ACUFF GARY HERBERT & ACUFF ANN DENISE"   (unchanged)

    Trust and company strings are returned whole -- `BRIAN & CONNIE PIERCE LIVING
    TRUST` is the shared-surname trust idiom and belongs to free_pierce.py, not
    here.
    """
    spaced = norm_owner(s)["spaced"]
    if not spaced:
        return []
    if _has_trust_marker(spaced) or _COMPANY_RE.search(spaced):
        return [spaced]
    parts = [p.strip() for p in re.split(r"\s*&\s*|\s+AND\s+", spaced) if p.strip()]
    if len(parts) < 2:
        return [spaced]
    head = parts[0].split()
    if len(head) < 2:
        return [spaced]
    surname = head[0]
    out = [parts[0]]
    for p in parts[1:]:
        toks = p.split()
        if not toks:
            continue
        if toks[0] == surname:
            out.append(p)
        else:
            out.append(surname + " " + p)
    return out


# --------------------------------------------------------------------------
# Address normalization
# --------------------------------------------------------------------------

_CSZ_RE = re.compile(
    r"^(?P<city>.+?),?\s+(?P<st>[A-Z]{2})(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?$"
)


def csz_split(s):
    """Parse a combined "CITY, ST ZIP" blob FROM THE RIGHT.

    Knox ships `"KNOXVILLE, TN 37931"` as a single field. A naive left-to-right
    split produced 33 of 312 mangled rows (`city="SAINT", state="LO"` from
    `SAINT PETERSBURG FL 33701`). The lazy city group plus the anchored state and
    ZIP groups backtrack correctly.

    Returns {"city","state","zip","ok","reason"}. `ok` is False whenever the
    state code fails validation -- do not submit an unvalidated state to a vendor.

    NOTE: this is not the fix for the Sherpa /api/business 404s. Empirically the
    33 mangled rows scored 19/34 with a person (56%) against 87/257 (34%) for
    well-formed rows. That is a separate bug -- see references/traps.md.
    """
    raw = ("" if s is None else str(s)).strip().upper()
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        return {"city": "", "state": "", "zip": "", "ok": False, "reason": "empty"}
    m = _CSZ_RE.match(raw)
    if not m:
        return {"city": "", "state": "", "zip": "", "ok": False,
                "reason": "no CITY ST [ZIP] pattern in {!r}".format(raw)}
    city = m.group("city").strip().rstrip(",").strip()
    st = m.group("st")
    zp = m.group("zip") or ""
    if st in STATE_CODES:
        return {"city": city, "state": st, "zip": zp, "ok": True, "reason": ""}
    if st in TERRITORY_CODES:
        return {"city": city, "state": st, "zip": zp, "ok": True, "reason": "territory code"}
    return {"city": city, "state": "", "zip": zp, "ok": False,
            "reason": "invalid state code {!r}".format(st)}


_STREET_SYNONYMS = {
    "ROAD": "RD", "RD": "RD", "DRIVE": "DR", "DR": "DR", "LANE": "LN", "LN": "LN",
    "STREET": "ST", "STR": "ST", "ST": "ST", "AVENUE": "AVE", "AV": "AVE",
    "AVE": "AVE", "PIKE": "PIKE", "PK": "PIKE", "HIGHWAY": "HWY", "HWY": "HWY",
    "CIRCLE": "CIR", "CIR": "CIR", "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "COURT": "CT", "CT": "CT", "PLACE": "PL", "PL": "PL", "TRAIL": "TRL",
    "TRL": "TRL", "PARKWAY": "PKWY", "PKWY": "PKWY", "TERRACE": "TER", "TER": "TER",
    "WAY": "WAY",
}
_DIRECTIONALS = frozenset({
    "N", "S", "E", "W", "NE", "NW", "SE", "SW",
    "NORTH", "SOUTH", "EAST", "WEST", "NORTHEAST", "NORTHWEST",
    "SOUTHEAST", "SOUTHWEST",
})
_DIR_CANON = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
_UNIT_RE = re.compile(
    r"\b(?:STE|SUITE|UNIT|APT|APARTMENT|RM|ROOM|FL|FLOOR|BLDG|BUILDING|DEPT|#)\b.*$"
)
_POBOX_RE = re.compile(r"\bP\.?\s*O\.?\s*BOX\b|\bPOBOX\b|\bPOST\s+OFFICE\s+BOX\b")


def _clean_street(street):
    s = ("" if street is None else str(street)).strip().upper()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"-\d{4}\b", "", s)          # ZIP+4 fragments
    return s


def naddr(street, csz=""):
    """Coarse dedupe key. Collapses street-type synonyms and DELETES all
    directionals, then reduces to [A-Z0-9].

    Deliberately lossy -- this is for clustering, not for anchoring. Use
    addr_key() when the answer decides whether a person is accepted.
    """
    s = _clean_street(street) + (" " + str(csz).upper() if csz else "")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    toks = []
    for t in s.split():
        if t in _DIRECTIONALS:
            continue
        toks.append(_STREET_SYNONYMS.get(t, t))
    return re.sub(r"[^A-Z0-9]", "", " ".join(toks))


def _strip_co_line(street):
    """Strip a leading `C/O <name>` up to the PO Box or house number.

    Wingate University's mail runs through two named staffers at one box:
    `C O TAMMY BRITT PO BOX 159` and `C O JENNY WALDEN PO BOX 159`. The box is
    the identity, not the staffer.
    """
    s = street
    if not _CO_PREFIX_RE.match(s) and not re.match(r"^\s*(?:C\s*/?\s*O|ATTN|%)\b", s):
        return s
    m = _POBOX_RE.search(s)
    if m:
        return s[m.start():]
    m = re.search(r"\b\d+\b", s)
    if m:
        return s[m.start():]
    return _CO_PREFIX_RE.sub("", s)


def addr_key(street, city="", state="", zip5=""):
    """The anchor comparison key: "street|city|ST|zip5".

    Truncates at a unit marker, strips a leading C/O line, canonicalizes street
    types and directionals -- but does NOT delete directionals. naddr() deletes
    them because it is a clustering key; the anchor is the verdict, and
    collapsing `100 N MAIN` into `100 S MAIN` would accept the wrong household.
    """
    s = _clean_street(street)
    s = _strip_co_line(s)
    s = _UNIT_RE.sub("", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    toks = []
    for t in s.split():
        t = _DIR_CANON.get(t, t)
        toks.append(_STREET_SYNONYMS.get(t, t))
    street_key = re.sub(r"[^A-Z0-9]", "", " ".join(toks))
    city_key = re.sub(r"[^A-Z0-9]", "", str(city or "").upper())
    st_key = re.sub(r"[^A-Z]", "", str(state or "").upper())[:2]
    z = re.sub(r"[^0-9]", "", str(zip5 or ""))[:5]
    return "{}|{}|{}|{}".format(street_key, city_key, st_key, z)


def napn(s):
    """Normalized APN: uppercase, alphanumerics only."""
    return re.sub(r"[^A-Z0-9]", "", ("" if s is None else str(s)).upper())


def split_apns(cell):
    """Split a multi-APN cell on [;,] and normalize each. Never truncated."""
    if cell is None:
        return []
    out = []
    for part in re.split(r"[;,]", str(cell)):
        n = napn(part)
        if n and n not in out:
            out.append(n)
    return out


# --------------------------------------------------------------------------
# Line type, names, phones
# --------------------------------------------------------------------------


def normalize_line_type(t):
    """Collapse three vendors' three spellings of one fact.

    one-api emits capitalized `Wireless|Landline|Voip`, Sherpa lowercase
    `mobile|landline|voip|other`, Tracerfy capitalized `Mobile|Landline`. A build
    that maps only `wire*` scores every Tracerfy row has_wire=False and silently
    reports the whole backbone as landlines.
    """
    t = ("" if t is None else str(t)).strip().lower()
    if t.startswith("wire") or t.startswith("mob"):
        return "wireless"
    if t.startswith("land"):
        return "landline"
    if "voip" in t:
        return "voip"
    return t


def surname5_prefix_match(a, b):
    """Bidirectional 5-character surname prefix match.

    RANKING AND LEAD SIGNAL ONLY. It is removed from every acceptance predicate
    (spec s9 rule 2): at five characters it confidently accepts the wrong Smith,
    and it is partly circular anyway -- you queried the vendor for a named
    candidate, then credited the vendor for returning that candidate's surname.
    No predicate in this module calls it.
    """
    a = re.sub(r"[^A-Z]", "", ("" if a is None else str(a)).upper())
    b = re.sub(r"[^A-Z]", "", ("" if b is None else str(b)).upper())
    if not a or not b:
        return False
    return a.startswith(b[:5]) or b.startswith(a[:5])


def levenshtein(a, b):
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def fuzzy_owner_merge_ok(a, b, same_mailing):
    """Fuzzy owner merging ONLY between owners already sharing a mailing address,
    bounded at Levenshtein <= 2. Unbounded fuzzy merging across the whole list
    silently fuses unrelated owners.
    """
    if not same_mailing:
        return False
    na = norm_owner(a)["tight"]
    nb = norm_owner(b)["tight"]
    if not na or not nb:
        return False
    return levenshtein(na, nb) <= 2


_COMMERCIAL_AGENT_RE = re.compile(
    r"\b(?:C\s*T\s+CORPORATION|CT\s+CORP\w*|CORPORATION\s+SERVICE\s+COMPANY|"
    r"\bCSC\b|REGISTERED\s+AGENTS?\s+(?:INC|LLC)|LEGALZOOM|LEGAL\s+ZOOM|"
    r"NATIONAL\s+REGISTERED\s+AGENTS|INCORP\s+SERVICES|COGENCY|VCORP|"
    r"NORTHWEST\s+REGISTERED\s+AGENT|HARVARD\s+BUSINESS\s+SERVICES|"
    r"UNITED\s+STATES\s+CORPORATION\s+AGENTS|SPIEGEL\s+UTRERA|"
    r"P\s*\.?\s*A\s*\.?$|\bPLLC\b|\bLLP\b|LAW\s+(?:OFFICES?|FIRM|GROUP)|"
    r"ATTORNEYS?\s+AT\s+LAW)\b"
)


def is_commercial_agent(name):
    """Commercial registered agents are recorded and skipped, never contacted.

    57% of FL registered agents are commercial dead ends before you spend
    anything -- catching them here is free.
    """
    s = norm_owner(name)["spaced"]
    if not s:
        return False
    return bool(_COMMERCIAL_AGENT_RE.search(s))


# Institutional families. Tested against BOTH the owner string and the mailing
# blob: `SOUTHERN REGION IND REALTY INC` and `ATLANTIC LAND & IMPROVEMENT COMPANY`
# are only identifiable as Norfolk Southern / CSX land subsidiaries via their C/O
# line.
RAIL_TIGHT = [
    r"CSXTRANSPORTATION", r"SEABOARDCOAST", r"SEABOARDCOASTLINE",
    r"FLORIDAEASTCOASTRAIL", r"NORFOLKSOUTHERN", r"RAILWAYCO", r"RAILROADCO",
    r"ATLANTICLAND.{0,4}IMPROVEMENT", r"SOUTHERNREGIONINDREALTY",
]
GOV_SPACED = [
    r"\bSTATE OF\b", r"\bCOUNTY OF\b", r"\bCITY OF\b", r"\bTOWN OF\b",
    r"\bUNITED STATES\b", r"\bBOARD OF\b", r"\bSCHOOL (?:BOARD|DISTRICT)\b",
    r"\bHOUSING AUTHORITY\b", r"\bWATER MANAGEMENT\b", r"\bTENNESSEE STATE OF\b",
]
CHURCH_SPACED = [
    r"\bCHURCH\b", r"\bBAPTIST\b", r"\bMETHODIST\b", r"\bPRESBYTERIAN\b",
    r"\bCATHOLIC\b", r"\bDIOCESE\b", r"\bSYNOD\b", r"\bMINISTRIES\b",
    r"\bCONGREGATION\b", r"\bTEMPLE\b", r"\bMOSQUE\b", r"\bLODGE\b",
    r"\bFRATERNAL ORDER\b", r"\bAMERICAN LEGION\b", r"\bMASONIC\b",
]
CORP_MAIL = [
    r"\bTAX DEPT\b", r"\bTAX DEPARTMENT\b", r"PROPERTY TAX", r"GENERAL COUNSEL",
    r"\bINDIRECT TAX\b", r"ATTN\s*:?\s*TAX",
]
CORP_OWNER_TIGHT = [
    r"MARTINMARIETTA", r"FLORIDAROCKINDUSTRIES", r"SMYRNAREADYMIX",
    r"ANHEUSERBUSCH", r"OVERNITETRANSPORTATION", r"CONWAYTRANSPORTATION",
    r"TANDEMLEASING", r"STJOHNSRIVERTERMINAL", r"STLUKESSTVINCENTS",
    r"PUBLIXSUPERMARKETS", r"WALMART", r"DUKEENERGY", r"TAMPAELECTRIC",
]
SUPERFUND_TIGHT = [
    r"STAUFFERMANAGEMENT", r"SUPERFUND", r"REMEDIATIONTRUST",
    r"ENVIRONMENTALREMEDIATION",
]
_FAMILIES = (
    ("rail", RAIL_TIGHT, "tight"),
    ("gov", GOV_SPACED, "spaced"),
    ("church_civic", CHURCH_SPACED, "spaced"),
    ("corp_mail", CORP_MAIL, "spaced"),
    ("corp_owner", CORP_OWNER_TIGHT, "tight"),
    ("superfund", SUPERFUND_TIGHT, "tight"),
)


def institutional_match(owner_raw, mail_blob=""):
    """-> {"family","pattern","matched_on"} or None.

    Tests BOTH the owner string and the mailing blob. `ANHEUSER BUSCH BREWING
    PROPERTIES LLC` with `mail1: "ATTN GENERAL COUNSEL"` and 119 net acres is a
    real dropped row -- it is only catchable on the mail side.

    A match is a SUPPRESSION with a recorded pattern, not a deletion. Nothing is
    dropped silently, and a comment in a config is not a filter.
    """
    on = norm_owner(owner_raw)
    mn = norm_owner(mail_blob)
    for family, pats, mode in _FAMILIES:
        for p in pats:
            rx = re.compile(p)
            if mode == "tight":
                if on["tight"] and rx.search(on["tight"]):
                    return {"family": family, "pattern": p, "matched_on": "owner"}
                if mn["tight"] and rx.search(mn["tight"]):
                    return {"family": family, "pattern": p, "matched_on": "mail"}
            else:
                if on["spaced"] and rx.search(on["spaced"]):
                    return {"family": family, "pattern": p, "matched_on": "owner"}
                if mn["spaced"] and rx.search(mn["spaced"]):
                    return {"family": family, "pattern": p, "matched_on": "mail"}
    tight = on["tight"]
    for seed in SEED_INSTITUTIONAL:
        if tight and tight == norm_owner(seed)["tight"]:
            return {"family": "seed_list", "pattern": seed, "matched_on": "owner"}
    return None


def mail_class(street, city="", state="", zip5="", entity_count=None,
               index_available=False):
    """-> {"mail_class", "mail_class_reason", "mail_class_string", "agent_desk_gate"}

    Only `mail_class == "residential"` may be reverse-address searched (doctrine 9).
    Querying an LLC's office (`200 N Laura St, Jacksonville`) returned building
    tenants including a law-firm email.

    The agent-desk gate is a SEPARATE axis from the string classification, and it
    is Florida-only: the address-frequency index is built from the FL bulk file.
    For a TN/NC/TX/NY parcel there is no count, so the gate is UNEVALUATED and the
    combined class degrades to UNEVALUATED -- a missing count must never read as a
    clean residential pass (spec s6 scope caveat, acceptance test 9).
    """
    s = _clean_street(street)
    if not s:
        return {"mail_class": "none", "mail_class_reason": "empty mailing street",
                "mail_class_string": "none", "agent_desk_gate": UNKNOWN}

    if _POBOX_RE.search(s):
        string_class, reason = "po_box", "PO Box"
    elif _UNIT_RE.search(s) or re.match(r"^\s*(?:C\s*/?\s*O|ATTN|%)\b", s):
        string_class, reason = "suite_or_co", "suite/unit/C-O marker"
    else:
        inst = institutional_match("", s)
        if inst:
            string_class = "commercial"
            reason = "institutional mail pattern {}".format(inst["pattern"])
        else:
            string_class, reason = "residential", "no PO Box, unit or C/O marker"

    if entity_count is None:
        # No count. Only an available index makes "no filings here" a real finding;
        # otherwise the gate simply never ran.
        gate = "PASS" if index_available else UNKNOWN
    elif entity_count >= AGENT_DESK_MIN:
        gate = "FAIL"
    else:
        gate = "PASS"

    if string_class != "residential":
        return {"mail_class": string_class, "mail_class_reason": reason,
                "mail_class_string": string_class, "agent_desk_gate": gate}

    if gate == "FAIL":
        return {"mail_class": "commercial",
                "mail_class_reason": ("residential-looking but hosts {} registry filings "
                                      ">= AGENT_DESK_MIN {} -- agent desk, not a home"
                                      .format(entity_count, AGENT_DESK_MIN)),
                "mail_class_string": "residential", "agent_desk_gate": gate}
    if gate == UNKNOWN:
        return {"mail_class": "UNEVALUATED",
                "mail_class_reason": ("residential-looking, but the agent-desk gate never "
                                      "ran -- the entity address-frequency index is "
                                      "Florida-only. A missing count is not a clean pass."),
                "mail_class_string": "residential", "agent_desk_gate": UNKNOWN}
    return {"mail_class": "residential",
            "mail_class_reason": "{}; agent-desk gate passed ({} filings)".format(
                reason, entity_count),
            "mail_class_string": "residential", "agent_desk_gate": gate}


_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_MONTH_RE = re.compile(r"([A-Za-z]{3})\w*\s+(\d{4})")


def month_num(s):
    """Parse the literal vendor form `"Last reported Jul 2026"` -> (2026, 7)."""
    if not s:
        return None
    m = _MONTH_RE.search(str(s))
    if not m:
        return None
    mon = _MONTHS.get(m.group(1)[:3].upper())
    if not mon:
        return None
    return (int(m.group(2)), mon)


def phone_sort_key(phone, now=None):
    """Ordering key for a phone dict.

    -> (recency_band, dnc_penalty, TYPE_RANK, -last_absolute_month)

    recency_band: 0 if last seen >= now-18mo, 1 if >= now-48mo, else 2. "now" is
    COMPUTED, never hardcoded -- the source builder froze it at `2026*12 + 7`.

    dnc_penalty sits ABOVE type rank so a DNC=True mobile sinks below a clean
    landline in the same recency band, and a blank/UNKNOWN DNC never ranks as
    clean. Recency still outranks both (doctrine 8): a Wireless number last seen
    2016 is worse than a landline seen this year, because of the FCC
    reassigned-number hazard.

    `phone` keys used: last_seen (str or (y,m)), type, dnc.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    now_abs = now.year * 12 + now.month

    ls = phone.get("last_seen") or phone.get("last_reported") or ""
    ym = ls if isinstance(ls, (tuple, list)) and len(ls) == 2 else month_num(ls)
    if ym:
        last_abs = int(ym[0]) * 12 + int(ym[1])
        age = now_abs - last_abs
        band = 0 if age <= 18 else (1 if age <= 48 else 2)
    else:
        last_abs = 0
        band = 2

    dnc = phone.get("dnc", None)
    if dnc is True or str(dnc).strip().lower() == "true":
        dnc_penalty = 2
    elif dnc is False or str(dnc).strip().lower() == "false":
        dnc_penalty = 0
    else:
        dnc_penalty = 1          # unknown: worse than clean, better than blocked

    t = normalize_line_type(phone.get("type"))
    return (band, dnc_penalty, TYPE_RANK.get(t, 4), -last_abs)


def tri(value):
    """-> "Y" | "N" | "UNKNOWN".

    Doctrine 18: every truth-valued field supports UNKNOWN, and missing evidence
    is never coerced to N/false. A deceased check that never ran must not render
    as "not deceased"; an address gate that was never evaluated must render as
    neither passed nor failed.
    """
    if value is None:
        return UNKNOWN
    if isinstance(value, str):
        v = value.strip().upper()
        if v in ("", "UNKNOWN", "UNEVALUATED", "NULL", "NONE", "N/A"):
            return UNKNOWN
        if v in ("Y", "YES", "TRUE", "T", "1"):
            return "Y"
        if v in ("N", "NO", "FALSE", "F", "0"):
            return "N"
        return UNKNOWN
    if isinstance(value, bool):
        return "Y" if value else "N"
    return UNKNOWN


def provenance(source, retrieved_at=None, anchor_basis=None, identity_tier=None,
               confidence_basis=None):
    """The five provenance keys every emitted field carries.

    A $0 name parse must never render like a verified mobile; this block is what
    keeps them distinguishable downstream.
    """
    return {
        "source": source,
        "retrieved_at": retrieved_at or utcnow_iso(),
        "anchor_basis": anchor_basis if anchor_basis is not None else UNKNOWN,
        "identity_tier": identity_tier if identity_tier is not None else UNKNOWN,
        "confidence_basis": confidence_basis if confidence_basis is not None else UNKNOWN,
    }


# Catches 314-555-0177, (314) 555-0177, +1 (630) 555-0195, 630.555.0195,
# 6305550195. The inherited regex `\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b` missed both
# parenthesized forms.
PHONE_RE = re.compile(
    r"(?<![0-9])(?:\+?1[\s.\-]?)?(?:\(\s*[2-9]\d{2}\s*\)|[2-9]\d{2})"
    r"[\s.\-]?[2-9]\d{2}[\s.\-]?\d{4}(?![0-9])"
)


def redact_phones(text, replacement="[REDACTED-PHONE]"):
    """-> (redacted_text, count). Used by leak_scan.py outside approved columns."""
    if text is None:
        return ("", 0)
    s = str(text)
    n = len(PHONE_RE.findall(s))
    return (PHONE_RE.sub(replacement, s), n)


# --------------------------------------------------------------------------
# Predicates (spec s9). Each takes an evidence dict and returns (bool, reason).
#
# Every one of these fails CLOSED. None of them reference surname5_prefix_match.
# --------------------------------------------------------------------------


def title_ok(ev):
    a = ev.get("latest_effective_recorded_grantee_matches_candidate_owner")
    b = ev.get("no_later_conflicting_instrument")
    if a is not True:
        return (False, "no recorded grantee match (tax roll alone is TAX-ROLL-OWNER)")
    if b is not True:
        return (False, "a later or conflicting instrument exists or was not checked")
    return (True, "recorded grantee matches and no later conflicting instrument")


def entity_ok(ev):
    if ev.get("registry_jurisdiction_and_entity_id_match") is True:
        return (True, "matched on jurisdiction + entity number")
    if ev.get("exact_legal_name_match") is not True:
        return (False, "no entity id and no exact legal-name match")
    n = int(ev.get("independent_discriminators") or 0)
    if n < 2:
        return (False, "exact name but only {} independent discriminator(s); "
                       "AMBIGUOUS-ENTITY-MATCH".format(n))
    if ev.get("no_competing_registry_candidate") is not True:
        return (False, "a competing registry candidate exists; AMBIGUOUS-ENTITY-MATCH")
    return (True, "exact legal name + {} discriminators, no competing candidate".format(n))


def role_ok(ev):
    """True only on a control-bearing edge from a government record.

    A registered-agent, director, generic-officer or limited-partner edge can
    never by itself establish authority. `ELLISON ROAD, LLC` -- agent Arnold H
    Slott, manager the CHARLES W. BOSTWICK TRUST -- is the shape this prevents.
    """
    if ev.get("person_is_direct_natural_person_grantee") is True:
        return (True, "named directly as natural-person grantee on the deed")
    edges = ev.get("edges") or []
    kinds = set()
    for e in edges:
        k = e.get("edge_type") if isinstance(e, dict) else str(e)
        if k:
            kinds.add(k)
    control = kinds & CONTROL_EDGES
    if control:
        srcd = ev.get("edge_source_is_government_record")
        if srcd is not True:
            return (False, "control edge {} present but not from a government "
                           "record".format(sorted(control)))
        return (True, "government record names the person as {}".format(sorted(control)))
    if kinds and kinds <= NONCONTROL_EDGES:
        return (False, "only non-control edges present ({}) -- these never establish "
                       "control".format(sorted(kinds)))
    return (False, "no control-bearing edge")


def person_ok(ev):
    if ev.get("full_normalized_name_or_documented_alias_matches") is not True:
        return (False, "name did not match in full normalized or documented-alias form")
    if ev.get("no_conflicting_person_with_same_name") is not True:
        return (False, "a conflicting person with the same name exists or was not checked")
    return (True, "full normalized name matches with no same-name conflict")


def strong_address_match(ev):
    needed = (
        ("primary_number_or_po_box_matches", "house number / PO box"),
        ("street_name_matches", "street name"),
        ("city_state_zip5_match", "city/state/zip5"),
        ("required_secondary_unit_matches", "secondary unit"),
    )
    for key, label in needed:
        if ev.get(key) is not True:
            return (False, "{} did not match or was not evaluated".format(label))
    if ev.get("not_cmra_or_agent_hub") is not True:
        return (False, "address is a CMRA/agent hub, or RDI/CMRA classification "
                       "never ran (do not guess from the string)")
    return (True, "strong address match on all components, not a CMRA or agent hub")


def phone_attributed(ev):
    """Two upstream-INDEPENDENT sources, or it is SINGLE-SOURCE-PHONE.

    Two Apify actors reselling the same people-search aggregator are one source
    wearing two hats. Lineage is read from the capability manifest; if lineage is
    unknown this fails closed. A carrier/HLR lookup confirms the number's TYPE,
    not its SUBSCRIBER, and never satisfies source B.
    """
    if ev.get("source_a_names_the_exact_person_and_lists_the_phone") is not True:
        return (False, "source A does not name the exact person and list this phone")
    ok_addr, why = strong_address_match(ev)
    if not ok_addr and ev.get("source_a_has_another_strong_identifier") is not True:
        return (False, "source A: {} and no other strong identifier".format(why))
    lineage = ev.get("source_b_upstream_lineage")
    if ev.get("source_b_present") is not True:
        return (False, "no source B -- SINGLE-SOURCE-PHONE")
    if not lineage or str(lineage).strip().upper() in (UNKNOWN, "UNDECLARED", ""):
        return (False, "source B lineage undeclared -- fails closed to SINGLE-SOURCE-PHONE")
    if ev.get("source_b_is_UPSTREAM_INDEPENDENT") is not True:
        return (False, "source B shares upstream lineage with source A ({}) -- one "
                       "source wearing two hats".format(lineage))
    if ev.get("source_b_is_carrier_or_hlr_only") is True:
        return (False, "source B is a carrier/HLR lookup -- confirms line type, not "
                       "subscriber")
    if ev.get("source_b_reverse_matches_exact_full_name_or_strong_address") is not True:
        return (False, "source B did not reverse-match the exact full name or a strong "
                       "address")
    if ev.get("any_current_source_contradicts_the_subscriber") is True:
        return (False, "a current source contradicts the subscriber -- CONTRADICTED")
    return (True, "two upstream-independent sources attribute this phone to this person")


def mobile_confirmed(ev):
    """Wireless status never increases ownership or role confidence -- line type
    answers a different question. A VERIFIED-MOBILE on an UNKNOWN owner is still
    an unknown owner.
    """
    ok, why = phone_attributed(ev)
    if not ok:
        return (False, "phone not attributed: {}".format(why))
    src = ev.get("line_type_source")
    if src not in LINE_TYPE_SOURCE_ALLOWLIST:
        return (False, "line_type_source {!r} is not in the allowlist -- line type must "
                       "come from the source record, never computed".format(src))
    if normalize_line_type(ev.get("source_line_type")) != "wireless":
        return (False, "source line type is not wireless")
    return (True, "attributed phone with source-reported wireless line type")


def outreach_eligible(ev):
    """dnc == False is NOT consent. It means "not found on the lists checked, at
    that time."
    """
    ok, why = mobile_confirmed(ev)
    if not ok:
        return (False, why)
    checked_at = ev.get("dnc_checked_at")
    if not checked_at:
        return (False, "no DNC check on record -- {}".format(NOT_SCRUBBED_STAMP))
    age = ev.get("dnc_checked_age_days")
    if age is None:
        return (False, "DNC check age unknown -- treat as stale, {}".format(NOT_SCRUBBED_STAMP))
    if int(age) > DNC_REFRESH_DAYS:
        return (False, "DNC scrub is {} days old (> {}) -- stale, re-renders "
                       "UNSCRUBBED".format(age, DNC_REFRESH_DAYS))
    for flag, label in (("national_dnc", "national DNC"),
                        ("applicable_state_dnc", "state DNC"),
                        ("internal_dnc", "internal do-not-call list")):
        if ev.get(flag) is True:
            return (False, "listed on {}".format(label))
        if ev.get(flag) is None:
            return (False, "{} status unknown -- fails closed".format(label))
    if str(ev.get("deceased_status") or "").upper() == "REPORTED-DECEASED":
        return (False, "REPORTED-DECEASED -- hard stop, route to estate/heir research")
    if ev.get("is_litigator") is True:
        return (False, "TCPA litigator -- excluded from every import tab")
    if ev.get("state_outreach_policy_allows_channel") is not True:
        return (False, "state outreach policy for this channel is not confirmed "
                       "(counsel-maintained matrix, never hard-coded from vendor logic)")
    return (True, "attributed wireless, currently scrubbed clean, channel permitted")


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------

def _selftest():
    checks = []

    def ck(name, got, want):
        ok = got == want
        checks.append((ok, name, got, want))

    ck("normalize_line_type Mobile", normalize_line_type("Mobile"), "wireless")
    ck("normalize_line_type Wireless", normalize_line_type("Wireless"), "wireless")
    ck("normalize_line_type LandLine", normalize_line_type("LandLine"), "landline")
    ck("normalize_line_type Voip", normalize_line_type("Voip"), "voip")
    ck("normalize_line_type blank", normalize_line_type(""), "")

    r = csz_split("SAINT PETERSBURG FL 33701")
    ck("csz SAINT PETERSBURG", (r["city"], r["state"], r["zip"]),
       ("SAINT PETERSBURG", "FL", "33701"))
    r = csz_split("KNOXVILLE, TN 37931")
    ck("csz KNOXVILLE", (r["city"], r["state"], r["zip"]), ("KNOXVILLE", "TN", "37931"))

    ck("split_owner_string Knox", split_owner_string("FUGATE RONALD ALLEN & VIRGINIA M"),
       ["FUGATE RONALD ALLEN", "FUGATE VIRGINIA M"])
    ck("split_owner_string Acuff",
       split_owner_string("ACUFF GARY HERBERT & ACUFF ANN DENISE"),
       ["ACUFF GARY HERBERT", "ACUFF ANN DENISE"])

    ck("is_company MARTIN MARIETTA", is_company("MARTIN MARIETTA MATERIALS INC"), True)
    ck("is_company CARTER MILL", is_company("CARTER MILL LLC"), True)
    ck("is_company PIERCE trust", is_company("BRIAN & CONNIE PIERCE LIVING TRUST"), False)

    ck("classify REAL ESTATE INVESTMENTS INC",
       classify("REAL ESTATE INVESTMENTS INC")["owner_class"], "entity")
    ck("classify SMITH FAMILY TRUST", classify("SMITH FAMILY TRUST")["owner_class"], "trust")
    ck("classify CO TR", classify("MILAM STEPHEN WESLEY CO TR")["owner_class"], "trust")
    ck("classify institutional trustee",
       classify("CITY NATIONAL BANK OF FLORIDA TRUSTEE")["owner_class"], "trust_company")
    ck("classify gov", classify("TENNESSEE STATE OF")["owner_class"], "gov")

    ck("addr_key C/O collapse",
       addr_key("C O TAMMY BRITT PO BOX 159", "WINGATE", "NC", "28174") ==
       addr_key("C O JENNY WALDEN PO BOX 159", "WINGATE", "NC", "28174"), True)

    ck("fuzzy merge same mailing",
       fuzzy_owner_merge_ok("LANDPEDDLARS", "LANDPEDDLERS", True), True)
    ck("fuzzy merge different mailing",
       fuzzy_owner_merge_ok("LANDPEDDLARS", "LANDPEDDLERS", False), False)

    ck("tri None", tri(None), UNKNOWN)
    ck("tri False", tri(False), "N")
    ck("tri True", tri(True), "Y")

    now = _dt.datetime(2026, 8, 11, tzinfo=_dt.timezone.utc)
    dnc_mobile = {"type": "Mobile", "dnc": True, "last_seen": "Jul 2026"}
    clean_land = {"type": "Landline", "dnc": False, "last_seen": "Jul 2026"}
    ck("DNC mobile sinks below clean landline",
       phone_sort_key(dnc_mobile, now) > phone_sort_key(clean_land, now), True)
    blank_dnc = {"type": "Mobile", "dnc": None, "last_seen": "Jul 2026"}
    clean_mobile = {"type": "Mobile", "dnc": False, "last_seen": "Jul 2026"}
    ck("blank DNC never ranks as clean",
       phone_sort_key(blank_dnc, now) > phone_sort_key(clean_mobile, now), True)

    ck("redact parenthesized", redact_phones("call (314) 555-0177 now")[1], 1)
    ck("redact +1 form", redact_phones("call +1 (630) 555-0195 now")[1], 1)

    ck("mail_class non-FL is UNEVALUATED",
       mail_class("10205 COWARD MILL RD", "KNOXVILLE", "TN", "37931")["mail_class"],
       "UNEVALUATED")
    ck("mail_class agent desk",
       mail_class("150 SE 2ND AVE", "MIAMI", "FL", "33131", entity_count=1381,
                  index_available=True)["mail_class"], "commercial")
    ck("mail_class residential with index",
       mail_class("10205 COWARD MILL RD", "KNOXVILLE", "TN", "37931", entity_count=1,
                  index_available=True)["mail_class"], "residential")

    ck("role_ok rejects registered-agent only",
       role_ok({"edges": [{"edge_type": "registered-agent"}],
                "edge_source_is_government_record": True})[0], False)
    ck("role_ok rejects director only",
       role_ok({"edges": [{"edge_type": "director"}],
                "edge_source_is_government_record": True})[0], False)
    ck("role_ok accepts manager",
       role_ok({"edges": [{"edge_type": "manager"}],
                "edge_source_is_government_record": True})[0], True)

    ck("phone_attributed fails closed on undeclared lineage",
       phone_attributed({
           "source_a_names_the_exact_person_and_lists_the_phone": True,
           "source_a_has_another_strong_identifier": True,
           "source_b_present": True,
           "source_b_upstream_lineage": None,
           "source_b_is_UPSTREAM_INDEPENDENT": True,
           "source_b_reverse_matches_exact_full_name_or_strong_address": True,
       })[0], False)

    ck("is_commercial_agent CT Corporation", is_commercial_agent("CT CORPORATION SYSTEM"), True)
    ck("institutional_match via mail C/O",
       (institutional_match("ANHEUSER BUSCH BREWING PROPERTIES LLC",
                            "ATTN GENERAL COUNSEL") or {}).get("family"), "corp_mail")

    failed = [c for c in checks if not c[0]]
    for ok, name, got, want in checks:
        print("{} {}".format("PASS" if ok else "FAIL", name))
        if not ok:
            print("      got={!r} want={!r}".format(got, want))
    print("octlib selftest: {} checks, {} failed".format(len(checks), len(failed)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="octlib.py",
        description="Shared library for owner-contact-trace. Import it; the CLI only "
                    "runs the embedded selftest.")
    ap.add_argument("--selftest", action="store_true",
                    help="run the embedded checks and exit nonzero on any failure")
    ap.add_argument("--cache-root", action="store_true",
                    help="print the resolved cache root and exit")
    args = ap.parse_args(argv)
    if args.cache_root:
        print(cache_root())
        return 0
    if args.selftest:
        return _selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
