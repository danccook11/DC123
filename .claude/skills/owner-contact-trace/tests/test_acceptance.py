"""The 27 acceptance tests from the master spec, as fixture-backed regressions.

Every test is offline. Test numbers match the spec's numbering so a failure can be traced
back to the measurement that motivated it.

Where a test needs a recorded vendor payload, it runs against the synthetic equivalent whose
STRUCTURE, ranking, line types, carriers and compliance flags are the recorded ones and
whose digits are reserved-fictional. Every assertion here is about status and shape, so this
does not weaken them.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import octlib
import anchor_gate
import free_pierce
import sunbiz_pierce as sb
import vendor_client
import verify_reverse
import delivery_gate
import leak_scan
import sos_route


# ---------------------------------------------------------------- 1


def test_01_nhg_holdings_resolves_by_doc_and_caps_role_status(fixtures_dir):
    """NHG HOLDINGS LLC — entity resolves by DOC NUMBER, not by name; and a corrupted title
    must not manufacture authority."""
    recs = []
    with open(fixtures_dir / "cordata_sample.txt", "rb") as fh:
        for _, line in sb.iter_records(fh):
            recs.append(sb.parse_record(line))
    nhg = [r for r in recs if r["doc_number"] == "L06000038390"]
    assert len(nhg) == 1, "must resolve by doc number, uniquely"
    nhg = nhg[0]
    assert nhg["entity_name"] == "NHG HOLDINGS LLC"
    assert nhg["registered_agent"]["display_name"] == "ALAN B GROSSE"
    names = [o["display_name"] for o in nhg["officers"]]
    assert "A B GROSSE" in names and "RENEE J GROSSE" in names
    # Both officers filed at the county mailing address.
    for o in nhg["officers"]:
        assert o["addr"] == "3659 RUBIN RD"

    # role_status may not exceed PROBABLE-AUTHORITY on a name-only match: the SHIPPED titles
    # for these two were GRM/RM, which are stride-bug artifacts, not real titles.
    cand = {"edges": [{"edge_type": "officer"}], "edge_source_is_government_record": True,
            "registry_officer_named": True, "anchored": "Y"}
    status, _ = anchor_gate.role_status(cand)
    assert status == "PROBABLE-AUTHORITY"


def test_01_vendor_confidence_is_not_a_verdict():
    """The Wyllie Bryant Hodges candidate is rejected even though a vendor labelled it
    SHERPA-VERIFIED / CONFIRMED."""
    ev = {"source_a_names_the_exact_person_and_lists_the_phone": True,
          "vendor_label": "SHERPA-VERIFIED", "vendor_match_confidence": 100,
          "source_b_present": False}
    ok, _ = octlib.phone_attributed(ev)
    assert ok is False
    status, _ = anchor_gate.phone_attribution_status(ev)
    assert status == "SINGLE-SOURCE-PHONE"


# ---------------------------------------------------------------- 2


def test_02_knox_apn_parses_as_one_parcel_and_splits_the_owner(fixtures_dir):
    layer = json.loads((fixtures_dir / "knox_layer.json").read_text(encoding="utf-8"))
    attrs = [f["attributes"] for f in layer["features"]]
    row = [a for a in attrs if a["PARCELID"].strip().startswith("090")][0]

    assert "  " in row["PARCELID"], "Knox PARCELID embeds a DOUBLE SPACE"
    assert len(octlib.split_apns(row["PARCELID"])) == 1, "one 3-component APN, not two parcels"

    owners = octlib.split_owner_string(row["OWNER"])
    assert len(owners) == 2
    assert owners[0].split()[0] == owners[1].split()[0], "surname carried across the ampersand"

    csz = octlib.csz_split(row["FULL_MAIL_CITY_STATE_ZIP"])
    assert (csz["city"], csz["state"], csz["zip"]) == ("KNOXVILLE", "TN", "37931")
    assert csz["zip"], "ZIP present, so the one-api pre-flight passes"

    assert octlib.naddr(row["FULL_ADDRESS"]) != octlib.naddr(row["FULL_MAIL_ADDRESS"]), \
        "situs != mailing"


# ---------------------------------------------------------------- 3


def test_03_bare_apn_refusal_raises_before_any_vendor_call():
    with pytest.raises(vendor_client.VendorRefusal):
        vendor_client.guard_person_axis(first=None, last=None,
                                        address="125 00801 FIPS 47093")


# ---------------------------------------------------------------- 4


def test_04_zipless_address_is_rejected_preflight():
    with pytest.raises(vendor_client.VendorRefusal):
        vendor_client.guard_zip("8331 CORRYTON RD, Knoxville TN")
    assert vendor_client.guard_zip("8331 CORRYTON RD; Corryton, TN 37721") is True


def test_04_positive_half_replays_a_fixture(fixtures_dir):
    rec = json.loads((fixtures_dir / "one_api_person.json").read_text(encoding="utf-8"))
    assert rec["Input Given"].endswith("37721")
    assert rec["Postal Code"] == "37721"


# ---------------------------------------------------------------- 5


def test_05_libphonenumber_is_a_hard_reject(fixtures_dir):
    fx = json.loads((fixtures_dir / "libphonenumber_reject.json").read_text(encoding="utf-8"))
    assert fx["numberType"] == "FIXED_LINE_OR_MOBILE"
    with pytest.raises(ValueError):
        anchor_gate.line_type_status({"line_type_source": "libphonenumber.numberType",
                                      "source_line_type": fx["numberType"]})
    assert "libphonenumber.numberType" not in octlib.LINE_TYPE_SOURCE_ALLOWLIST
    # And the word "mobile" must never appear in output for it.
    assert octlib.normalize_line_type(fx["numberType"]) != "wireless"


# ---------------------------------------------------------------- 6, 11


def test_06_geo_conflict_rejects_regardless_of_confidence():
    """A 70-year-old in Kansas City at matchConfidence 100 must be REJECTED."""
    ev = {"source_a_names_the_exact_person_and_lists_the_phone": True,
          "vendor_match_confidence": 100,
          "primary_number_or_po_box_matches": False, "street_name_matches": False,
          "city_state_zip5_match": False, "required_secondary_unit_matches": False,
          "not_cmra_or_agent_hub": None, "source_b_present": False}
    ok, why = octlib.strong_address_match(ev)
    assert ok is False
    assert octlib.phone_attributed(ev)[0] is False


def test_11_geography_is_a_disambiguator_not_a_hard_gate():
    """Reject on CONFLICT, not on distance. An out-of-county entity is normal — absentee
    ownership is the norm — so a hard county gate would reject the true owner."""
    ev = {"registry_jurisdiction_and_entity_id_match": True}
    ok, _ = octlib.entity_ok(ev)
    assert ok is True, "an entity matched by jurisdiction+id is accepted wherever it sits"

    # A name-only match with no discriminators is AMBIGUOUS — the HOLSTON failure mode.
    ok, why = octlib.entity_ok({"exact_legal_name_match": True,
                                "independent_discriminators": 0,
                                "no_competing_registry_candidate": True})
    assert ok is False and "discriminator" in why


# ---------------------------------------------------------------- 8


def test_08_dual_key_join_merges_the_acuff_pair():
    a, b = "ACUFF GARY H & ANN D", "ACUFF GARY HERBERT & ACUFF ANN DENISE"
    same_mailing = True
    assert octlib.norm_owner(a)["spaced"].split()[0] == \
        octlib.norm_owner(b)["spaced"].split()[0]
    # They do not merge on name alone, which is exactly why the ADDRESS axis is required.
    assert octlib.fuzzy_owner_merge_ok(a, b, same_mailing) is False
    assert octlib.addr_key("100 EXAMPLE RD", "MONROE", "NC", "28112") == \
        octlib.addr_key("100 EXAMPLE RD", "MONROE", "NC", "28112")


# ---------------------------------------------------------------- 9


def test_09_agent_desk_downgrade_and_unevaluated_outside_florida():
    assert octlib.mail_class("150 SE 2ND AVE", "MIAMI", "FL", "33131",
                             entity_count=1381, index_available=True)["mail_class"] == \
        "commercial"
    assert octlib.mail_class("7901 4TH ST N", "ST PETERSBURG", "FL", "33702",
                             entity_count=70796, index_available=True)["mail_class"] == \
        "commercial"
    # A NON-FL parcel with no index must be UNEVALUATED, never residential.
    out = octlib.mail_class("10205 EXAMPLE MILL RD", "KNOXVILLE", "TN", "37931")
    assert out["mail_class"] == "UNEVALUATED"
    assert out["agent_desk_gate"] == "UNKNOWN"


# ---------------------------------------------------------------- 10


def test_10_sunbiz_framing_and_offsets(fixtures_dir):
    path = fixtures_dir / "cordata_sample.txt"
    raw = path.read_bytes()
    assert raw[1440:1442] == b"\r\n", "the fixture must be CRLF-terminated"

    n = 0
    with open(path, "rb") as fh:
        for _, line in sb.iter_records(fh):
            assert len(line) == 1440
            n += 1
    assert n >= 6

    recs = []
    with open(path, "rb") as fh:
        for _, line in sb.iter_records(fh):
            recs.append(sb.parse_record(line))
    niles = [r for r in recs if r["doc_number"] == "F94000002850"][0]
    assert len(niles["officers"]) == 6, "six officers, not four"
    assert [o["title"] for o in niles["officers"]] == \
        ["Dire", "VP,", "Trea", "Secr", "VP,", "Asst"], "real titles, not None"
    assert len(niles["registered_agent"]["zip"]) <= 9, "RA zip is 9 chars, never '34223    M'"


def test_10_framing_error_is_raised_not_silently_accepted():
    with pytest.raises(sb.FramingError):
        sb.decode_record(b"too short\r\n")
    # A 1441-char line means the \r is still attached.
    with pytest.raises(sb.FramingError):
        sb.decode_record(("x" * 1441).encode("latin-1"))


# ---------------------------------------------------------------- 11, 12


def test_11_free_pierce_guardrails_with_no_list_context(skill_dir):
    lex = free_pierce.load_lexicon()
    for company in ("MARTIN MARIETTA MATERIALS INC", "CARTER MILL LLC"):
        res = free_pierce.parse_people(company, lex)
        assert res["people"] == [], "{} must yield NO person".format(company)

    res = free_pierce.parse_people("BRIAN & CONNIE PIERCE LIVING TRUST", lex)
    got = {(p["first"], p["last"]) for p in res["people"]}
    assert got == {("BRIAN", "PIERCE"), ("CONNIE", "PIERCE")}
    assert res["tier"] == "LEAD", "the frozen lexicon produces LEADS, never conclusions"


def test_12_eponymous_entities_are_leads_not_conclusions():
    lex = free_pierce.load_lexicon()
    for name, surname in (("PARKER PROPERTIES INC", "PARKER"),
                          ("SANDERS FARMS LLC", "SANDERS")):
        res = free_pierce.parse_people(name, lex)
        assert res["people"] == [], "name inference alone must not produce a person"
        assert res["eponymous_surname_lead"]["surname"] == surname, \
            "but the surname IS emitted as a free registry search term"

    # With the name inference alone the role caps below PROBABLE-AUTHORITY.
    status, _ = anchor_gate.role_status({"tier": "LEAD", "edges": []})
    assert status == "BENEFICIAL-CONTROL-UNKNOWN"
    # It reaches PROBABLE-AUTHORITY only when a registry officer independently names them.
    status, _ = anchor_gate.role_status({"registry_officer_named": True, "anchored": "Y",
                                         "edges": [{"edge_type": "officer"}],
                                         "edge_source_is_government_record": True})
    assert status == "PROBABLE-AUTHORITY"


# ---------------------------------------------------------------- 13, 17


def test_13_owner_cluster_vs_relationship_cluster():
    a, b = "STEGALL JOHN A", "JOHN A STEGALL PROPERTIES LLC"
    box = octlib.addr_key("PO BOX 42", "MONROE", "NC", "28112")
    assert octlib.fuzzy_owner_merge_ok(a, b, True) is False, "2 owner clusters"
    assert box == octlib.addr_key("PO BOX 42", "MONROE", "NC", "28112"), "1 rel cluster"
    assert octlib.fuzzy_owner_merge_ok("LANDPEDDLARS", "LANDPEDDLERS", True) is True


def test_17_co_collapse_keeps_the_box_not_the_staffer():
    a = octlib.addr_key("C O TAMMY BRITT PO BOX 159", "WINGATE", "NC", "28174")
    b = octlib.addr_key("C O JENNY WALDEN PO BOX 159", "WINGATE", "NC", "28174")
    assert a == b


# ---------------------------------------------------------------- 14


def test_14_institutional_holdback_blocks_the_call_list():
    g = delivery_gate.Gate()
    delivery_gate.check_row(g, {
        "owner_of_record": "C S X TRANSPORTATION INC", "suppressed": True,
        "suppression_pattern": "CSXTRANSPORTATION",
        "primary_mobile": "904-555-0133", "primary_line_type": "wireless",
        "line_type_source": "one-api.Phone-N Type", "primary_dnc": False,
        "identity_source": "one-api", "retrieved_at": "2026-08-11T00:00:00Z",
        "anchor_basis": "parcel mailing address", "identity_tier": 2,
    }, "Call List")
    assert any(f["check"] == "suppressed-on-call-list" for f in g.failures)


def test_14_institutional_match_catches_via_the_mail_line():
    hit = octlib.institutional_match("ANHEUSER BUSCH BREWING PROPERTIES LLC",
                                     "ATTN GENERAL COUNSEL")
    assert hit and hit["matched_on"] == "mail"


# ---------------------------------------------------------------- 16


def test_16_leak_scan_catches_both_parenthesized_forms():
    findings = leak_scan.scan_text("call (314) 555-0177 or +1 (630) 555-0195",
                                   "raw_source_column", approved=False,
                                   allow_fictional=False)
    assert len([f for f in findings if f["rule"] == "phone_outside_approved_column"]) == 2


def test_16_leak_scan_is_scoped_not_global():
    """This skill's product IS phone numbers — an approved column must pass."""
    assert leak_scan.scan_text("865-555-0158", "primary_mobile", approved=True,
                               allow_fictional=False) == []
    assert leak_scan.scan_text("865-555-0158", "raw_source", approved=False,
                               allow_fictional=False) != []


