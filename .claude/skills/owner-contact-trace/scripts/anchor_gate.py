#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anchor_gate.py — stage 9: the four gates, the five status fields, the ambiguity gate.

CONFIDENCE IS MULTIDIMENSIONAL. The single-band model conflated four unrelated questions --
who holds title / which human has documented authority / does this phone belong to that
human / is it a usable mobile -- and its LIKELY rung accepted a surname match with no
address and no geography check, which with 5-character prefix matching confidently accepts
the wrong Smith.

So this emits FIVE independent status fields and never one band:

    ownership_status · role_status · phone_attribution_status · line_type_status
    · compliance_status

Four rules that fall out of that and are enforced here and re-checked in delivery_gate.py:

  1. Wireless status NEVER increases ownership or role confidence. A VERIFIED-MOBILE on an
     UNKNOWN owner is still an unknown owner.
  2. surname5_prefix_match appears in NO acceptance predicate. It survives as a ranking and
     lead signal only.
  3. Corroboration must be UPSTREAM-independent. Two actors reselling one aggregator are one
     source; unknown lineage fails closed.
  4. HOUSEHOLD-PHONE and SINGLE-SOURCE-PHONE may never print as PRIMARY MOBILE. They are
     still useful -- deliver them, labelled as what they are.

AMBIGUITY GATE: ambiguous means the top two ranked humans are within 20 points, or both
anchored, or both carry a control title. Emit BOTH as rank 1 and rank 2, set
`ambiguity: true`, and NEVER pick.

Usage:
    anchor_gate.py --in HUMANS.json --contacts contacts.jsonl --out-dir RUN_DIR
    anchor_gate.py --demo-fixture <fixtures>/tracerfy_parcel_lookup.json --parcel-addr-key ...
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

AMBIGUITY_POINTS = 20


# ---------------------------------------------------------------- ownership / role


def ownership_status(row):
    """Deed evidence decides. The assessor roll alone is TAX-ROLL-OWNER, never VERIFIED."""
    if row.get("deed_status") == "OWNERSHIP-CONFLICT":
        return "OWNERSHIP-CONFLICT", ("recorder and assessor disagree — ALL PAID IDENTITY "
                                      "WORK STOPS. Contacting a prior owner is the most "
                                      "expensive error available (doctrine 17).")
    ok, why = octlib.title_ok(row.get("title_evidence") or {})
    if ok:
        return "VERIFIED-OWNER", why
    if row.get("entity_resolved") and not row.get("controller_resolved"):
        return "RECORD-OWNER-RESOLVED", (
            "the title-holding entity is established but its current controller is not "
            "publicly establishable — entity-interest transfer, nominee arrangement, land "
            "trust or series LLC. This is a COMPLETED row, not a failed one.")
    if (row.get("owner_of_record") or "").strip():
        return "TAX-ROLL-OWNER", (
            "assessor roll only. {} The roll is a BILLING record: it lags conveyances, keeps "
            "dissolved grantees, and omits vesting language.".format(
                row.get("deed_note") or why))
    return "UNKNOWN", "no owner of record"


def role_status(candidate):
    ok, why = octlib.role_ok(candidate.get("role_evidence") or
                             {"edges": candidate.get("edges") or [],
                              "edge_source_is_government_record":
                                  candidate.get("edge_source_is_government_record")})
    if ok:
        return "VERIFIED-AUTHORITY", why

    edges = {e.get("edge_type") for e in (candidate.get("edges") or []) if isinstance(e, dict)}
    if candidate.get("registry_officer_named") and candidate.get("anchored") == "Y":
        return "PROBABLE-AUTHORITY", (
            "a registry officer record independently names this person and their filed "
            "address anchors — but no control-bearing edge is documented: {}".format(why))
    if edges & octlib.NONCONTROL_EDGES:
        return "AUTHORIZED-CONTACT", (
            "reachable and recorded, but the only edges are {} — these never establish "
            "control".format(sorted(edges & octlib.NONCONTROL_EDGES)))
    if candidate.get("tier") == "LEAD":
        return "BENEFICIAL-CONTROL-UNKNOWN", (
            "name-inference lead only. A surname in a company name, or a name inside a trust "
            "name, is not evidence of control.")
    return "UNKNOWN", why


