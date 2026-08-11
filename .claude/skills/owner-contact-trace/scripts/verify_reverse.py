#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_reverse.py — stage 8: the reverse-phone verdict ladder.

Promotion to CONFIRMED requires this stage. ITS COST IS A SECOND BILLED CALL PER PHONE and
it must appear in the budget estimate — vendor_client.py's `--expected-phones` line is that
cost.

The ladder:
    exact   = last[:6] AND first[:4] prefix match on the reversed record
    listed  = the reversed record actually carries this number in Phone-1..5

    CONFIRMED            exact + listed + Wireless
    CONFIRMED-nonmobile  exact + listed
    LIKELY               exact
    RELATIVE-ONLY        surname only
    CONTRADICTED         neither
    DEAD                 no record

THE BAND AND THE VERDICT ARE TWO COLUMNS, never merged into one score:
  * CONTRADICTED demotes any band to WEAK and moves the row to Needs Review
  * CONFIRMED is required to print the words "PRIMARY MOBILE"
  * a missing verdict prints band + " (unverified line type)"

A carrier/HLR lookup confirms the NUMBER'S TYPE, not its SUBSCRIBER. It never satisfies
source B, so it can never produce CONFIRMED on its own.

Usage:
    verify_reverse.py --name "Dana Exampleton" --record <fixtures>/one_api_person.json \\
        --phone 865-555-0173
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402


def digits(s):
    return re.sub(r"\D", "", str(s or ""))


def name_parts(full):
    toks = [t for t in re.split(r"[^A-Za-z]+", str(full or "")) if t]
    if not toks:
        return "", ""
    return toks[0].upper(), toks[-1].upper()


def exact_match(query_name, record_name):
    """last[:6] and first[:4] prefix match. Deliberately tighter than surname5."""
    qf, ql = name_parts(query_name)
    rf, rl = name_parts(record_name)
    if not (qf and ql and rf and rl):
        return False
    return ql[:6] == rl[:6] and qf[:4] == rf[:4]


def listed(phone, record):
    """Does the reversed record actually carry this number in Phone-1..5?"""
    want = digits(phone)
    if not want:
        return False
    for i in range(1, 6):
        if digits(record.get("Phone-{}".format(i))) == want:
            return True
    for p in record.get("phones") or []:
        if digits(p if isinstance(p, str) else p.get("number")) == want:
            return True
    return False


def record_line_type(phone, record):
    want = digits(phone)
    for i in range(1, 6):
        if digits(record.get("Phone-{}".format(i))) == want:
            return record.get("Phone-{} Type".format(i)) or ""
    for p in record.get("phones") or []:
        if isinstance(p, dict) and digits(p.get("number")) == want:
            return p.get("type") or ""
    return ""


def surname_only(query_name, record_name):
    _, ql = name_parts(query_name)
    _, rl = name_parts(record_name)
    return bool(ql and rl and ql == rl)


def verify(query_name, phone, record, source=None, upstream_lineage=None,
           is_carrier_or_hlr=False):
    rec_name = record.get("name") or " ".join(
        x for x in (record.get("First Name"), record.get("Last Name")) if x)
    ex = exact_match(query_name, rec_name)
    li = listed(phone, record)
    lt = octlib.normalize_line_type(record_line_type(phone, record))

    if not rec_name:
        verdict, why = "DEAD", "no record returned for this number"
    elif ex and li and lt == "wireless":
        verdict, why = "CONFIRMED", "exact name prefix + number listed + source-reported wireless"
    elif ex and li:
        verdict, why = "CONFIRMED-nonmobile", "exact name prefix + number listed, line type {!r}".format(lt or "unknown")
    elif ex:
        verdict, why = "LIKELY", "exact name prefix, but the number is not listed on the record"
    elif surname_only(query_name, rec_name):
        verdict, why = "RELATIVE-ONLY", "surname matches but the given name does not — a relative or household member, not this person"
    else:
        verdict, why = "CONTRADICTED", "neither an exact name prefix nor a surname match"

    out = {"query_name": query_name, "phone": phone, "record_name": rec_name,
           "exact": ex, "listed": li, "line_type": lt, "verdict": verdict, "why": why,
           "source": source, "upstream_lineage": upstream_lineage,
           "checked_at": octlib.utcnow_iso()}

    if is_carrier_or_hlr:
        out["satisfies_source_b"] = False
        out["source_b_note"] = ("a carrier/HLR lookup confirms the NUMBER'S TYPE, not its "
                                "SUBSCRIBER — it never satisfies source B")
        if verdict == "CONFIRMED":
            out["verdict"] = "CONFIRMED-nonmobile"
            out["why"] += (" — downgraded: the only corroboration was a carrier lookup, "
                           "which does not attribute a subscriber")
    else:
        undeclared = not upstream_lineage or str(upstream_lineage).upper() in \
            (octlib.UNKNOWN, "UNDECLARED", "")
        out["satisfies_source_b"] = not undeclared
        if undeclared:
            out["source_b_note"] = ("upstream lineage is undeclared, so this FAILS CLOSED "
                                    "and cannot promote the phone past "
                                    "SINGLE-SOURCE-PHONE. Two actors reselling one "
                                    "aggregator are one source wearing two hats.")

    out["band_effect"] = {
        "CONTRADICTED": "demotes any band to WEAK and moves the row to Needs Review",
        "CONFIRMED": "the ONLY verdict that permits printing the words PRIMARY MOBILE",
    }.get(out["verdict"], "band prints as band + ' (unverified line type)' when absent")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="verify_reverse.py",
        description="Stage 8: reverse-phone verdict ladder. Each check is a SECOND BILLED "
                    "CALL per phone and must appear in the budget estimate.")
    ap.add_argument("--name", required=True, help="the person we queried for")
    ap.add_argument("--phone", required=True)
    ap.add_argument("--record", required=True, help="the reversed record, as JSON")
    ap.add_argument("--source", help="which vendor produced the reversed record")
    ap.add_argument("--lineage", help="declared upstream data source from the capability "
                                      "manifest. Undeclared FAILS CLOSED.")
    ap.add_argument("--carrier-lookup", action="store_true",
                    help="the record came from a carrier/HLR API — type only, not subscriber")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rec = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    res = verify(args.name, args.phone, rec, source=args.source,
                 upstream_lineage=args.lineage, is_carrier_or_hlr=args.carrier_lookup)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        for k in ("query_name", "record_name", "exact", "listed", "line_type", "verdict",
                  "satisfies_source_b"):
            print("{:22} {}".format(k, res[k]))
        print("\nwhy          {}".format(res["why"]))
        if res.get("source_b_note"):
            print("source B     {}".format(res["source_b_note"]))
        print("band effect  {}".format(res["band_effect"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