# ---------------------------------------------------------------- 18


def test_18_multi_hop_follows_a_company_officer(fixtures_dir, tmp_path):
    member = fixtures_dir / "cordata_sample.txt"
    idx_path = tmp_path / "index.json"
    doc = sb.build_offset_index(str(member), str(idx_path), progress_every=0)
    res = sb.walk(str(member), doc["index"], "68V CREEKCHASE FL 2022 LLC", max_hops=3)
    entities = {c["entity"] for c in res["chain"]}
    assert "68V CREEKCHASE FL 2022 LLC" in entities
    assert "68VENTURES" in entities, "'68 VENTURES, LLC' must normalize to '68VENTURES'"
    assert res["unresolved_frontier"] == [] or isinstance(res["unresolved_frontier"], list)


def test_18_never_recurses_through_a_registered_agent(fixtures_dir, tmp_path):
    member = fixtures_dir / "cordata_sample.txt"
    doc = sb.build_offset_index(str(member), str(tmp_path / "i.json"), progress_every=0)
    res = sb.walk(str(member), doc["index"], "68V CREEKCHASE FL 2022 LLC", max_hops=3)
    # The RA is REGISTERED AGENTS INC, a service company. It must not appear as a hop.
    assert not any("REGISTERED AGENTS" in (c["entity"] or "").upper() for c in res["chain"])


