#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify_owner.py — stage 2: classify, and suppress with a recorded pattern.

Adds to every census row:
    owner_class      gov | trust_company | trust | entity | individual
    entity_type      llc | lp | corp | trust | estate | gov | individual | unknown
    mail_class       residential | commercial | po_box | suite_or_co | none | UNEVALUATED
    suppressed       bool, with the LITERAL matched pattern recorded
    route            the stage the row goes to next

Two rules this stage exists to enforce:

  * Nothing is deleted. Institutional, government and operator owners are SUPPRESSED with
    a recorded matched pattern and stay visible on the audit sheet. `pinellas.json` said
    "screen out explicitly" for the Stauffer Superfund site in a COMMENT ONLY; the filter
    was never written and Stauffer shipped. A comment in a config is not a filter.
  * Outside Florida the agent-desk gate is UNEVALUATED, not a clean residential pass. The
    address-frequency index is built from the FL bulk file and does not exist elsewhere, so
    a missing count must never read as "safe to reverse-search".

Usage:
    classify_owner.py --in CENSUS.json --out-dir RUN_DIR
    classify_owner.py --owner "MILAM STEPHEN WESLEY CO TR" --mail "PO BOX 5"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402
import county_fetch  # noqa: E402

# Routes taken after classification.
ROUTES = {
    "gov": "SUPPRESS",
    "trust_company": "SUPPRESS",       # institutional trustee/bank — held back, not deleted
    "trust": "STAGE_3_FREE_PIERCE",    # lexicon LEAD only, then TRUST-NEEDS-DEED
    "entity": "STAGE_4_REGISTRY_PIERCE",
    "individual": "STAGE_7_PERSON_AXIS",
}

# Only Florida has an entity address-frequency index (built from the Sunbiz bulk file).
INDEXED_STATES = frozenset({"FL"})


def classify_row(row, entity_counts=None):
    """Classify one census row in place and return it."""
    owner_raw = row.get("owner_of_record") or ""
    mail_blob = " ".join(str(row.get(k) or "") for k in
                         ("owner_mailing_address", "mail_city", "mail_state", "mail_zip"))

    cls = octlib.classify(owner_raw)
    row["owner_class"] = cls["owner_class"]
    row["entity_type"] = cls["entity_type"]
    row["owner_class_reason"] = cls["reason"]
    row["owner_class_pattern"] = cls["matched_pattern"]

    state = (row.get("state") or "").upper()
    index_available = state in INDEXED_STATES
    key = row.get("addr_key") or ""
    count = None
    if entity_counts is not None and key:
        count = entity_counts.get(key)
        index_available = True

    mc = octlib.mail_class(
        row.get("owner_mailing_address") or "",
        row.get("mail_city") or "", row.get("mail_state") or "", row.get("mail_zip") or "",
        entity_count=count, index_available=index_available)
    row.update(mc)
    row["entities_at_this_address"] = count

    # Only mail_class == residential may be reverse-address searched (doctrine 9).
    row["reverse_address_eligible"] = bool(
        mc["mail_class"] == "residential" and (row.get("mail_city") or "")
        and (row.get("mail_zip") or ""))
    if not row["reverse_address_eligible"]:
        row["reverse_address_ineligible_reason"] = (
            "mail_class={}".format(mc["mail_class"]) if mc["mail_class"] != "residential"
            else "mail_csz incomplete")

    inst = octlib.institutional_match(owner_raw, mail_blob)
    if inst:
        row["suppressed"] = True
        row["suppression_family"] = inst["family"]
        row["suppression_pattern"] = inst["pattern"]
        row["suppression_matched_on"] = inst["matched_on"]
        row["route"] = "SUPPRESS"
        row["coverage_disposition"] = "SUPPRESSED-INSTITUTIONAL"
    elif cls["owner_class"] in ("gov", "trust_company"):
        row["suppressed"] = True
        row["suppression_family"] = cls["owner_class"]
        row["suppression_pattern"] = cls["matched_pattern"] or cls["owner_class"]
        row["suppression_matched_on"] = "owner"
        row["route"] = "SUPPRESS"
        row["coverage_disposition"] = "SUPPRESSED-INSTITUTIONAL"
    else:
        row["suppressed"] = False
        row["suppression_pattern"] = None
        row["route"] = ROUTES.get(cls["owner_class"], "STAGE_7_PERSON_AXIS")
        row["coverage_disposition"] = "UNEVALUATED"

    if not owner_raw.strip():
        row["route"] = "NO_OWNER_NAME"
        row["coverage_disposition"] = "NO-OWNER-NAME"

    row["classified_at"] = octlib.utcnow_iso()
    return row


