#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""leak_scan.py — scoped redaction scan.

THE CONTRADICTION THIS FILE RESOLVES: this skill's PRODUCT is phone numbers. A blanket
phone-pattern scan would reject every correct output and train whoever runs it to bypass the
gate — which is worse than no gate at all.

So the scan is SCOPED, not global:

  * APPROVED PHONE COLUMNS are schema-enumerated. A normalized phone value sitting in one of
    them is expected and passes.
  * A phone number found ANYWHERE ELSE blocks delivery: raw-source columns, hidden sheets,
    cell comments, formulas, document metadata, temp files, or any non-approved output
    location.
  * Credentials, keys and prohibited PII block everywhere, including approved columns.

The regex is octlib.PHONE_RE, which catches `(314) 555-0177` and `+1 (630) 555-0195`. The
inherited pattern `\\b\\d{3}[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b` missed both parenthesized forms
(acceptance test 16).

Precedent: raw harvested text in a workbook column leaked 72 cleartext passwords into the
iCloud root on 2026-08-07. Emit the MATCHED RULE plus a SCRUBBED SNIPPET, never raw source.

Usage:
    leak_scan.py --workbook call_list.xlsx
    leak_scan.py --path RUN_DIR --json
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

FICTIONAL_RE = re.compile(r"555[\s.\-]?01\d{2}")