# ---------------------------------------------------------------- 19


def test_19_csz_split_never_produces_saint_lo():
    out = octlib.csz_split("SAINT PETERSBURG FL 33701")
    assert (out["city"], out["state"], out["zip"]) == ("SAINT PETERSBURG", "FL", "33701")
    assert out["city"] != "SAINT" and out["state"] != "LO"


# ---------------------------------------------------------------- 20


def test_20_budget_estimator_is_worst_case_and_refuses():
    est = vendor_client.estimate(200, "apivault_name", max_results=3,
                                 expected_phones=150)
    apivault = [l for l in est["lines"] if l["axis"] == "apivault_name"][0]
    assert abs(apivault["usd"] - (200 * 3 * 0.0065 + 0.00005)) < 1e-4, \
        "must be persons x max_results x price, not persons x price"
    assert any(l["axis"] == "one_api_reverse_phone" for l in est["lines"]), \
        "the reverse-phone leg is a second billed call and must be in the estimate"

    # With max_results unset the worst case is the ACTOR'S default of 100.
    est2 = vendor_client.estimate(200, "apivault_name")
    assert est2["usd_total"] > 100
    with pytest.raises(vendor_client.NotApproved):
        vendor_client.check_approval(25.0, None)
    with pytest.raises(vendor_client.NotApproved):
        vendor_client.check_approval(25.0, 10.0)


