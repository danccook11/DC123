#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""delivery_gate.py — blocking QA gate. RUNS IN A FRESH PROCESS.

Fresh process on purpose: a gate that shares memory with the builder that produced the
artifact can be satisfied by the builder's own in-memory state rather than by what is
actually on disk. This reads the finished workbook and nothing else.

BLOCKS delivery if ANY of these is true:

  1. a phone row lacks {source, retrieved_at, anchor_basis, identity_tier}
  2. a number lacks a DNC value AND lacks the literal "NOT YET SCRUBBED — do not dial or text"
  3. a phone has primary_line_type but no line_type_source
  4. any input APN has no COVERAGE.json disposition
  5. leak_scan.py hits
  6. a suppressed owner appears on the Call List sheet
  7. deceased == true or is_litigator == true appears outside the disclosure sheet
  8. any truth-valued field was coerced to N/false where no check ran (doctrine 18)
  9. HOUSEHOLD-PHONE or SINGLE-SOURCE-PHONE is rendered as PRIMARY MOBILE
 10. ownership_status == TAX-ROLL-OWNER on a row printed as VERIFIED-OWNER
 11. a role_status above PROBABLE-AUTHORITY rests only on a registered-agent, director,
     generic-officer or limited-partner edge
 12. has_wire set from anything outside the line-type allowlist

On failure it MOVES the workbook to qa_quarantine/ and exits nonzero. It does not warn and
continue: a gate that can be walked past is not a gate.

Usage:
    delivery_gate.py --workbook RUN_DIR/call_list.xlsx --coverage RUN_DIR/COVERAGE.json
    delivery_gate.py --rows rows.json --coverage COVERAGE.json --input-apns parcels.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402
import leak_scan  # noqa: E402

PROVENANCE_KEYS = ("source", "retrieved_at", "anchor_basis", "identity_tier")
DISCLOSURE_SHEETS = {"Read Me", "Needs Review", "Gaps",
                     "Dropped (audit, with suppression pattern)", "Sources & Method"}
TRI_FIELDS = ("anchored", "surname_match", "geo_match", "deceased", "is_litigator")


class Gate(object):
    def __init__(self):
        self.failures = []

    def block(self, check, detail, where=""):
        self.failures.append({"check": check, "detail": detail, "where": where})

    def report(self):
        for f in self.failures:
            print("BLOCK {:38} {}".format(f["check"], f["detail"]))
            if f["where"]:
                print("        at {}".format(f["where"]))
        return len(self.failures)


def check_row(g, row, sheet, evidence=None):
    where = "{}[{}]".format(sheet, row.get("owner_of_record") or row.get("contact_name") or "?")
    phone = (row.get("primary_mobile") or "").strip()
    line_type = (row.get("primary_line_type") or "").strip()

    # 1 — provenance on every emitted phone.
    # The 40-column call-list format carries provenance as FLAT COLUMNS rather than a nested
    # object, so accept either shape. What must never be accepted is its absence.
    if phone:
        prov = dict(row.get("provenance") or {})
        for key, flat in (("source", "identity_source"), ("retrieved_at", "retrieved_at"),
                          ("anchor_basis", "anchor_basis"),
                          ("identity_tier", "identity_tier")):
            if not prov.get(key) and row.get(flat) not in (None, "", "UNKNOWN"):
                prov[key] = row.get(flat)
        missing = [k for k in PROVENANCE_KEYS if not prov.get(k)]
        if missing:
            g.block("provenance-on-phone",
                    "phone present but provenance missing {} — a $0 name parse must never "
                    "render like a verified mobile".format(missing), where)

    # 2 — DNC value, or the literal stamp
    if phone:
        dnc = row.get("primary_dnc")
        has_value = dnc in (True, False)
        notes = " ".join(str(row.get(k) or "") for k in ("notes", "compliance_status",
                                                         "compliance_note"))
        if not has_value and octlib.NOT_SCRUBBED_STAMP not in notes:
            g.block("dnc-value-or-stamp",
                    "number has no DNC value and does not carry the literal "
                    "{!r}".format(octlib.NOT_SCRUBBED_STAMP), where)

    # 3 — line type must name its source
    if line_type and not (row.get("line_type_source") or "").strip():
        g.block("line-type-source-required",
                "primary_line_type={!r} with no line_type_source".format(line_type), where)

    # 12 — and that source must be on the allowlist
    src = (row.get("line_type_source") or "").strip()
    if src and src not in octlib.LINE_TYPE_SOURCE_ALLOWLIST:
        g.block("line-type-source-allowlist",
                "line_type_source {!r} is not allowlisted. Any libphonenumber-derived value "
                "is a HARD REJECT — US number portability makes it structurally incapable "
                "(doctrine 7).".format(src), where)

    # 8 — no coercion of unknowns
    for f in TRI_FIELDS:
        if f not in row:
            continue
        val = str(row.get(f) or "").strip()
        ran = row.get(f + "_checked")
        if val == "N" and ran is False:
            g.block("no-coercion-of-unknowns",
                    "{} serialized as 'N' but the check never ran — it must be UNKNOWN "
                    "(doctrine 18)".format(f), where)
        if val not in ("Y", "N", "UNKNOWN", ""):
            g.block("tri-vocabulary", "{}={!r} is not Y/N/UNKNOWN".format(f, val), where)

    # 9 — HOUSEHOLD / SINGLE-SOURCE may never print as PRIMARY MOBILE
    attr = row.get("phone_attribution_status")
    lts = row.get("line_type_status")
    rendered = " ".join(str(row.get(k) or "") for k in ("notes", "primary_label", "verdict"))
    if "PRIMARY MOBILE" in rendered.upper():
        if not (attr == "VERIFIED-PHONE" and lts == "VERIFIED-MOBILE"):
            g.block("primary-mobile-label",
                    "row rendered as PRIMARY MOBILE with phone_attribution_status={} and "
                    "line_type_status={}. Those words require VERIFIED-PHONE AND "
                    "VERIFIED-MOBILE.".format(attr, lts), where)

    # 10 — TAX-ROLL-OWNER must not print as VERIFIED-OWNER
    if row.get("ownership_status") == "TAX-ROLL-OWNER" and \
            "VERIFIED-OWNER" in rendered.upper():
        g.block("tax-roll-vs-verified",
                "ownership_status is TAX-ROLL-OWNER but the row is printed as "
                "VERIFIED-OWNER. The assessor roll is a billing record.", where)

    # 11 — role above PROBABLE-AUTHORITY needs a control-bearing edge
    if row.get("role_status") == "VERIFIED-AUTHORITY":
        edges = row.get("role_edges") or (evidence or {}).get("edges") or []
        kinds = {e.get("edge_type") if isinstance(e, dict) else str(e) for e in edges}
        kinds.discard(None)
        if kinds and not (kinds & octlib.CONTROL_EDGES):
            g.block("role-needs-control-edge",
                    "role_status VERIFIED-AUTHORITY rests only on {} — registered-agent, "
                    "director, generic officer and limited-partner edges never establish "
                    "control".format(sorted(kinds)), where)

    # 6 — suppressed owners must not reach the Call List
    if sheet == "Call List" and row.get("suppressed"):
        g.block("suppressed-on-call-list",
                "suppressed owner (pattern {!r}) appears on the Call List sheet".format(
                    row.get("suppression_pattern")), where)

    # 7 — deceased / litigator only on the disclosure sheets
    if sheet not in DISCLOSURE_SHEETS:
        if octlib.tri(row.get("deceased")) == "Y":
            g.block("deceased-outside-disclosure",
                    "deceased row appears on {} — it belongs on a disclosure sheet and is "
                    "never dialled".format(sheet), where)
        if octlib.tri(row.get("is_litigator")) == "Y":
            g.block("litigator-outside-disclosure",
                    "[TCPA LITIGATOR] row appears on {} — excluded from every import "
                    "tab".format(sheet), where)