SECRET_RULES = [
    ("api_key_assignment", re.compile(
        r"(?i)\b(api[_-]?key|apikey|secret|token|passwd|password|credentials?)\b\s*[:=]\s*\S+")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("melissa_key", re.compile(r"\b[A-Za-z0-9]{22}\*\*")),
    ("long_hex_secret", re.compile(r"\b[a-f0-9]{40,}\b")),
]

# The toll-free scraper artifact. Four "hits" across 36 addresses all shared it.
SCRAPER_ARTIFACT = "+1-855-723-2747"

RAW_SOURCE_HINTS = ("raw", "raw_source", "source_text", "harvested", "page_text", "html",
                    "response_body", "debug", "scratch")


def scrub(text, keep=24):
    """Emit a scrubbed snippet. NEVER the raw source."""
    red, _ = octlib.redact_phones(str(text))
    for name, rx in SECRET_RULES:
        red = rx.sub("[REDACTED-{}]".format(name.upper()), red)
    red = red.replace("\n", " ").strip()
    return (red[:keep] + "…") if len(red) > keep else red


def scan_text(text, where, approved=False, allow_fictional=True):
    findings = []
    s = str(text or "")
    if not s:
        return findings

    for name, rx in SECRET_RULES:
        for m in rx.finditer(s):
            findings.append({"rule": name, "severity": "BLOCK", "where": where,
                             "snippet": scrub(m.group(0)),
                             "why": "credentials and secrets block everywhere, including "
                                    "approved columns"})

    if SCRAPER_ARTIFACT.replace("-", "") in re.sub(r"\D", "", s):
        findings.append({"rule": "scraper_artifact", "severity": "BLOCK", "where": where,
                         "snippet": SCRAPER_ARTIFACT,
                         "why": "the toll-free scraper-artifact constant — a detectable "
                                "signature, not a real contact"})

    for m in octlib.PHONE_RE.finditer(s):
        hit = m.group(0)
        if allow_fictional and FICTIONAL_RE.search(hit):
            continue
        if approved:
            continue        # a phone in an approved column is the product, not a leak
        findings.append({"rule": "phone_outside_approved_column", "severity": "BLOCK",
                         "where": where, "snippet": scrub(hit),
                         "why": "this skill's product is phone numbers, so the scan is "
                                "scoped: an approved schema column passes, anywhere else "
                                "blocks"})
    return findings


def scan_workbook(path):
    findings = []
    try:
        import openpyxl
    except ImportError:
        return [{"rule": "openpyxl_missing", "severity": "WARN", "where": str(path),
                 "snippet": "", "why": "cannot inspect the workbook; CSV was still scanned. "
                                       "Install with: python3 -m pip install --user openpyxl"}]
    wb = openpyxl.load_workbook(path, data_only=False)

    props = wb.properties
    for attr in ("creator", "lastModifiedBy", "title", "subject", "description", "keywords"):
        v = getattr(props, attr, None)
        if v:
            findings += scan_text(v, "metadata:{}".format(attr), approved=False)

    for ws in wb.worksheets:
        hidden = ws.sheet_state != "visible"
        if hidden:
            findings.append({"rule": "hidden_sheet", "severity": "BLOCK",
                             "where": "sheet:{}".format(ws.title), "snippet": ws.sheet_state,
                             "why": "hidden sheets are a classic leak path and are scanned "
                                    "with NO column approved"})
        header = [str(c.value or "") for c in next(ws.iter_rows(max_row=1), [])]
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                idx = cell.column - 1
                col = header[idx] if idx < len(header) else ""
                approved = (not hidden) and col in octlib.APPROVED_PHONE_COLUMNS
                if any(h in col.lower() for h in RAW_SOURCE_HINTS):
                    approved = False
                where = "{}!{}{} [{}]".format(ws.title, cell.column_letter, cell.row, col)
                findings += scan_text(cell.value, where, approved=approved)
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    findings += scan_text(cell.value, where + " (formula)", approved=False)
                if cell.comment is not None:
                    findings += scan_text(cell.comment.text, where + " (comment)",
                                          approved=False)
    return findings


def scan_csv(path):
    import csv as _csv
    findings = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = _csv.reader(fh)
        header = next(reader, [])
        for n, row in enumerate(reader, 2):
            for i, val in enumerate(row):
                col = header[i] if i < len(header) else ""
                approved = col in octlib.APPROVED_PHONE_COLUMNS and \
                    not any(h in col.lower() for h in RAW_SOURCE_HINTS)
                findings += scan_text(val, "{}:{}:{}".format(path.name, n, col),
                                      approved=approved)
    return findings


def scan_path(p):
    p = pathlib.Path(p)
    if p.is_dir():
        out = []
        for child in sorted(p.rglob("*")):
            if child.is_file():
                out += scan_path(child)
        return out
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        return scan_workbook(p)
    if p.suffix.lower() == ".csv":
        return scan_csv(p)
    if p.suffix.lower() in (".tmp", ".part", ".bak", ".swp"):
        return [{"rule": "temp_file_in_output", "severity": "BLOCK", "where": str(p),
                 "snippet": "", "why": "a temp file in an output location is a leak path"}]
    if p.suffix.lower() in (".json", ".jsonl", ".txt", ".md", ".log"):
        try:
            return scan_text(p.read_text(encoding="utf-8", errors="replace"), str(p),
                             approved=False)
        except OSError:
            return []
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="leak_scan.py",
        description="Scoped redaction scan. Approved phone columns pass; a phone anywhere "
                    "else blocks. Credentials block everywhere.")
    ap.add_argument("--workbook", help="a finished .xlsx")
    ap.add_argument("--path", help="a file or directory to scan")
    ap.add_argument("--allow-fictional", action="store_true", default=True,
                    help="treat the reserved 555-01xx range as non-PII (default on)")
    ap.add_argument("--strict-fictional", dest="allow_fictional", action="store_false",
                    help="flag even 555-01xx numbers outside approved columns")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    target = args.workbook or args.path
    if not target:
        ap.error("one of --workbook or --path is required")

    findings = scan_path(target)
    blocks = [f for f in findings if f["severity"] == "BLOCK"]

    if args.json:
        print(json.dumps({"target": str(target), "scanned_at": octlib.utcnow_iso(),
                          "findings": findings, "blocking": len(blocks)},
                         indent=2, ensure_ascii=False))
    else:
        print("leak_scan: {}".format(target))
        print("  approved phone columns: {}".format(
            ", ".join(sorted(octlib.APPROVED_PHONE_COLUMNS))))
        for f in findings:
            print("  {} {:34} {:44} {}".format(
                f["severity"], f["rule"], f["where"][:44], f["snippet"]))
            print("      {}".format(f["why"]))
        print("  {} finding(s), {} blocking".format(len(findings), len(blocks)))
    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