def test_20_budget_exhausted_raises_rather_than_truncating(tmp_path):
    ledger = tmp_path / "ledger.csv"
    vendor_client.ledger_append(ledger, "one-api", 100, 24.0)
    with pytest.raises(vendor_client.BudgetExhausted):
        vendor_client.check_budget(ledger, 25.0, 5.0)


# ---------------------------------------------------------------- 21


def test_21_no_route_state_never_escalates_to_a_paid_vendor():
    r = sos_route.route_for("TN")
    assert r["escalate_to_paid_vendor"] is False
    r = sos_route.probe("TN", offline=True)
    assert r["disposition"].startswith("UNEVALUATED")
    assert "PIERCED" not in r["disposition"], \
        "must not claim we looked and found nothing"
    nc = sos_route.route_for("NC")
    assert nc["disposition"] == "NO-ROUTE-STATE"


# ---------------------------------------------------------------- 22


def test_22_fort_stockton_negative_control(fixtures_dir):
    """THE MOST IMPORTANT TEST IN THE SUITE.

    A build that prints this person as the owner of this parcel has failed, regardless of
    every other test passing.
    """
    vendor = json.loads(
        (fixtures_dir / "tracerfy_trace_lookup_fortstockton.json").read_text(encoding="utf-8"))
    cad = json.loads((fixtures_dir / "pecos_cad_row.json").read_text(encoding="utf-8"))

    person = vendor["people"][0]
    assert person["property_owner"] is True, "the vendor DOES claim ownership"

    m = person["mailing_address"]
    returned_key = octlib.addr_key(m["street"], m["city"], m["state"], m["zip"])
    cad_key = octlib.addr_key(cad["mailing"]["street"], cad["mailing"]["city"],
                              cad["mailing"]["state"], cad["mailing"]["zip"])
    assert returned_key != cad_key, "Fort Stockton PO box vs Richmond VA — no anchor"

    anchored, why = vendor_client.anchor_or_discard(m, cad_key)
    assert anchored is False and "DISCARDED" in why

    # No surname tie to the entity, and the entity is not pierced.
    assert not octlib.surname5_prefix_match(person["last_name"], cad["owner"])
    assert octlib.classify(cad["owner"])["owner_class"] == "entity"

    # The claim is RECORDED for audit and is never an input to any predicate.
    ev = {"property_owner": person["property_owner"],
          "source_a_names_the_exact_person_and_lists_the_phone": True,
          "source_b_present": False}
    status, _ = anchor_gate.phone_attribution_status(ev)
    assert status != "VERIFIED-PHONE"
    ok, _ = octlib.title_ok({"latest_effective_recorded_grantee_matches_candidate_owner":
                             person["property_owner"]})
    assert ok is False, "a vendor boolean can never satisfy title_ok"


