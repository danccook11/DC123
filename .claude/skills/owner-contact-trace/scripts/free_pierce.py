#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""free_pierce.py — stage 3: $0 name parse against the frozen lexicon.

OUTPUT TIER IS `LEAD`. ALWAYS. Nothing this script produces is a trustee, a manager, or a
controller. No Secretary of State registers a trust, and a person named inside
`SMITH FAMILY TRUST` may be the settlor, a beneficiary, a deceased grandparent, or nobody
currently living.

Promotion out of `LEAD` requires a government record: a vesting deed, trustee deed,
certification or memorandum of trust, recorded successor-trustee instrument, probate record,
or a registry officer entry that independently names the same person. This script never
performs that promotion; it only produces the search leads that make it possible.

Two guards, in order of importance:

  1. `octlib.is_company()` — a corporate suffix with no trust marker blocks person-parsing
     outright. Without it `MARTIN MARIETTA MATERIALS INC` yields "Marietta Martin" and
     `CARTER MILL LLC` yields "Mill Carter". CARTER and MILL are legitimate personal names,
     so no lexicon can catch this; only the suffix can.
  2. `FIRST[token] >= min_support` from the frozen lexicon.

SINGLE-PROPERTY MODE USES THE FROZEN LEXICON AS-IS and never augments it. A one-row dataset
gives every token support 0, so a "learn from the list" design silently deletes the entire
$0 leg exactly when it is most needed (acceptance test 11).

Usage:
    free_pierce.py --owner "BRIAN & CONNIE PIERCE LIVING TRUST"
    free_pierce.py --in CENSUS.json --out-dir RUN_DIR
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

STOP = frozenset({"JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DR", "AND", "THE",
                  "OF", "ET", "AL", "UX", "VIR", "DBA", "AKA", "FKA"})


def load_lexicon(path=None):
    p = pathlib.Path(path) if path else \
        pathlib.Path(__file__).resolve().parent.parent / "references" / "name_lexicon.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.setdefault("_meta", {})
    return doc


