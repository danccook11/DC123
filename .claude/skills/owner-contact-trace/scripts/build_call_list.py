#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_call_list.py — stage 10: the deliverable.

Three shapes, all ONE ROW PER OWNER with APNs semicolon-listed, plus a parcel-detail sheet:

  --format calllist       40 columns, 8 sheets (default)
  --format sherpa         16 columns; leading zeros and internal spaces survive as TEXT
  --format launchcontrol  17 columns; Phone1/2/3 reordered MOBILE-FIRST per row, because a
                          texting platform cannot use landlines. Deceased and litigator rows
                          are excluded from the Import tab ENTIRELY.

CSV is written UNCONDITIONALLY. XLSX is written only if `import openpyxl` succeeds, printing
"XLSX skipped — openpyxl not installed; CSV written" rather than crashing at the end of a
paid run.

Grouping is on LAST-NAME-OR-BUSINESS + MAILING ADDRESS, never on the raw full-name string:
grouping on `Owner Full Name` fails whenever one parcel lists a joint owner and another does
not.

Dedupe is on the PERSON, not on (name, phone). The inherited signature made one human with
two numbers survive as two contacts and inflated every count.

`apns` is UNTRUNCATED. The source builder capped it at 12; that is not inherited.

Usage:
    build_call_list.py --run-dir RUN_DIR --format calllist --coverage
    build_call_list.py --run-dir RUN_DIR --format launchcontrol
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

SHEETS = ["Call List", "Entity Pierce Ledger", "Gaps", "Needs Review",
          "Dropped (audit, with suppression pattern)", "Relationship Clusters",
          "Sources & Method", "Read Me"]

SHERPA_COLS = ["Owner Full Name", "Owner First Name", "Owner Last Name", "Business Name",
               "Mailing Address", "Mailing City", "Mailing State", "Mailing Zip",
               "Property APN", "Property FIPS", "Property County", "Property Address",
               "Property City", "Property State", "Property Zip", "Custom 1"]

LAUNCHCONTROL_COLS = ["FirstName", "LastName", "Email", "MailingAddress", "MailingCity",
                      "MailingState", "MailingZip", "PropertyAddress", "PropertyCity",
                      "PropertyState", "PropertyZip", "Phone1", "Phone2", "Phone3", "APN",
                      "PropertyCounty", "Acreage"]


def schema_columns():
    """The 40 call-list columns, read from the schema so there is ONE source of truth."""
    p = pathlib.Path(__file__).resolve().parent.parent / "schemas" / "call_list.schema.json"
    return json.loads(p.read_text(encoding="utf-8"))["x-column-order"]


def group_key(row):
    """last-name-or-business + mailing address. NEVER the raw full-name string."""
    owner = row.get("owner_of_record") or ""
    if octlib.is_company(owner):
        ident = octlib.norm_owner(owner)["tight"]
    else:
        toks = octlib.norm_owner(owner)["spaced"].split()
        ident = toks[0] if toks else ""
    return "{}||{}".format(ident, row.get("addr_key") or "")


def person_key(contact):
    """Dedupe on the PERSON. Not on (name, phone) -- that inflates every count."""
    return octlib.norm_owner(contact.get("contact_name") or "")["tight"]


def merge_owner(rows, contacts_by_apn):
    """One row per owner, APNs semicolon-listed and untruncated."""
    groups = {}
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)

    out = []
    for key, members in groups.items():
        first = members[0]
        apns = []
        for m in members:
            for a in octlib.split_apns(m.get("apn")):
                if a not in apns:
                    apns.append(a)

        seen, contacts = set(), []
        for m in members:
            for c in contacts_by_apn.get(m.get("apn_norm"), []):
                pk = person_key(c)
                if pk and pk in seen:
                    continue
                seen.add(pk)
                contacts.append(c)

        out.append({"members": members, "first": first, "apns": apns,
                    "contacts": contacts, "group_key": key})
    return out