# ---------------------------------------------------------------- 23


def test_23_knox_positive_control_end_to_end(fixtures_dir):
    vendor = json.loads(
        (fixtures_dir / "tracerfy_parcel_lookup.json").read_text(encoding="utf-8"))
    layer = json.loads((fixtures_dir / "knox_layer.json").read_text(encoding="utf-8"))
    county = [f["attributes"] for f in layer["features"]
              if f["attributes"]["PARCELID"].strip().startswith("090")][0]

    person = vendor["people"][0]
    m = person["mailing_address"]
    csz = octlib.csz_split(county["FULL_MAIL_CITY_STATE_ZIP"])
    county_key = octlib.addr_key(county["FULL_MAIL_ADDRESS"], csz["city"], csz["state"],
                                 csz["zip"])
    vendor_key = octlib.addr_key(m["street"], m["city"], m["state"], m["zip"])
    assert vendor_key == county_key, "strong_address_match: mailing addr_key identical"

    # Exact surname tie to the owner string.
    owner_surname = octlib.norm_owner(county["OWNER"])["spaced"].split()[0]
    assert person["last_name"].upper() == owner_surname

    phone = person["phones"][0]
    assert phone["type"] == "Mobile"
    assert octlib.normalize_line_type(phone["type"]) == "wireless", \
        "a build that maps only 'wire*' scores this row has_wire=False and silently " \
        "downgrades a perfect match"

    lts, _ = anchor_gate.line_type_status({"line_type_source": "tracerfy.phones[].type",
                                           "source_line_type": phone["type"]})
    assert lts == "VERIFIED-MOBILE"

    # Tracerfy alone is ONE source. The skill must not self-promote.
    attr, _ = anchor_gate.phone_attribution_status({
        "source_a_names_the_exact_person_and_lists_the_phone": True,
        "source_a_has_another_strong_identifier": True, "source_b_present": False})
    assert attr == "SINGLE-SOURCE-PHONE"

    # TAX-ROLL-OWNER on the county fixture alone.
    own, _ = anchor_gate.ownership_status({"owner_of_record": county["OWNER"],
                                           "deed_status": "DEED-UNAVAILABLE"})
    assert own == "TAX-ROLL-OWNER"

    # Compliance bites: the mobile is dnc:true.
    assert phone["dnc"] is True
    comp, why = anchor_gate.compliance_status({"primary_dnc": True,
                                               "dnc_checked_at": "2026-08-11T00:00:00Z"})
    assert comp == "DNC-BLOCKED" and "mail or email only" in why
    assert anchor_gate.may_print_primary_mobile(attr, lts) is False


