#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""census.py — stage 1: build CENSUS.json, the complete identity inventory.

NO PAID CALL MAY FIRE while any REQ field is `missing`, as distinct from
`explicitly-unavailable`. `--coverage` emits CENSUS_COVERAGE.json, and that file is what
the budget gate reads.

Failure policy, which is deliberately per-row rather than per-run:

  * A blank `owner_of_record` triggers ONE free re-pull from the county layer. After that
    the ROW takes disposition NO-OWNER-NAME and drops out of the paid path. The run
    continues.
  * The RUN halts only if more than 20% of rows are blank. That signals a stale-cache or
    config fault -- exactly the 85-of-233 bug -- not 233 genuinely nameless parcels.
  * An unknown county fails with `NO_COUNTY_ADAPTER <state>/<county>` and a named gap.
    Never with an open question to Mitch.

Stage 1a (recorder/title validation) has no implementation in this build, so every row
that reaches it takes `DEED-UNAVAILABLE (<county>, <date>)` and is labelled
TAX-ROLL-OWNER, never VERIFIED-OWNER. That is doctrine 17 held honestly, not satisfied.

Usage:
    census.py --in parcels.csv --county tn_knox --out-dir RUN_DIR --coverage
    census.py --apn "090 07403" --county tn_knox --fixture tests/fixtures/knox_layer.json
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
import county_fetch  # noqa: E402

# Requirement level per field. REQ fields gate the paid axis.
REQUIREMENTS = [
    ("apn", "REQ"), ("apn_norm", "REQ"), ("parcel_id", "OPT"),
    ("county", "REQ"), ("state", "REQ"), ("fips", "PREF"),
    ("situs_address", "PREF"),
    ("owner_of_record", "REQ"), ("owner_2", "OPT"),
    ("owner_norm", "REQ"), ("owner_tight", "REQ"), ("owner_base", "REQ"),
    ("owner_class", "REQ"),
    ("owner_mailing_address", "REQ"), ("mail_city", "REQ"), ("mail_state", "REQ"),
    ("mail_zip", "REQ"),
    ("mail_class", "REQ"),
    ("registered_agent", "REQ_IF_ENTITY"), ("officers", "REQ_IF_ENTITY"),
    ("trustee_names", "REQ_IF_TRUST"),
    ("crm_hit", "REQ"),
]

BLANK_RUN_HALT_FRACTION = 0.20


# A row carrying one of these has already been dispositioned out of the paid path. Its
# empty fields are "we looked and there is nothing", not "we have not fetched it yet", so
# they must not hold the paid gate shut for every other row in the run.
TERMINAL_DISPOSITIONS = frozenset({"NO-OWNER-NAME", "SUPPRESSED-INSTITUTIONAL",
                                   "CRM-HIT", "NO-ROUTE-STATE"})


def field_state(row, field, cfg):
    """-> populated | explicitly-unavailable | missing.

    `explicitly-unavailable` means we looked and it is genuinely not obtainable -- either
    the county does not publish it (Monroe FL carries neither owner nor mailing fields on
    its layer) or the row has already been dispositioned out of the paid path. Reporting
    either as `missing` would read as a fetch failure and would block the paid gate forever.

    It is NOT the same as UNEVALUATED elsewhere in the skill: `missing` here means we
    should have it and do not.
    """
    v = row.get(field)
    if v not in (None, "", [], {}):
        return "populated"

    if row.get("coverage_disposition") in TERMINAL_DISPOSITIONS:
        return "explicitly-unavailable"

    mail_fields = cfg.get("mail_fields") or {}
    if field in ("owner_mailing_address", "mail_city", "mail_state", "mail_zip") \
            and not mail_fields:
        return "explicitly-unavailable"
    if field == "owner_of_record" and not (cfg.get("owner_fields") or []):
        return "explicitly-unavailable"
    if field == "owner_2" and cfg.get("owner_field_packs_both_owners"):
        return "explicitly-unavailable"
    if field == "fips" and not cfg.get("fips"):
        return "explicitly-unavailable"
    if field == "situs_address" and not (cfg.get("situs_fields") or {}):
        return "explicitly-unavailable"
    if field == "registered_agent" and row.get("owner_class") != "entity":
        return "explicitly-unavailable"
    if field == "officers" and row.get("owner_class") != "entity":
        return "explicitly-unavailable"
    if field == "trustee_names" and row.get("owner_class") != "trust":
        return "explicitly-unavailable"
    return "missing"