def render_calllist_row(g, cols):
    r, c = g["first"], (g["contacts"] or [{}])[0]
    phones = c.get("phones") or []
    alts = phones[1:3]
    val = {
        "owner_of_record": r.get("owner_of_record") or "UNKNOWN",
        "entity_type": r.get("entity_type") or "UNKNOWN",
        "county": r.get("county") or "UNKNOWN",
        "state": r.get("state") or "UNKNOWN",
        "parcel_count": len(g["members"]),
        "apns": "; ".join(g["apns"]),                       # UNTRUNCATED
        "ownership_status": r.get("ownership_status") or "UNKNOWN",
        "ownership_as_of": r.get("ownership_as_of") or "UNKNOWN",
        "deed_instrument_no": (r.get("deed") or {}).get("instrument_no")
                              or "DEED-UNAVAILABLE",
        "role_status": c.get("role_status") or "UNKNOWN",
        "contact_name": c.get("contact_name") or "UNRESOLVED",
        "contact_role": c.get("contact_role") or "UNKNOWN",
        "role_evidence": c.get("role_evidence") or "UNKNOWN",
        "contact_address": c.get("contact_address") or "UNKNOWN",
        "phone_attribution_status": c.get("phone_attribution_status") or "UNKNOWN",
        "line_type_status": c.get("line_type_status") or "UNKNOWN",
        "compliance_status": c.get("compliance_status") or "UNSCRUBBED",
        "verdict": c.get("verdict") or "UNKNOWN",
        "anchored": octlib.tri(c.get("anchored")),
        "anchor_basis": c.get("anchor_basis") or "UNKNOWN",
        "surname_match": octlib.tri(c.get("surname_match")),
        "geo_match": octlib.tri(c.get("geo_match")),
        "primary_mobile": (phones[0] or {}).get("number", "") if phones else "",
        "primary_line_type": octlib.normalize_line_type(
            (phones[0] or {}).get("type")) if phones else "",
        "line_type_source": (phones[0] or {}).get("line_type_source", "") if phones else "",
        "primary_carrier": (phones[0] or {}).get("carrier", "") if phones else "",
        "primary_last_seen": (phones[0] or {}).get("last_seen", "") if phones else "",
        "primary_dnc": (phones[0] or {}).get("dnc", "UNSCRUBBED") if phones else "UNSCRUBBED",
        "is_litigator": octlib.tri(c.get("is_litigator")),
        "deceased": octlib.tri(c.get("deceased")),
        "alt_phone_1": alts[0]["number"] if len(alts) > 0 else "",
        "alt_1_type": octlib.normalize_line_type(alts[0].get("type")) if len(alts) > 0 else "",
        "alt_phone_2": alts[1]["number"] if len(alts) > 1 else "",
        "alt_2_type": octlib.normalize_line_type(alts[1].get("type")) if len(alts) > 1 else "",
        "email": c.get("email") or "",
        "household_others": "; ".join(c.get("household_others") or []),
        "identity_source": c.get("identity_source") or "county assessor layer",
        "identity_tier": c.get("identity_tier", octlib.UNKNOWN),
        "sos_doc": c.get("sos_doc") or "UNEVALUATED",
        "sos_status": c.get("sos_status") or "UNEVALUATED",
        "retrieved_at": c.get("retrieved_at") or octlib.utcnow_iso(),
        "notes": c.get("notes") or "",
    }
    # A number with no DNC value MUST carry the literal stamp, or delivery_gate blocks it.
    if val["primary_mobile"] and val["primary_dnc"] not in (True, False):
        val["primary_dnc"] = "UNSCRUBBED"
        val["notes"] = (val["notes"] + " " + octlib.NOT_SCRUBBED_STAMP).strip()
    # Every field populated or carrying an explicit reason token — never "".
    for k in cols:
        if val.get(k, "") == "":
            val[k] = "" if k in ("email", "household_others", "notes", "alt_phone_1",
                                 "alt_phone_2", "alt_1_type", "alt_2_type",
                                 "primary_mobile", "primary_line_type", "line_type_source",
                                 "primary_carrier", "primary_last_seen") else "UNKNOWN"
    return val