# ---------------------------------------------------------------- phone / line / compliance


def phone_attribution_status(ev):
    ok, why = octlib.phone_attributed(ev)
    if ok:
        return "VERIFIED-PHONE", why
    if ev.get("any_current_source_contradicts_the_subscriber") is True:
        return "CONTRADICTED", why
    if ev.get("household_only") is True:
        return "HOUSEHOLD-PHONE", (
            "the number belongs to the household at the anchored address, not demonstrably "
            "to this person. Useful, and delivered — but not a primary mobile.")
    if ev.get("source_a_names_the_exact_person_and_lists_the_phone") is True:
        return "SINGLE-SOURCE-PHONE", (
            "one upstream source. {} Operationally useful; deliver it labelled as what it "
            "is.".format(why))
    return "UNKNOWN", why


def line_type_status(ev):
    src = ev.get("line_type_source")
    raw = ev.get("source_line_type")
    norm = octlib.normalize_line_type(raw)

    if src and src not in octlib.LINE_TYPE_SOURCE_ALLOWLIST:
        raise ValueError(
            "line_type_source {!r} is not in the allowlist. US number portability makes any "
            "libphonenumber-derived value (numberType, FIXED_LINE_OR_MOBILE) structurally "
            "incapable of answering this — it is a hard reject, not a downgrade "
            "(doctrine 7).".format(src))
    if not raw:
        return "UNKNOWN", "no source-reported line type"
    if norm == "landline":
        return "LANDLINE", "source reports landline"
    if norm != "wireless":
        return "UNKNOWN", "source reports {!r}, which is neither wireless nor landline".format(raw)

    # This axis is INDEPENDENT of attribution, and deliberately so. "Is this number a
    # mobile" and "does this number belong to this person" are different questions, which is
    # the whole reason there are five status fields instead of one band. A number can be
    # VERIFIED-MOBILE and SINGLE-SOURCE-PHONE at the same time -- that is the Knox control.
    #
    # VERIFIED-MOBILE means the line type came from an ALLOWLISTED SOURCE RECORD.
    # REPORTED-MOBILE means something claims mobile without that provenance.
    if src in octlib.LINE_TYPE_SOURCE_ALLOWLIST:
        return "VERIFIED-MOBILE", (
            "source record {} reports {!r}, normalized to wireless. This says nothing about "
            "whether the number belongs to this person — see phone_attribution_status — and "
            "it NEVER raises ownership or role confidence.".format(src, raw))
    return "REPORTED-MOBILE", (
        "something reports wireless, but not from an allowlisted source record. Line type "
        "must come from the source, never computed: US number portability makes every "
        "libphonenumber actor return FIXED_LINE_OR_MOBILE (doctrine 7).")


def compliance_status(ev):
    if octlib.tri(ev.get("deceased")) == "Y":
        return "DECEASED-HOLD", ("REPORTED-DECEASED — hard stop, routed to estate/heir "
                                 "research, never dialled")
    if octlib.tri(ev.get("is_litigator")) == "Y":
        return "LITIGATOR", "[TCPA LITIGATOR] — excluded from every import tab"
    dnc = ev.get("primary_dnc")
    if dnc is True:
        return "DNC-BLOCKED", "DNC — mail or email only; never presented as a call target"
    if dnc is None or dnc == "UNSCRUBBED" or not ev.get("dnc_checked_at"):
        return "UNSCRUBBED", octlib.NOT_SCRUBBED_STAMP
    ok, why = octlib.outreach_eligible(ev)
    return ("OUTREACH-ELIGIBLE", why) if ok else ("UNSCRUBBED", why)