def coverage(rows, cfg):
    fields = {}
    for field, req in REQUIREMENTS:
        c = {"requirement": req, "populated": 0, "explicitly_unavailable": 0, "missing": 0}
        for row in rows:
            st = field_state(row, field, cfg)
            c["populated" if st == "populated"
              else "explicitly_unavailable" if st == "explicitly-unavailable"
              else "missing"] += 1
        if field == "owner_2" and cfg.get("owner_field_packs_both_owners"):
            c["note"] = ("this county packs both owners into one OWNER string; owner_2 is "
                         "OPT here or the county reports a permanent false gap")
        if field in ("owner_mailing_address", "mail_city", "mail_state", "mail_zip") \
                and not (cfg.get("mail_fields") or {}):
            c["note"] = "this layer publishes no owner mailing fields"
        if field == "crm_hit":
            c["note"] = ("stage 0b. A CRM hit suppresses duplicate SPEND only — it is never "
                         "evidence that the account still owns the parcel")
        if field in ("owner_class", "mail_class"):
            c["note"] = ("stage-2 output — expected to be missing until "
                         "classify_owner.py has run")
        fields[field] = c

    blocked = [f for f, c in fields.items()
               if c["requirement"] in ("REQ", "REQ_IF_ENTITY", "REQ_IF_TRUST")
               and c["missing"] > 0]
    return {
        "run_id": "",
        "retrieved_at": octlib.utcnow_iso(),
        "total_rows": len(rows),
        "paid_call_gate": "BLOCKED" if blocked else "OPEN",
        "blocked_reason": ("REQ field(s) still missing: " + ", ".join(sorted(blocked)))
                          if blocked else None,
        "fields": fields,
    }


def stage_1a(row, cfg):
    """Recorder / title validation. NOT IMPLEMENTED — emits a named gap, never a pass."""
    row["deed"] = None
    row["deed_status"] = "DEED-UNAVAILABLE"
    row["deed_note"] = ("DEED-UNAVAILABLE ({}, {}) — no online recorder route is implemented "
                        "for any county in this build. An assessor-only conclusion is "
                        "TAX-ROLL-OWNER, never VERIFIED-OWNER (doctrine 17)."
                        .format(cfg["county"], octlib.utcnow_iso()[:10]))
    row["ownership_status"] = "TAX-ROLL-OWNER"
    row["ownership_as_of"] = octlib.utcnow_iso()[:10]
    return row


def read_input(path, apn_column):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if apn_column not in (reader.fieldnames or []):
            raise SystemExit("column {!r} not in {}".format(apn_column, reader.fieldnames))
        for r in reader:
            for apn in octlib.split_apns(r.get(apn_column)) or [None]:
                if apn:
                    yield r.get(apn_column, "").strip(), r