def load_entity_counts(path):
    """address addr_key -> count of entities filing there. FL only."""
    if not path:
        return None
    p = pathlib.Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def summarize(rows):
    out = {"total": len(rows), "owner_class": {}, "mail_class": {}, "route": {},
           "suppressed": 0, "reverse_address_eligible": 0}
    for r in rows:
        for k in ("owner_class", "mail_class", "route"):
            v = r.get(k) or "UNKNOWN"
            out[k][v] = out[k].get(v, 0) + 1
        out["suppressed"] += 1 if r.get("suppressed") else 0
        out["reverse_address_eligible"] += 1 if r.get("reverse_address_eligible") else 0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="classify_owner.py",
        description="Stage 2: classify owners, compute mail_class, and suppress "
                    "institutional owners with a recorded matched pattern. Free.")
    ap.add_argument("--in", dest="infile", help="CENSUS.json from census.py")
    ap.add_argument("--out-dir", help="RUN_DIR; writes CENSUS.json back with classification")
    ap.add_argument("--entity-address-index",
                    help="FL address-frequency index (addr_key -> count). Absent means the "
                         "agent-desk gate is UNEVALUATED, which is NOT a clean pass.")
    ap.add_argument("--coverage", action="store_true",
                    help="refresh CENSUS_COVERAGE.json after classifying. owner_class and "
                         "mail_class are stage-2 outputs, so the paid-call gate cannot open "
                         "until this has run.")
    ap.add_argument("--owner", help="classify a single owner string and exit")
    ap.add_argument("--mail", default="", help="mailing blob to pair with --owner")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.owner:
        row = {"owner_of_record": args.owner, "owner_mailing_address": args.mail,
               "state": "", "addr_key": octlib.addr_key(args.mail)}
        classify_row(row)
        keys = ("owner_class", "entity_type", "owner_class_reason", "mail_class",
                "mail_class_reason", "agent_desk_gate", "suppressed",
                "suppression_pattern", "route", "reverse_address_eligible")
        if args.json:
            print(json.dumps({k: row.get(k) for k in keys}, indent=2, ensure_ascii=False))
        else:
            for k in keys:
                print("{:28} {}".format(k, row.get(k)))
        return 0

    if not args.infile:
        ap.error("--in CENSUS.json is required unless --owner is given")

    doc = json.loads(pathlib.Path(args.infile).read_text(encoding="utf-8"))
    counts = load_entity_counts(args.entity_address_index)
    if counts is None:
        print("NOTE no entity address-frequency index supplied — the agent-desk gate is "
              "UNEVALUATED for every non-FL row. That is not a clean residential pass.")
    for row in doc.get("rows", []):
        classify_row(row, counts)

    doc["classified_at"] = octlib.utcnow_iso()
    doc["classification_summary"] = summarize(doc.get("rows", []))

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else pathlib.Path(args.infile).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "CENSUS.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if args.coverage:
        import census  # local import: classify_owner is usable without it
        cfg = county_fetch.load_config(doc.get("county_config") or "")
        cov = census.coverage(doc.get("rows", []), cfg)
        cov["run_id"] = doc.get("run_id", "")
        with open(out_dir / "CENSUS_COVERAGE.json", "w", encoding="utf-8") as fh:
            json.dump(cov, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print("coverage refreshed: paid_call_gate={}".format(cov["paid_call_gate"]))
        if cov["blocked_reason"]:
            print("  {}".format(cov["blocked_reason"]))

    s = doc["classification_summary"]
    print("classify_owner: {} rows -> {}".format(s["total"], out))
    for k in ("owner_class", "mail_class", "route"):
        print("  {:12} {}".format(k, json.dumps(s[k], sort_keys=True)))
    print("  suppressed   {} (held back with a recorded pattern, NOT deleted)"
          .format(s["suppressed"]))
    print("  reverse-address eligible {}".format(s["reverse_address_eligible"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