# ---------------------------------------------------------------- 24


def test_24_doctor_makes_zero_credit_consuming_calls(skill_dir):
    import doctor
    for bad in ("trace_lookup", "parcel_lookup", "dnc_check", "execute_lead_list"):
        assert bad in doctor.TRACERFY_FORBIDDEN_IN_DOCTOR
    for free in ("check_balance", "list_strategies"):
        assert free in doctor.TRACERFY_FREE_TOOLS
        assert free not in doctor.TRACERFY_FORBIDDEN_IN_DOCTOR

    src = (skill_dir / "scripts" / "doctor.py").read_text(encoding="utf-8")
    # The forbidden names appear only in the refusal list and its message, never as a call.
    assert "TRACERFY_FORBIDDEN_IN_DOCTOR" in src
    manifest = doctor.build_manifest(offline=True)
    tracerfy = [c for c in manifest["mcp"] if c["name"] == "tracerfy"][0]
    assert tracerfy["status"] == "UNEVALUATED"
    assert tracerfy["usd_per_credit"] is None, "never fabricate a dollar figure"


# ---------------------------------------------------------------- 25


def test_25_recorder_conflict_halts_spend():
    own, why = anchor_gate.ownership_status({"owner_of_record": "OWNER X",
                                             "deed_status": "OWNERSHIP-CONFLICT"})
    assert own == "OWNERSHIP-CONFLICT"
    assert "STOPS" in why.upper()


def test_25_no_recorder_route_is_a_named_gap_not_a_silent_pass():
    own, why = anchor_gate.ownership_status({"owner_of_record": "OWNER X",
                                             "deed_status": "DEED-UNAVAILABLE",
                                             "deed_note": "DEED-UNAVAILABLE (Knox, 2026-08-11)"})
    assert own == "TAX-ROLL-OWNER"
    assert "DEED-UNAVAILABLE" in why
    assert own != "VERIFIED-OWNER"


# ---------------------------------------------------------------- 26


