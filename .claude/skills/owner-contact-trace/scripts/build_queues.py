#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_queues.py — the lost queue builders.

Seven queue artifacts exist on disk with NO GENERATOR: the selection logic was never saved.
This reconstructs it from the recoverable headers and the row counts, and says plainly where
the reconstruction is inference rather than recovery.

    SHERPA_APN_QUEUE.csv         apn,county,state,acreage,owner,situs
    SHERPA_GAP_QUEUE.csv   (790) apn,county,state,acreage,owner,situs,mailing
    SHERPA_GAP_50AC.csv    (151) apn,county,state,acreage,owner,situs,mailing
    SHERPA_BUSINESS_QUEUE.csv (312) business_name,street,city,state,zipcode,apn,acreage
    SHERPA_NEXT16.csv            apn,county,state,acreage,owner,situs
    APIFY_SITUS_QUEUE.csv  (348) address,apn,owner,acreage
    APIFY_ROUND2.csv       (137) address,apn,owner,acreage

RECONSTRUCTION HONESTY: the headers and counts are recovered facts. The SELECTION PREDICATES
below are inferred from the header shape, the counts, and the doctrine -- they are not the
original code. Each queue records its predicate in the output so a row can always be traced
back to why it was selected. Re-derive against a known list before treating a count as a
match.

APIFY_SITUS_QUEUE is reproduced because the artifact exists, but note the finding that
retired it: situs is not a contact axis (doctrine 12, measured yield 5 of 6,930 contact
rows). It is built with a loud warning and is not part of the default set.

Usage:
    build_queues.py --in CENSUS.json --out-dir RUN_DIR
    build_queues.py --in CENSUS.json --out-dir RUN_DIR --only sherpa_gap
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

BATCH = 250          # the paid address axis batches at 250
GAP_ACREAGE_MIN = 50.0


def acres(row):
    for k in ("acreage", "acres", "CALCULATED_AREA", "ACRES", "CALC_ACRES"):
        v = row.get(k) or (row.get("county_raw") or {}).get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def traced(row):
    return bool(row.get("traced") or row.get("contacts"))


def eligible_paid(row):
    """Only mail_class == residential AND a non-empty mail_csz are eligible.

    1,990 unique addresses survived from 2,659 Tier-A owners; the 669 rejected broke down as
    po_box 194 / suite_or_co 150 / none 193.
    """
    return bool(row.get("mail_class") == "residential"
                and (row.get("mail_city") or "") and (row.get("mail_zip") or ""))


def priority(row):
    """P1 individual + never-traced · P2 entity/trust/gov · P3 individual + already-traced."""
    cls = row.get("owner_class")
    if cls in ("entity", "trust", "trust_company", "gov"):
        return "P2"
    return "P3" if traced(row) else "P1"


QUEUES = {
    "sherpa_apn": {
        "file": "SHERPA_APN_QUEUE.csv",
        "header": ["apn", "county", "state", "acreage", "owner", "situs"],
        "predicate": "every non-suppressed row with an owner name — the APN-keyed queue",
        "warning": "APN-KEYED. Doctrine 1: a bare APN must never be the IDENTITY source. "
                   "690 parcels submitted APN-only returned 51 of 84 hits on a DIFFERENT "
                   "parcel. This queue is for corroboration only, and every result is "
                   "discarded unless its mailing address anchors.",
        "select": lambda r: not r.get("suppressed") and (r.get("owner_of_record") or "").strip(),
    },
    "sherpa_gap": {
        "file": "SHERPA_GAP_QUEUE.csv",
        "header": ["apn", "county", "state", "acreage", "owner", "situs", "mailing"],
        "predicate": "non-suppressed, has an owner name, has NO contact yet, and is "
                     "reverse-address eligible (recorded count: 790)",
        "select": lambda r: (not r.get("suppressed")
                             and (r.get("owner_of_record") or "").strip()
                             and not traced(r) and eligible_paid(r)),
    },
    "sherpa_gap_50ac": {
        "file": "SHERPA_GAP_50AC.csv",
        "header": ["apn", "county", "state", "acreage", "owner", "situs", "mailing"],
        "predicate": "the gap queue restricted to >= {} acres (recorded count: 151)".format(
            GAP_ACREAGE_MIN),
        "select": lambda r: (not r.get("suppressed")
                             and (r.get("owner_of_record") or "").strip()
                             and not traced(r) and eligible_paid(r)
                             and (acres(r) or 0) >= GAP_ACREAGE_MIN),
    },
    "sherpa_business": {
        "file": "SHERPA_BUSINESS_QUEUE.csv",
        "header": ["business_name", "street", "city", "state", "zipcode", "apn", "acreage"],
        "predicate": "entity-classed owners with a mailing address (recorded count: 312)",
        "warning": "Sherpa /api/business returns 404 / expected_results 0 when business_name "
                   "is sent ALONE. Send mailing_address too, PLUS "
                   "omit_registered_agents: true. ZIP presence does not matter.",
        "select": lambda r: (r.get("owner_class") == "entity"
                             and (r.get("owner_mailing_address") or "").strip()),
    },
    "sherpa_next16": {
        "file": "SHERPA_NEXT16.csv",
        "header": ["apn", "county", "state", "acreage", "owner", "situs"],
        "predicate": "the next 16 gap rows by descending acreage — a hand-sized batch. "
                     "INFERRED: the original selection is unrecoverable; only the count is "
                     "known.",
        "limit": 16,
        "sort": lambda r: -(acres(r) or 0),
        "select": lambda r: (not r.get("suppressed") and not traced(r) and eligible_paid(r)),
    },
    "apify_situs": {
        "file": "APIFY_SITUS_QUEUE.csv",
        "header": ["address", "apn", "owner", "acreage"],
        "predicate": "rows keyed on the SITUS address (recorded count: 348)",
        "warning": "DOCTRINE 12 RETIRED THIS AXIS. Owner-occupied means situs already equals "
                   "mailing; absentee means whoever answers is a tenant. Measured yield: 5 "
                   "of 6,930 contact rows. Reproduced only because the artifact exists — it "
                   "is NOT in the default set.",
        "opt_in": True,
        "select": lambda r: bool((r.get("situs_address") or "").strip()),
    },
    "apify_round2": {
        "file": "APIFY_ROUND2.csv",
        "header": ["address", "apn", "owner", "acreage"],
        "predicate": "second-pass mailing-address rows that round 1 left without a contact "
                     "(recorded count: 137)",
        "select": lambda r: (not r.get("suppressed") and not traced(r) and eligible_paid(r)
                             and r.get("round1_attempted")),
    },
}