# ---------------------------------------------------------------- reverse-phone ladder


def reverse_verdict(rev):
    """exact = last[:6] and first[:4] prefix match; listed = the reversed record actually
    carries this number in Phone-1..5.

    The band and the verdict are TWO columns, never merged into one score.
    """
    if not rev or rev.get("no_record"):
        return "DEAD"
    exact = bool(rev.get("exact"))
    listed = bool(rev.get("listed"))
    wireless = octlib.normalize_line_type(rev.get("line_type")) == "wireless"
    if exact and listed and wireless:
        return "CONFIRMED"
    if exact and listed:
        return "CONFIRMED-nonmobile"
    if exact:
        return "LIKELY"
    if rev.get("surname_only"):
        return "RELATIVE-ONLY"
    return "CONTRADICTED"


def apply_verdict(band, verdict):
    """CONTRADICTED demotes any band to WEAK and moves the row to Needs Review; CONFIRMED is
    required to print the words PRIMARY MOBILE; a missing verdict prints
    band + ' (unverified line type)'.
    """
    if verdict == "CONTRADICTED":
        return "WEAK", "Needs Review", "reverse-phone CONTRADICTED demotes any band"
    if not verdict or verdict == "UNKNOWN":
        return "{} (unverified line type)".format(band), "Call List", "no reverse verdict"
    return band, "Call List", "verdict {}".format(verdict)


def may_print_primary_mobile(phone_attr, line_type):
    """The ONLY place these two words are permitted."""
    return phone_attr == "VERIFIED-PHONE" and line_type == "VERIFIED-MOBILE"


# ---------------------------------------------------------------- ambiguity


def ambiguity_gate(candidates):
    """-> (ranked, ambiguity: bool, reason). Emits both, never picks."""
    ranked = sorted(candidates, key=lambda c: -(c.get("score") or 0))
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
    if len(ranked) < 2:
        return ranked, False, "fewer than two candidates"
    a, b = ranked[0], ranked[1]
    reasons = []
    if abs((a.get("score") or 0) - (b.get("score") or 0)) <= AMBIGUITY_POINTS:
        reasons.append("top two within {} points ({} vs {})".format(
            AMBIGUITY_POINTS, a.get("score"), b.get("score")))
    if a.get("anchored") == "Y" and b.get("anchored") == "Y":
        reasons.append("both anchored")
    if a.get("has_control_title") and b.get("has_control_title"):
        reasons.append("both carry a control title")
    if reasons:
        for c in (a, b):
            c["ambiguity"] = True
        return ranked, True, ("; ".join(reasons) + " — BOTH emitted as rank 1 and rank 2. "
                                                  "Never pick.")
    return ranked, False, "top two are separated"


# ---------------------------------------------------------------- band a row