def strip_trust_words(spaced, keywords):
    out = spaced
    for kw in sorted(keywords, key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(kw) + r"\b", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def parse_people(owner_raw, lex, min_support=None):
    """-> {"tier","people","residual_tokens","reason","disposition"}.

    `people` is a list of {first, last, basis}. Every entry is a LEAD.
    """
    meta = lex.get("_meta", {})
    min_support = min_support if min_support is not None else \
        int(meta.get("min_support_to_promote", 2))
    FIRST, LAST = lex.get("FIRST", {}), lex.get("LAST", {})
    kws = lex.get("TRUST_KEYWORDS", [])

    spaced = octlib.norm_owner(owner_raw)["spaced"]
    residual = [t for t in strip_trust_words(spaced, kws).split()
                if t not in STOP and len(t) > 1 and t.isalpha()]

    # A leading token that is a known surname. This is computed for COMPANY strings too,
    # and deliberately so: "look for a registry officer surnamed PARKER" is a legitimate
    # free search lead. What it is not, ever, is a person (acceptance test 12).
    eponymous = None
    if residual and LAST.get(residual[0], 0) >= min_support:
        eponymous = {
            "surname": residual[0],
            "note": "SEARCH LEAD and ranking signal only. Reaches PROBABLE-AUTHORITY only "
                    "when a registry officer record INDEPENDENTLY names that person; with "
                    "the name inference alone it caps at LEAD / BENEFICIAL-CONTROL-UNKNOWN. "
                    "A surname in a company name is not evidence of control."}

    if octlib.is_company(owner_raw):
        out = {"tier": "NONE", "people": [], "residual_tokens": residual,
               "reason": "is_company() guard: corporate suffix with no trust marker. "
                         "Parsing a person out of this string is how "
                         "'MARTIN MARIETTA MATERIALS INC' becomes 'Marietta Martin' and "
                         "'CARTER MILL LLC' becomes 'Mill Carter'.",
               "disposition": "NOT-A-PERSON-STRING",
               "lexicon_provenance": meta.get("support_semantics", "unknown"),
               "min_support": min_support}
        if eponymous:
            out["eponymous_surname_lead"] = eponymous
            out["reason"] += (" An eponymous surname lead IS still emitted — it is a free "
                              "registry search term, not a person.")
        return out

    people = []

    # Shared-surname idiom: FIRST & FIRST LAST ... -> two people sharing the trailing
    # surname. "BRIAN & CONNIE PIERCE LIVING TRUST" -> Brian Pierce + Connie Pierce.
    if "&" in spaced or re.search(r"\bAND\b", spaced):
        parts = [p.strip() for p in re.split(r"\s*&\s*|\s+AND\s+",
                                             strip_trust_words(spaced, kws)) if p.strip()]
        if len(parts) >= 2:
            tail = parts[-1].split()
            surname = None
            for tok in reversed(tail):
                if LAST.get(tok, 0) >= min_support:
                    surname = tok
                    break
            if surname:
                for p in parts:
                    toks = [t for t in p.split() if t not in STOP and t.isalpha()]
                    givens = [t for t in toks
                              if t != surname and FIRST.get(t, 0) >= min_support]
                    if givens:
                        people.append({"first": givens[0], "last": surname,
                                       "basis": "shared-surname idiom, lexicon support "
                                                "FIRST={} LAST={}".format(
                                                    FIRST.get(givens[0], 0),
                                                    LAST.get(surname, 0))})

    # Assessor orderings: LAST FIRST MID, and FIRST MID LAST.
    if not people and len(residual) >= 2:
        a, b = residual[0], residual[1]
        if LAST.get(a, 0) >= min_support and FIRST.get(b, 0) >= min_support:
            people.append({"first": b, "last": a,
                           "basis": "LAST FIRST MID ordering, lexicon support "
                                    "LAST={} FIRST={}".format(LAST[a], FIRST[b])})
        elif FIRST.get(a, 0) >= min_support and LAST.get(residual[-1], 0) >= min_support:
            people.append({"first": a, "last": residual[-1],
                           "basis": "FIRST MID LAST ordering, lexicon support "
                                    "FIRST={} LAST={}".format(FIRST[a], LAST[residual[-1]])})

    if people:
        tier, disposition = "LEAD", "LEAD-ONLY"
        reason = ("names parsed from the owner string against the frozen lexicon. LEAD "
                  "TIER: promotion to trustee or controller requires a vesting deed, "
                  "trustee deed, certification or memorandum of trust, recorded "
                  "successor-trustee instrument, probate record, or an independent registry "
                  "officer entry.")
    elif len(residual) >= 2:
        tier, disposition = "LEAD", "TRUST-NEEDS-DEED"
        reason = ("{} residual tokens after stripping trust keywords, but no token pair met "
                  "the lexicon support threshold of {}. trust (named trustee) is a search "
                  "lead only.".format(len(residual), min_support))
    else:
        tier, disposition = "NONE", "TRUST-NEEDS-DEED"
        reason = ("trust (private): fewer than 2 residual tokens after stripping trust "
                  "keywords. No registry lists trustees; the trustee is on the deed, and "
                  "there is no deed-pull implementation in this build.")

    out = {"tier": tier, "people": people, "residual_tokens": residual,
           "reason": reason, "disposition": disposition,
           "lexicon_provenance": meta.get("support_semantics", "unknown"),
           "min_support": min_support}
    if eponymous:
        out["eponymous_surname_lead"] = eponymous
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="free_pierce.py",
        description="Stage 3: $0 name parse against the frozen lexicon. Output tier is "
                    "LEAD, always. Spends nothing.")
    ap.add_argument("--owner", help="a single owner string")
    ap.add_argument("--in", dest="infile", help="CENSUS.json")
    ap.add_argument("--out-dir", help="RUN_DIR")
    ap.add_argument("--lexicon", help="override references/name_lexicon.json")
    ap.add_argument("--min-support", type=int)
    ap.add_argument("--augment-from-list", action="store_true",
                    help="BATCH MODE ONLY: augment the frozen lexicon from this run's owner "
                         "list. Never use in single-property mode — a one-row dataset gives "
                         "every token support 0 and the $0 leg silently vanishes.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    lex = load_lexicon(args.lexicon)
    if lex.get("_meta", {}).get("support_semantics") == "bootstrap_rank":
        print("NOTE lexicon is BOOTSTRAP (ranks seeded from common US name frequency, not "
              "counts from Mitch's owner corpus). Rebuild with build_lexicon.py --in "
              "MASTER_OWNERS.csv before relying on support thresholds for anything but "
              "lead generation.", file=sys.stderr)

    if args.owner:
        res = parse_people(args.owner, lex, args.min_support)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print("owner        {!r}".format(args.owner))
            print("tier         {}".format(res["tier"]))
            print("disposition  {}".format(res["disposition"]))
            for p in res["people"]:
                print("person       {} {}   ({})".format(p["first"].title(),
                                                         p["last"].title(), p["basis"]))
            if res.get("eponymous_surname_lead"):
                e = res["eponymous_surname_lead"]
                print("eponymous    {} — {}".format(e["surname"], e["note"]))
            if not res["people"]:
                print("person       (none)")
            print("reason       {}".format(res["reason"]))
        return 0

    if not args.infile:
        ap.error("one of --owner or --in is required")

    doc = json.loads(pathlib.Path(args.infile).read_text(encoding="utf-8"))
    rows = doc.get("rows", [])

    if args.augment_from_list:
        added = 0
        for r in rows:
            if octlib.is_company(r.get("owner_of_record") or ""):
                continue
            toks = octlib.norm_owner(r.get("owner_of_record") or "")["spaced"].split()
            if len(toks) >= 2 and toks[0].isalpha():
                lex["LAST"][toks[0]] = lex["LAST"].get(toks[0], 0) + 1
                added += 1
                for t in toks[1:]:
                    if t.isalpha() and t not in STOP:
                        lex["FIRST"][t] = lex["FIRST"].get(t, 0) + 1
        lex["_meta"]["support_semantics"] = "mixed"
        print("augmented lexicon from {} list rows (support_semantics -> mixed)".format(added))

    n_lead = 0
    for r in rows:
        if r.get("owner_class") not in ("trust", "entity", None):
            continue
        res = parse_people(r.get("owner_of_record") or "", lex, args.min_support)
        r["free_pierce"] = res
        if res["people"]:
            n_lead += 1
        if res["disposition"] == "TRUST-NEEDS-DEED" and r.get("owner_class") == "trust":
            r["coverage_disposition"] = "TRUST-NEEDS-DEED"

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else pathlib.Path(args.infile).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "CENSUS.json", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    entity_rows = [r for r in rows if r.get("owner_class") == "entity"]
    blocked = [r for r in entity_rows
               if (r.get("free_pierce") or {}).get("disposition") == "NOT-A-PERSON-STRING"]
    n_entity_people = sum(
        1 for r in entity_rows if (r.get("free_pierce") or {}).get("people"))
    n_eponymous = sum(
        1 for r in rows if (r.get("free_pierce") or {}).get("eponymous_surname_lead"))
    print("free_pierce: {} row(s) produced a LEAD-tier person".format(n_lead))
    # State this explicitly or the coverage report looks broken: an entity yielding zero
    # people is the guard working, not the stage failing.
    print("entity free-pierce: {} by design (is_company guard blocked {} of {} entity rows)"
          .format(n_entity_people, len(blocked), len(entity_rows)))
    print("eponymous surname leads: {} (search terms, never conclusions)".format(n_eponymous))
    print("wrote {}".format(out_dir / "CENSUS.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