def build(county_key, apns, fixture=None, no_cache=False, retry=True):
    cfg = county_fetch.load_config(county_key)
    rows, blanks, errors = [], 0, []
    for apn in apns:
        try:
            _, got = county_fetch.fetch(county_key, apn, fixture=fixture, no_cache=no_cache)
        except county_fetch.CountyFetchError as e:
            errors.append((apn, str(e)))
            got = []
        row = got[0] if got else None

        if row is None or not (row.get("owner_of_record") or "").strip():
            if retry and not fixture:
                # ONE free re-pull, cache bypassed. The stale-cache silent blank is the
                # single most common cause of a blank owner on a row the layer has.
                try:
                    _, got = county_fetch.fetch(county_key, apn, no_cache=True)
                    row = got[0] if got else row
                except county_fetch.CountyFetchError as e:
                    errors.append((apn, "retry: " + str(e)))
        if row is None:
            row = {"apn": apn, "apn_norm": octlib.napn(apn), "county": cfg["county"],
                   "state": cfg["state"], "fips": cfg.get("fips"), "owner_of_record": "",
                   "provenance": octlib.provenance(
                       source="county layer {} (no feature returned)".format(county_key),
                       identity_tier=octlib.UNKNOWN,
                       confidence_basis="no feature matched this parcel id")}
        if not (row.get("owner_of_record") or "").strip():
            blanks += 1
            row["coverage_disposition"] = "NO-OWNER-NAME"
            row["route"] = "NO_OWNER_NAME"
        stage_1a(row, cfg)
        rows.append(row)
    return cfg, rows, blanks, errors


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="census.py",
        description="Stage 1: build CENSUS.json, the complete identity inventory. Free; "
                    "spends nothing. No paid call may fire while a REQ field is missing.")
    ap.add_argument("--in", dest="infile", help="CSV of parcels")
    ap.add_argument("--apn-column", default="apn")
    ap.add_argument("--apn", action="append", help="single APN (repeatable)")
    ap.add_argument("--county", required=True, help="adapter key, e.g. tn_knox")
    ap.add_argument("--out-dir", help="RUN_DIR (default: <cache_root>/runs/<st>_<county>_<ts>)")
    ap.add_argument("--fixture", help="replay a recorded layer response (offline)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-retry", action="store_true",
                    help="skip the one free re-pull on a blank owner")
    ap.add_argument("--coverage", action="store_true",
                    help="also emit CENSUS_COVERAGE.json (the paid-call gate)")
    args = ap.parse_args(argv)

    if not args.infile and not args.apn:
        ap.error("one of --in or --apn is required")

    try:
        cfg = county_fetch.load_config(args.county)
    except county_fetch.NoCountyAdapter as e:
        print("{}\nNamed gap: this county has no adapter. Add config/counties/{}.json "
              "before running.".format(e, args.county), file=sys.stderr)
        return 3

    apns = list(args.apn or [])
    if args.infile:
        apns += [a for a, _ in read_input(args.infile, args.apn_column)]
    if not apns:
        print("no APNs to process", file=sys.stderr)
        return 1

    cfg, rows, blanks, errors = build(args.county, apns, fixture=args.fixture,
                                      no_cache=args.no_cache, retry=not args.no_retry)

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else \
        octlib.run_dir(cfg["state"], cfg["county"])
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = out_dir.name

    doc = {"run_id": run_id, "retrieved_at": octlib.utcnow_iso(),
           "county_config": args.county, "rows": rows}
    with open(out_dir / "CENSUS.json", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("census: {} row(s) -> {}".format(len(rows), out_dir / "CENSUS.json"))
    for apn, err in errors[:5]:
        print("  fetch error {}: {}".format(apn, err))

    if args.coverage:
        cov = coverage(rows, cfg)
        cov["run_id"] = run_id
        with open(out_dir / "CENSUS_COVERAGE.json", "w", encoding="utf-8") as fh:
            json.dump(cov, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print("coverage: paid_call_gate={}".format(cov["paid_call_gate"]))
        if cov["blocked_reason"]:
            print("  {}".format(cov["blocked_reason"]))

    frac = (blanks / float(len(rows))) if rows else 0.0
    if blanks:
        print("blank owner_of_record on {}/{} rows ({:.1%}) — each takes disposition "
              "NO-OWNER-NAME and drops out of the paid path".format(blanks, len(rows), frac))
    if frac > BLANK_RUN_HALT_FRACTION:
        print("HALT: {:.1%} of rows have a blank owner, above the {:.0%} threshold. That is "
              "a stale-cache or config fault, not {} nameless parcels. Check that the "
              "feature cache key includes the requested field list, then re-run with "
              "--no-cache.".format(frac, BLANK_RUN_HALT_FRACTION, blanks), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