def row_values(header, r):
    m = {
        "apn": r.get("apn") or "",
        "county": r.get("county") or "",
        "state": r.get("state") or "",
        "acreage": acres(r) if acres(r) is not None else "",
        "owner": r.get("owner_of_record") or "",
        "situs": r.get("situs_address") or "",
        "mailing": ", ".join(x for x in (r.get("owner_mailing_address"),
                                         r.get("mail_city"),
                                         " ".join(x for x in (r.get("mail_state"),
                                                              r.get("mail_zip")) if x))
                             if x),
        "business_name": r.get("owner_of_record") or "",
        "street": r.get("owner_mailing_address") or "",
        "city": r.get("mail_city") or "",
        "zipcode": r.get("mail_zip") or "",
        "address": ", ".join(x for x in (r.get("situs_address"), r.get("situs_city"),
                                         r.get("situs_zip")) if x),
    }
    return [m.get(h, "") for h in header]


def build(rows, key, out_dir):
    spec = QUEUES[key]
    sel = [r for r in rows if spec["select"](r)]
    if spec.get("sort"):
        sel.sort(key=spec["sort"])
    if spec.get("limit"):
        sel = sel[:spec["limit"]]

    out = pathlib.Path(out_dir) / spec["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(spec["header"])
        for r in sel:
            w.writerow(row_values(spec["header"], r))

    meta = {"queue": key, "file": spec["file"], "rows": len(sel),
            "header": spec["header"], "predicate": spec["predicate"],
            "reconstruction": ("headers and counts are RECOVERED; the selection predicate is "
                               "INFERRED from the header shape, the counts and the doctrine "
                               "— it is not the original code"),
            "batch_size": BATCH,
            "built_at": octlib.utcnow_iso()}
    if spec.get("warning"):
        meta["warning"] = spec["warning"]
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_queues.py",
        description="Rebuild the seven queue artifacts whose generator was never saved. "
                    "Free; writes CSV only.")
    ap.add_argument("--in", dest="infile", required=True, help="CENSUS.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", action="append", choices=sorted(QUEUES),
                    help="build only these queues (repeatable)")
    ap.add_argument("--include-opt-in", action="store_true",
                    help="also build queues retired by doctrine (apify_situs)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    doc = json.loads(pathlib.Path(args.infile).read_text(encoding="utf-8"))
    rows = doc.get("rows", [])

    keys = args.only or [k for k, v in QUEUES.items()
                         if args.include_opt_in or not v.get("opt_in")]
    metas = [build(rows, k, args.out_dir) for k in keys]

    if args.json:
        print(json.dumps(metas, indent=2, ensure_ascii=False))
        return 0

    print("build_queues: {} row(s) in, batch size {}".format(len(rows), BATCH))
    for m in metas:
        print("\n  {:24} {:>5} rows -> {}".format(m["queue"], m["rows"], m["file"]))
        print("    predicate: {}".format(m["predicate"]))
        if m.get("warning"):
            print("    WARNING:   {}".format(m["warning"]))
    print("\nNOTE {}".format(metas[0]["reconstruction"]) if metas else "")
    skipped = [k for k, v in QUEUES.items() if v.get("opt_in") and k not in keys]
    if skipped:
        print("NOT BUILT (retired by doctrine, pass --include-opt-in): {}".format(
            ", ".join(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