def sheet_for(row):
    if row.get("verdict") == "CONTRADICTED":
        return "Needs Review"
    if row.get("compliance_status") in ("DECEASED-HOLD", "LITIGATOR"):
        return "Needs Review"
    return "Call List"


def render_sherpa(g):
    r = g["first"]
    owner = r.get("owner_of_record") or ""
    is_co = octlib.is_company(owner)
    toks = octlib.norm_owner(owner)["spaced"].split()
    return {
        "Owner Full Name": owner,
        "Owner First Name": "" if is_co else (toks[1] if len(toks) > 1 else ""),
        "Owner Last Name": "" if is_co else (toks[0] if toks else ""),
        "Business Name": owner if is_co else "",
        "Mailing Address": r.get("owner_mailing_address") or "",
        "Mailing City": r.get("mail_city") or "",
        "Mailing State": r.get("mail_state") or "",
        "Mailing Zip": r.get("mail_zip") or "",
        # Leading zeros and internal spaces (Duval REs) must survive as TEXT.
        "Property APN": r.get("apn") or "",
        "Property FIPS": r.get("fips") or "",
        "Property County": r.get("county") or "",
        "Property Address": r.get("situs_address") or "",
        "Property City": r.get("situs_city") or "",
        "Property State": r.get("state") or "",
        "Property Zip": r.get("situs_zip") or "",
        "Custom 1": "; ".join(g["apns"]),
    }


def render_launchcontrol(g):
    r, c = g["first"], (g["contacts"] or [{}])[0]
    # MOBILE-FIRST per row: a texting platform cannot use landlines.
    phones = sorted(c.get("phones") or [],
                    key=lambda p: (0 if octlib.normalize_line_type(p.get("type")) == "wireless"
                                   else 1, octlib.phone_sort_key(p)))
    nums = [p.get("number", "") for p in phones][:3] + ["", "", ""]
    toks = octlib.norm_owner(c.get("contact_name") or r.get("owner_of_record") or "").get(
        "spaced", "").split()
    return {
        "FirstName": toks[1] if len(toks) > 1 else "",
        "LastName": toks[0] if toks else "",
        "Email": c.get("email") or "",
        "MailingAddress": r.get("owner_mailing_address") or "",
        "MailingCity": r.get("mail_city") or "",
        "MailingState": r.get("mail_state") or "",
        "MailingZip": r.get("mail_zip") or "",
        "PropertyAddress": r.get("situs_address") or "",
        "PropertyCity": r.get("situs_city") or "",
        "PropertyState": r.get("state") or "",
        "PropertyZip": r.get("situs_zip") or "",
        "Phone1": nums[0], "Phone2": nums[1], "Phone3": nums[2],
        "APN": "; ".join(g["apns"]),
        "PropertyCounty": r.get("county") or "",
        "Acreage": r.get("acreage") or "",
    }


def launchcontrol_excluded(g):
    """Deceased and litigator rows are excluded from the Import tab ENTIRELY."""
    c = (g["contacts"] or [{}])[0]
    if octlib.tri(c.get("deceased")) == "Y":
        return "REPORTED-DECEASED — routed to estate/heir research, never texted"
    if octlib.tri(c.get("is_litigator")) == "Y":
        return "[TCPA LITIGATOR] — excluded from every import tab"
    if c.get("compliance_status") == "DNC-BLOCKED":
        return "DNC — mail or email only; a texting platform inherits the DNC constraint"
    if not (c.get("phones") or []):
        return "no contact found"
    return None


