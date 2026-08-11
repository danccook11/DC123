"""octlib unit tests.

The bulk of octlib's behaviour is exercised through tests/test_acceptance.py, because every
one of those assertions is ultimately about a normalization or predicate in this module.
What lives here is the embedded selftest plus the edge cases that have no acceptance-test
home.
"""

from __future__ import annotations

import datetime

import pytest

import octlib


def test_selftest_passes():
    assert octlib._selftest() == 0


@pytest.mark.parametrize("raw,want", [
    ("Mobile", "wireless"), ("Wireless", "wireless"), ("mobile", "wireless"),
    ("MOB", "wireless"), ("Landline", "landline"), ("LandLine", "landline"),
    ("Voip", "voip"), ("VoIP", "voip"), ("", ""), (None, ""), ("other", "other"),
])
def test_normalize_line_type(raw, want):
    """Three vendors, three spellings of one fact. Tracerfy's 'Mobile' is the one that
    silently breaks a build that only maps 'wire*'."""
    assert octlib.normalize_line_type(raw) == want


@pytest.mark.parametrize("owner,cls", [
    ("REAL ESTATE INVESTMENTS INC", "entity"),
    ("SMITH FAMILY TRUST", "trust"),
    ("MILAM STEPHEN WESLEY CO TR", "trust"),
    ("CITY NATIONAL BANK OF FLORIDA TRUSTEE", "trust_company"),
    ("TENNESSEE STATE OF", "gov"),
    ("FUGATE RONALD ALLEN", "individual"),
    ("ESTATE OF JOHN DOE", "trust"),
    ("68V CREEKCHASE FL 2022 LLC", "entity"),
])
def test_classify_order_is_load_bearing(owner, cls):
    assert octlib.classify(owner)["owner_class"] == cls


def test_strip_suffix_removes_et_al_and_trailing_plus():
    assert "ET AL" not in octlib.strip_suffix("SMITH JOHN ET AL")
    assert not octlib.strip_suffix("SMITH PROPERTIES LLC +").endswith("+")
    assert octlib.strip_suffix("THE EXAMPLE COMPANY THE").strip() == "EXAMPLE"


def test_naddr_deletes_directionals_but_addr_key_does_not():
    """naddr is a CLUSTERING key and can afford to be lossy. addr_key is the ANCHOR, and
    collapsing 100 N MAIN into 100 S MAIN would accept the wrong household."""
    assert octlib.naddr("100 N MAIN ST") == octlib.naddr("100 S MAIN ST")
    assert octlib.addr_key("100 N MAIN ST", "X", "TN", "37931") != \
        octlib.addr_key("100 S MAIN ST", "X", "TN", "37931")


def test_addr_key_truncates_at_unit_markers():
    assert octlib.addr_key("150 SE 2ND AVE STE 300", "MIAMI", "FL", "33131") == \
        octlib.addr_key("150 SE 2ND AVE", "MIAMI", "FL", "33131")


def test_split_apns_never_truncates():
    cell = "; ".join("APN{:03d}".format(i) for i in range(40))
    assert len(octlib.split_apns(cell)) == 40, "the source builder capped this at 12"


def test_phone_ordering_recency_outranks_type():
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.timezone.utc)
    stale_wireless = {"type": "Mobile", "dnc": False, "last_seen": "Jan 2016"}
    fresh_landline = {"type": "Landline", "dnc": False, "last_seen": "Jul 2026"}
    assert octlib.phone_sort_key(fresh_landline, now) < \
        octlib.phone_sort_key(stale_wireless, now), \
        "a wireless number last seen 2016 is worse than a landline seen this year"


def test_phone_ordering_now_is_computed_not_hardcoded():
    a = octlib.phone_sort_key({"type": "Mobile", "last_seen": "Jul 2026"},
                              datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc))
    b = octlib.phone_sort_key({"type": "Mobile", "last_seen": "Jul 2026"},
                              datetime.datetime(2036, 8, 1, tzinfo=datetime.timezone.utc))
    assert a[0] == 0 and b[0] == 2, "the same number ages as 'now' advances"


def test_provenance_has_all_five_keys():
    p = octlib.provenance("county layer")
    assert set(p) == {"source", "retrieved_at", "anchor_basis", "identity_tier",
                      "confidence_basis"}
    assert p["anchor_basis"] == octlib.UNKNOWN, "unset provenance is UNKNOWN, never blank"


def test_cache_root_is_never_an_absolute_literal(monkeypatch, tmp_path):
    monkeypatch.setenv("OWNER_TRACE_CACHE", str(tmp_path / "custom"))
    assert octlib.cache_root() == tmp_path / "custom"


def test_run_dir_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OWNER_TRACE_CACHE", str(tmp_path))
    d = octlib.run_dir("TN", "Knox", datetime.datetime(2026, 8, 11, 14, 3))
    assert d.name == "tn_knox_20260811-1403"
    assert d.parent.name == "runs"


def test_control_titles_dropped_the_stride_bug_artifacts():
    for artifact in ("GRM", "GR", "RM"):
        assert artifact not in octlib.CONTROL_TITLES
    for added in ("D", "PD"):
        assert added in octlib.CONTROL_TITLES


def test_noncontrol_edges_never_establish_control():
    for edge in octlib.NONCONTROL_EDGES:
        ok, why = octlib.role_ok({"edges": [{"edge_type": edge}],
                                  "edge_source_is_government_record": True})
        assert ok is False, "{} must not establish control".format(edge)
        assert "non-control" in why


def test_outreach_eligible_treats_a_stale_scrub_as_unscrubbed():
    ev = {"source_a_names_the_exact_person_and_lists_the_phone": True,
          "source_a_has_another_strong_identifier": True, "source_b_present": True,
          "source_b_upstream_lineage": "distinct", "source_b_is_UPSTREAM_INDEPENDENT": True,
          "source_b_reverse_matches_exact_full_name_or_strong_address": True,
          "line_type_source": "tracerfy.phones[].type", "source_line_type": "Mobile",
          "dnc_checked_at": "2026-01-01T00:00:00Z", "dnc_checked_age_days": 90,
          "national_dnc": False, "applicable_state_dnc": False, "internal_dnc": False,
          "state_outreach_policy_allows_channel": True}
    ok, why = octlib.outreach_eligible(ev)
    assert ok is False and "stale" in why
    ev["dnc_checked_age_days"] = 5
    assert octlib.outreach_eligible(ev)[0] is True


def test_dnc_false_is_not_consent_when_the_check_never_ran():
    ev = {"source_a_names_the_exact_person_and_lists_the_phone": True,
          "source_a_has_another_strong_identifier": True, "source_b_present": True,
          "source_b_upstream_lineage": "distinct", "source_b_is_UPSTREAM_INDEPENDENT": True,
          "source_b_reverse_matches_exact_full_name_or_strong_address": True,
          "line_type_source": "tracerfy.phones[].type", "source_line_type": "Mobile",
          "dnc_checked_at": None}
    ok, why = octlib.outreach_eligible(ev)
    assert ok is False and octlib.NOT_SCRUBBED_STAMP in why