def band(row, candidate, ev):
    own, own_why = ownership_status(row)
    role, role_why = role_status(candidate or {})
    attr, attr_why = phone_attribution_status(ev or {})
    line, line_why = line_type_status(ev or {})
    comp, comp_why = compliance_status(ev or {})
    verdict = reverse_verdict((ev or {}).get("reverse"))
    band_label, sheet, band_why = apply_verdict(
        "STRONG" if attr == "VERIFIED-PHONE" else "WEAK", verdict)

    out = {
        "ownership_status": own, "ownership_reason": own_why,
        "role_status": role, "role_reason": role_why,
        "phone_attribution_status": attr, "phone_attribution_reason": attr_why,
        "line_type_status": line, "line_type_reason": line_why,
        "compliance_status": comp, "compliance_reason": comp_why,
        "verdict": verdict, "band": band_label, "sheet": sheet, "band_reason": band_why,
        "may_print_primary_mobile": may_print_primary_mobile(attr, line),
        "anchored": octlib.tri((ev or {}).get("anchored")),
        "surname_match": octlib.tri((ev or {}).get("surname_match")),
        "geo_match": octlib.tri((ev or {}).get("geo_match")),
        "deceased": octlib.tri((ev or {}).get("deceased")),
        "is_litigator": octlib.tri((ev or {}).get("is_litigator")),
        "vendor_owner_claim": (ev or {}).get("property_owner"),
        "vendor_owner_claim_note": (
            "recorded for audit ONLY. Tracerfy's property_owner boolean is never an input to "
            "any predicate — see the Fort Stockton control."),
    }
    # Rule 1, asserted rather than assumed.
    if out["line_type_status"] == "VERIFIED-MOBILE" and out["ownership_status"] == "UNKNOWN":
        out["cross_check"] = ("VERIFIED-MOBILE on an UNKNOWN owner. That is a legitimate "
                              "state: line type answers a different question than ownership, "
                              "and it does not raise it.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="anchor_gate.py",
        description="Stage 9: emit the five status fields and the verdict ladder. Never one "
                    "band. Free; spends nothing.")
    ap.add_argument("--in", dest="infile", help="HUMANS.json")
    ap.add_argument("--contacts", help="contacts.jsonl")
    ap.add_argument("--census", help="CENSUS.json (for ownership_status)")
    ap.add_argument("--out-dir")
    ap.add_argument("--demo-fixture", help="band a single Tracerfy-shaped fixture")
    ap.add_argument("--parcel-addr-key", help="addr_key to anchor the fixture against")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.demo_fixture:
        fx = json.loads(pathlib.Path(args.demo_fixture).read_text(encoding="utf-8"))
        person = (fx.get("people") or [{}])[0]
        m = person.get("mailing_address") or {}
        key = octlib.addr_key(m.get("street", ""), m.get("city", ""), m.get("state", ""),
                              m.get("zip", ""))
        anchored = bool(args.parcel_addr_key and key == args.parcel_addr_key)
        phone = (person.get("phones") or [{}])[0]
        ev = {
            "source_a_names_the_exact_person_and_lists_the_phone": True,
            "source_a_has_another_strong_identifier": anchored,
            "source_b_present": False,          # Tracerfy alone is ONE source
            "source_b_upstream_lineage": None,
            "anchored": anchored,
            "primary_number_or_po_box_matches": anchored,
            "street_name_matches": anchored,
            "city_state_zip5_match": anchored,
            "required_secondary_unit_matches": anchored,
            "not_cmra_or_agent_hub": None,
            "line_type_source": "tracerfy.phones[].type",
            "source_line_type": phone.get("type"),
            "primary_dnc": phone.get("dnc"),
            "dnc_checked_at": octlib.utcnow_iso() if phone.get("dnc") is not None else None,
            "dnc_checked_age_days": 0 if phone.get("dnc") is not None else None,
            "national_dnc": phone.get("dnc"),
            "applicable_state_dnc": None, "internal_dnc": None,
            "deceased": person.get("deceased"),
            "is_litigator": person.get("litigator"),
            "property_owner": person.get("property_owner"),
            "state_outreach_policy_allows_channel": None,
        }
        row = {"owner_of_record": "(from the county layer)", "deed_status": "DEED-UNAVAILABLE",
               "deed_note": "no online recorder route implemented"}
        res = band(row, {}, ev)
        res["returned_addr_key"] = key
        res["anchored_against"] = args.parcel_addr_key
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            for k in ("ownership_status", "role_status", "phone_attribution_status",
                      "line_type_status", "compliance_status", "verdict", "band", "sheet",
                      "may_print_primary_mobile", "anchored", "deceased", "is_litigator",
                      "vendor_owner_claim"):
                print("{:28} {}".format(k, res[k]))
            print("\nreturned addr_key  {}".format(key))
            print("anchored against   {}".format(args.parcel_addr_key))
            for k in ("phone_attribution_reason", "line_type_reason", "compliance_reason"):
                print("\n{}\n  {}".format(k, res[k]))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