def coverage_report(rows, groups):
    """KPI denominator, stated once: classified mobiles / non-suppressed owner rows."""
    non_suppressed = [g for g in groups if not g["first"].get("suppressed")]
    mobiles = 0
    for g in non_suppressed:
        for c in g["contacts"]:
            for p in (c.get("phones") or []):
                if octlib.normalize_line_type(p.get("type")) == "wireless" and \
                        p.get("line_type_source") in octlib.LINE_TYPE_SOURCE_ALLOWLIST:
                    mobiles += 1
                    break
            else:
                continue
            break
    denom = len(non_suppressed)
    return {"classified_mobiles": mobiles, "non_suppressed_owner_rows": denom,
            "coverage": round(mobiles / float(denom), 4) if denom else None,
            "acceptance_bar": 0.50,
            "meets_bar": (mobiles / float(denom) >= 0.50) if denom else False,
            "note": "classified mobiles / non-suppressed owner rows. A 'classified' mobile "
                    "is one whose line type came from an ALLOWLISTED SOURCE RECORD — a "
                    "libphonenumber value never counts."}


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_xlsx(path, sheets, text_columns=()):
    try:
        import openpyxl
    except ImportError:
        print("XLSX skipped — openpyxl not installed; CSV written")
        return None
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (cols, rows) in sheets.items():
        ws = wb.create_sheet(title=name[:31])
        ws.append(list(cols))
        for r in rows:
            ws.append([r.get(c, "") if isinstance(r, dict) else r for c in cols])
        # Leading zeros and internal spaces (Duval REs) must survive as TEXT.
        for i, c in enumerate(cols, 1):
            if c in text_columns:
                letter = get_column_letter(i)
                for cell in ws[letter][1:]:
                    cell.number_format = "@"
                    if cell.value is not None:
                        cell.value = str(cell.value)
    wb.save(path)
    return path


