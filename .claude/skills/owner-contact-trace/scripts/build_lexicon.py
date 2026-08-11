#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_lexicon.py — rebuild references/name_lexicon.json from an owner corpus.

The shipped lexicon is a BOOTSTRAP: its support values are ranks seeded from common US
name frequency, not measured counts from Mitch's owner corpus, because
`owner_mobile_enrichment/output/MASTER_OWNERS.csv` (1,787 assessor-format individual
records) was not present in the build environment.

This script replaces it with a real corpus build. It refuses to silently overstate its own
provenance: `_meta.support_semantics` moves to "corpus_count" only when the output is
entirely corpus-derived, and to "mixed" when a bootstrap file is merged in.

Free-pierce output stays at tier LEAD regardless of which lexicon is loaded. A better
lexicon makes better *leads*; it never makes a trustee.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

TRUST_KEYWORDS = [
    "TRUST", "TRUSTS", "TRUSTEE", "TRUSTEES", "TR", "TRS", "CO TR", "CO TRUSTEE",
    "LIVING", "LIVING TRUST", "REVOCABLE", "IRREVOCABLE", "FAMILY", "FAMILY TRUST",
    "LAND TRUST", "TESTAMENTARY", "ESTATE OF", "LIFE EST", "LIFE ESTATE",
    "SURVIVORS", "MARITAL", "REMAINDER", "REMAINDERMAN", "LIFE TENANT",
]
CORPORATE_SUFFIXES = [
    "LLC", "L L C", "LC", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
    "LP", "LLP", "LLLP", "LTD", "LIMITED", "PLLC", "PARTNERSHIP", "PA",
]
# Single letters and generic particles are never people.
STOP = frozenset("A B C D E F G H I J K L M N O P Q R S T U V W X Y Z".split()) | {
    "JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DR", "AND", "THE", "OF", "ET",
    "AL", "UX", "VIR", "ETAL", "DBA", "AKA", "FKA",
}


def tokens(owner_raw):
    """Yield candidate name tokens from one assessor owner string, or nothing at all.

    `octlib.is_company()` is the first line of defence and it is the one that matters:
    without it `MARTIN MARIETTA MATERIALS INC` contributes MARTIN and MARIETTA, and
    `CARTER MILL LLC` contributes CARTER and MILL. CARTER is a legitimate surname and
    always will be — the suffix is what disqualifies the string, not the token.
    """
    if octlib.is_company(owner_raw):
        return []
    spaced = octlib.norm_owner(owner_raw)["spaced"]
    for kw in sorted(TRUST_KEYWORDS, key=len, reverse=True):
        spaced = re.sub(r"\b" + re.escape(kw) + r"\b", " ", spaced)
    out = []
    for part in re.split(r"\s*&\s*|\s+AND\s+", spaced):
        toks = [t for t in part.split() if t not in STOP and len(t) > 1 and t.isalpha()]
        if toks:
            out.append(toks)
    return out


def build(rows, owner_column):
    """Count token support in both assessor orderings.

    Assessor format is LAST FIRST MID, but lists are mixed, so a token is credited to LAST
    when it leads and to FIRST when it follows — the same token can support both, which is
    correct (JAMES is a common given name and a common surname).
    """
    first, last, seen = {}, {}, 0
    for row in rows:
        raw = row.get(owner_column) or ""
        if not raw.strip():
            continue
        groups = tokens(raw)
        if not groups:
            continue
        seen += 1
        for toks in groups:
            last[toks[0]] = last.get(toks[0], 0) + 1
            for t in toks[1:]:
                first[t] = first.get(t, 0) + 1
    return first, last, seen


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_lexicon.py",
        description="Rebuild references/name_lexicon.json from an assessor owner corpus. "
                    "Replaces the shipped BOOTSTRAP lexicon with measured counts.")
    ap.add_argument("--in", dest="infile", required=True,
                    help="CSV of owner records, e.g. MASTER_OWNERS.csv")
    ap.add_argument("--owner-column", default="owner_of_record",
                    help="column holding the raw assessor owner string "
                         "(default: owner_of_record)")
    ap.add_argument("--out", default=None,
                    help="output path (default: references/name_lexicon.json next to this "
                         "script's skill root)")
    ap.add_argument("--min-support", type=int, default=2,
                    help="support threshold free_pierce.py requires to promote a token "
                         "(default: 2)")
    ap.add_argument("--merge", action="store_true",
                    help="augment the existing lexicon instead of replacing it. Batch mode "
                         "uses this; single-property mode never does, because a one-row "
                         "dataset gives every token support 0 and the $0 leg would vanish.")
    ap.add_argument("--force", action="store_true",
                    help="required to overwrite a BOOTSTRAP lexicon without --merge")
    args = ap.parse_args(argv)

    here = pathlib.Path(__file__).resolve().parent
    out = pathlib.Path(args.out) if args.out else here.parent / "references" / "name_lexicon.json"

    existing = None
    if out.is_file():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            existing = None
    prior_semantics = (existing or {}).get("_meta", {}).get("support_semantics")
    if existing and prior_semantics == "bootstrap_rank" and not (args.merge or args.force):
        print("refusing to overwrite a BOOTSTRAP lexicon without --merge or --force.\n"
              "  --merge keeps the bootstrap tokens and marks the result 'mixed'\n"
              "  --force discards them and marks the result 'corpus_count'", file=sys.stderr)
        return 2

    with open(args.infile, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if args.owner_column not in (reader.fieldnames or []):
            print("column {!r} not in {}".format(args.owner_column, reader.fieldnames),
                  file=sys.stderr)
            return 2
        first, last, seen = build(reader, args.owner_column)

    semantics = "corpus_count"
    if args.merge and existing:
        semantics = "mixed" if prior_semantics == "bootstrap_rank" else "corpus_count"
        for key, target in (("FIRST", first), ("LAST", last)):
            for tok, val in (existing.get(key) or {}).items():
                target[tok] = target.get(tok, 0) + int(val)

    prov = ("Built from {} ({} owner rows contributed tokens) on {}."
            .format(os.path.basename(args.infile), seen,
                    datetime.date.today().isoformat()))
    if semantics == "mixed":
        prov += (" MERGED with a prior BOOTSTRAP lexicon, so support values are part measured "
                 "count and part seeded rank. Treat thresholds as approximate.")
    elif args.merge:
        prov += " Merged with a prior corpus build."

    doc = {
        "_meta": {
            "provenance": prov,
            "built_at": datetime.date.today().isoformat(),
            "support_semantics": semantics,
            "min_support_to_promote": args.min_support,
            "source_file": os.path.basename(args.infile),
            "source_rows_contributing": seen,
            "guardrail_note": (
                "The lexicon is the SECOND line of defence. octlib.is_company() is the "
                "first: a corporate suffix with no trust marker blocks person-parsing "
                "regardless of what this file contains."),
            "counts": {"first": len(first), "last": len(last)},
        },
        "FIRST": dict(sorted(first.items())),
        "LAST": dict(sorted(last.items())),
        "TRUST_KEYWORDS": TRUST_KEYWORDS,
        "CORPORATE_SUFFIXES": CORPORATE_SUFFIXES,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    promotable = sum(1 for v in first.values() if v >= args.min_support)
    print("wrote {}".format(out))
    print("  rows contributing tokens : {}".format(seen))
    print("  FIRST tokens             : {} ({} at support >= {})".format(
        len(first), promotable, args.min_support))
    print("  LAST tokens              : {}".format(len(last)))
    print("  support_semantics        : {}".format(semantics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