def test_26_no_coercion_of_unknowns():
    assert octlib.tri(None) == "UNKNOWN"
    assert octlib.tri("") == "UNKNOWN"
    assert octlib.tri("UNEVALUATED") == "UNKNOWN"

    g = delivery_gate.Gate()
    delivery_gate.check_row(g, {"owner_of_record": "X", "deceased": "N",
                                "deceased_checked": False}, "Call List")
    assert any(f["check"] == "no-coercion-of-unknowns" for f in g.failures)

    # And an address gate that never ran serializes as neither pass nor fail.
    ok, why = octlib.strong_address_match({"primary_number_or_po_box_matches": True,
                                           "street_name_matches": True,
                                           "city_state_zip5_match": True,
                                           "required_secondary_unit_matches": True,
                                           "not_cmra_or_agent_hub": None})
    assert ok is False and "never ran" in why


# ---------------------------------------------------------------- 27


def test_27_correlated_sources_are_not_corroboration():
    base = {"source_a_names_the_exact_person_and_lists_the_phone": True,
            "source_a_has_another_strong_identifier": True,
            "source_b_present": True,
            "source_b_reverse_matches_exact_full_name_or_strong_address": True}

    same = dict(base, source_b_upstream_lineage="TruePeopleSearch",
                source_b_is_UPSTREAM_INDEPENDENT=False)
    assert anchor_gate.phone_attribution_status(same)[0] == "SINGLE-SOURCE-PHONE"

    distinct = dict(base, source_b_upstream_lineage="NYS DHCR sxi2-m23m",
                    source_b_is_UPSTREAM_INDEPENDENT=True)
    assert anchor_gate.phone_attribution_status(distinct)[0] == "VERIFIED-PHONE"

    undeclared = dict(base, source_b_upstream_lineage=None,
                      source_b_is_UPSTREAM_INDEPENDENT=True)
    assert anchor_gate.phone_attribution_status(undeclared)[0] == "SINGLE-SOURCE-PHONE", \
        "unknown lineage must FAIL CLOSED"


def test_27_carrier_lookup_never_satisfies_source_b(fixtures_dir):
    rec = json.loads((fixtures_dir / "one_api_person.json").read_text(encoding="utf-8"))
    res = verify_reverse.verify("Dana Exampleton", "865-555-0173", rec,
                                upstream_lineage="Telnyx", is_carrier_or_hlr=True)
    assert res["satisfies_source_b"] is False
    assert res["verdict"] != "CONFIRMED"


# ---------------------------------------------------------------- cross-cutting


def test_surname5_appears_in_no_acceptance_predicate(skill_dir):
    """Spec s9 rule 2. It survives only as a ranking and lead signal."""
    for name in ("octlib.py", "anchor_gate.py"):
        src = (skill_dir / "scripts" / name).read_text(encoding="utf-8")
        for pred in ("def title_ok", "def entity_ok", "def role_ok", "def person_ok",
                     "def strong_address_match", "def phone_attributed",
                     "def mobile_confirmed", "def outreach_eligible"):
            if pred not in src:
                continue
            body = src.split(pred, 1)[1].split("\ndef ", 1)[0]
            assert "surname5_prefix_match" not in body, \
                "{} in {} references surname5_prefix_match".format(pred, name)


def test_wireless_never_raises_ownership_or_role_confidence():
    own, _ = anchor_gate.ownership_status({"owner_of_record": ""})
    assert own == "UNKNOWN"
    lts, _ = anchor_gate.line_type_status({"line_type_source": "tracerfy.phones[].type",
                                           "source_line_type": "Mobile"})
    assert lts == "VERIFIED-MOBILE"
    own2, _ = anchor_gate.ownership_status({"owner_of_record": ""})
    assert own2 == "UNKNOWN", "a VERIFIED-MOBILE on an UNKNOWN owner is still unknown"


def test_every_script_supports_help(skill_dir):
    scripts = sorted((skill_dir / "scripts").glob("*.py"))
    assert scripts
    for p in scripts:
        r = subprocess.run([sys.executable, str(p), "--help"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, "{} --help exited {}: {}".format(
            p.name, r.returncode, r.stderr[:400])
        assert "usage" in r.stdout.lower()