def read_jsonl(p):
    p = pathlib.Path(p)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_call_list.py",
        description="Stage 10: build the deliverable. CSV always; XLSX only if openpyxl is "
                    "importable. Never labels a workbook dial-ready — that is a per-ROW "
                    "property.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--format", default="calllist",
                    choices=["calllist", "sherpa", "launchcontrol"])
    ap.add_argument("--coverage", action="store_true", help="emit the KPI denominator")
    ap.add_argument("--dry-run", action="store_true", help="report shape, write nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    run = pathlib.Path(args.run_dir)
    census = json.loads((run / "CENSUS.json").read_text(encoding="utf-8"))
    rows = census.get("rows", [])
    contacts = read_jsonl(run / "contacts.jsonl")
    by_apn = {}
    for c in contacts:
        by_apn.setdefault(c.get("apn_norm"), []).append(c)

    groups = merge_owner(rows, by_apn)
    kept = [g for g in groups if not g["first"].get("suppressed")]
    dropped = [g for g in groups if g["first"].get("suppressed")]

    if args.format == "sherpa":
        cols, out_rows = SHERPA_COLS, [render_sherpa(g) for g in kept]
        text_cols = ("Property APN", "Mailing Zip", "Property Zip", "Property FIPS")
        sheets = {"Sherpa": (cols, out_rows)}
    elif args.format == "launchcontrol":
        cols = LAUNCHCONTROL_COLS
        imp, review, nocontact = [], [], []
        for g in kept:
            why = launchcontrol_excluded(g)
            row = render_launchcontrol(g)
            if why is None:
                imp.append(row)
            elif why == "no contact found":
                nocontact.append(row)
            else:
                row = dict(row, Phone1="", Phone2="", Phone3="")
                row["Email"] = ""
                review.append(dict(row, LastName=row["LastName"] + " — " + why))
        out_rows = imp
        text_cols = ("APN", "MailingZip", "PropertyZip")
        sheets = {"Import": (cols, imp),
                  "Parcel Detail": (["apn", "county", "state", "owner_of_record"],
                                    [{"apn": r.get("apn"), "county": r.get("county"),
                                      "state": r.get("state"),
                                      "owner_of_record": r.get("owner_of_record")}
                                     for r in rows]),
                  "Needs Review": (cols, review),
                  "No Contact Found": (cols, nocontact)}
    else:
        cols = schema_columns()
        rendered = [render_calllist_row(g, cols) for g in kept]
        call, review = [], []
        for r in rendered:
            (review if sheet_for(r) == "Needs Review" else call).append(r)
        out_rows = call
        text_cols = ("apns",)
        readme = pathlib.Path(__file__).resolve().parent.parent / "templates" \
            / "call_list_readme.md"
        sheets = {
            "Call List": (cols, call),
            "Entity Pierce Ledger": (["legal_name", "sos_doc", "disposition", "hop_chain"],
                                     []),
            "Gaps": (["apn", "gap"], [{"apn": r.get("apn"),
                                       "gap": r.get("deed_note") or "DEED-UNAVAILABLE"}
                                      for r in rows]),
            "Needs Review": (cols, review),
            "Dropped (audit, with suppression pattern)":
                (["owner_of_record", "suppression_family", "suppression_pattern",
                  "suppression_matched_on"],
                 [{"owner_of_record": g["first"].get("owner_of_record"),
                   "suppression_family": g["first"].get("suppression_family"),
                   "suppression_pattern": g["first"].get("suppression_pattern"),
                   "suppression_matched_on": g["first"].get("suppression_matched_on")}
                  for g in dropped]),
            "Relationship Clusters": (["rel_cluster_id", "addr_key", "owners"],
                                      [{"rel_cluster_id": i + 1,
                                        "addr_key": g["group_key"].split("||")[-1],
                                        "owners": "; ".join(
                                            sorted({m.get("owner_of_record") or ""
                                                    for m in g["members"]}))}
                                       for i, g in enumerate(groups)]),
            "Sources & Method": (["item", "value"], [
                {"item": "run_id", "value": census.get("run_id")},
                {"item": "county_config", "value": census.get("county_config")},
                {"item": "cordata_vintage", "value": "n/a — not a Sunbiz state or not run"},
                {"item": "built_at", "value": octlib.utcnow_iso()},
                {"item": "dial-readiness", "value": "a PER-ROW property. This workbook is "
                                                    "NOT labelled dial-ready as a whole."}]),
            "Read Me": (["line"], [{"line": l} for l in
                                   readme.read_text(encoding="utf-8").splitlines()]),
        }

    if args.dry_run:
        print("dry run — nothing written")
        print("  format      {}".format(args.format))
        print("  owner rows  {} kept, {} suppressed (held back with a recorded pattern)"
              .format(len(kept), len(dropped)))
        print("  columns     {}".format(len(cols)))
        print("  sheets      {}".format(", ".join(sheets)))
        if args.coverage:
            print("  coverage    {}".format(json.dumps(coverage_report(rows, groups))))
        return 0

    csv_path = run / "call_list_{}.csv".format(args.format)
    write_csv(csv_path, cols, out_rows)
    print("wrote {}".format(csv_path))

    xlsx = write_xlsx(run / "call_list_{}.xlsx".format(args.format), sheets, text_cols)
    if xlsx:
        print("wrote {}".format(xlsx))

    if args.coverage:
        cov = coverage_report(rows, groups)
        with open(run / "coverage_kpi.json", "w", encoding="utf-8") as fh:
            json.dump(cov, fh, indent=2)
            fh.write("\n")
        print("coverage: {}/{} = {} (bar {}) — {}".format(
            cov["classified_mobiles"], cov["non_suppressed_owner_rows"],
            cov["coverage"], cov["acceptance_bar"],
            "MEETS" if cov["meets_bar"] else "BELOW BAR"))

    print("\nNEXT, in a FRESH PROCESS:")
    print("  python3 scripts/leak_scan.py --workbook {}".format(
        run / "call_list_{}.xlsx".format(args.format)))
    print("  python3 scripts/delivery_gate.py --workbook {} --coverage {}".format(
        run / "call_list_{}.xlsx".format(args.format), run / "COVERAGE.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