def check_coverage(g, coverage_path, input_apns):
    if not coverage_path:
        g.block("coverage-required",
                "no COVERAGE.json supplied. Every input APN must carry a disposition from "
                "the closed vocabulary; a row with no disposition is a silent blank.")
        return
    doc = json.loads(pathlib.Path(coverage_path).read_text(encoding="utf-8"))
    rows = doc.get("rows") or {}
    for apn in input_apns:
        rec = rows.get(apn)
        if not rec:
            g.block("apn-without-disposition",
                    "input APN {!r} has no COVERAGE.json disposition".format(apn))
        elif rec.get("disposition") not in octlib.COVERAGE_DISPOSITIONS:
            g.block("disposition-vocabulary",
                    "APN {!r} disposition {!r} is not in the closed vocabulary".format(
                        apn, rec.get("disposition")))


def read_workbook_rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h or "") for h in rows[0]]
        for r in rows[1:]:
            out.append((ws.title, dict(zip(header, r))))
    return out


def quarantine(path):
    p = pathlib.Path(path)
    q = p.parent / "qa_quarantine"
    q.mkdir(parents=True, exist_ok=True)
    dest = q / p.name
    shutil.move(str(p), str(dest))
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="delivery_gate.py",
        description="Blocking QA gate. Runs in a FRESH PROCESS against the finished "
                    "artifact. On failure it quarantines the workbook and exits nonzero.")
    ap.add_argument("--workbook", help="finished .xlsx")
    ap.add_argument("--rows", help="JSON list of {sheet, row} for testing without openpyxl")
    ap.add_argument("--coverage", help="COVERAGE.json")
    ap.add_argument("--input-apns", help="CSV of the input APNs (column apn)")
    ap.add_argument("--no-quarantine", action="store_true",
                    help="report without moving the artifact (CI use)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    g = Gate()
    pairs = []

    if args.workbook:
        try:
            pairs = read_workbook_rows(args.workbook)
        except ImportError:
            g.block("openpyxl-missing",
                    "cannot read the workbook to gate it. Install with: python3 -m pip "
                    "install --user openpyxl. NOT gating is not an option.")
    elif args.rows:
        for item in json.loads(pathlib.Path(args.rows).read_text(encoding="utf-8")):
            pairs.append((item.get("sheet", "Call List"), item.get("row", item)))
    else:
        ap.error("one of --workbook or --rows is required")

    for sheet, row in pairs:
        check_row(g, row, sheet)

    apns = []
    if args.input_apns:
        with open(args.input_apns, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                apns += octlib.split_apns(r.get("apn"))
    if args.coverage or apns:
        check_coverage(g, args.coverage, apns)

    # 5 — leak scan
    if args.workbook and pathlib.Path(args.workbook).is_file():
        for f in leak_scan.scan_path(args.workbook):
            if f["severity"] == "BLOCK":
                g.block("leak-scan", "{}: {}".format(f["rule"], f["snippet"]), f["where"])

    n = g.report()
    result = {"checked_rows": len(pairs), "blocking": n, "failures": g.failures,
              "gated_at": octlib.utcnow_iso()}

    if n and args.workbook and not args.no_quarantine and \
            pathlib.Path(args.workbook).is_file():
        dest = quarantine(args.workbook)
        result["quarantined_to"] = str(dest)
        print("\nQUARANTINED -> {}".format(dest))

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\ndelivery_gate: {} row(s) checked, {} blocking".format(len(pairs), n))
        if not n:
            print("PASS — delivery permitted. Dial-readiness remains a PER-ROW property; "
                  "this workbook is not labelled dial-ready as a whole.")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
