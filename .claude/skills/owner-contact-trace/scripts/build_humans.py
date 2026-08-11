#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_humans.py — stage 6: rank candidates for REVIEW, never for acceptance.

Scoring:  base 5  ·  +100 if the filed address addr_key equals the parcel mailing addr_key
          ·  +20 if the title is in CONTROL_TITLES
          ·  a non-commercial PERSON registered agent scores 90 anchored / 10 not

A person RA is NOT presumptively better than a commercial one. It is a lead, and its
promotion still requires a control-bearing edge. Commercial agents are excluded from ranking
entirely -- recorded, never contacted.

The score orders review. It never converts an unsupported role into a controller, and every
competing manager or member is preserved rather than collapsed into a winner.

Always emits `unresolved_frontier`.

Usage:
    build_humans.py --entity-ledger ENTITY_LEDGER.json --census CENSUS.json --out-dir RUN_DIR
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402
import anchor_gate  # noqa: E402

BASE, ANCHOR_BONUS, CONTROL_BONUS = 5, 100, 20
PERSON_RA_ANCHORED, PERSON_RA_UNANCHORED = 90, 10
KEEP_TOP = 3


def score(candidate, parcel_addr_key, principal_addr_keys=()):
    anchored, basis = False, octlib.UNKNOWN
    key = octlib.addr_key(candidate.get("addr") or "", candidate.get("city") or "",
                          candidate.get("state") or "", candidate.get("zip") or "")
    if key and parcel_addr_key and key == parcel_addr_key:
        anchored, basis = True, "parcel mailing address"
    elif key and key in set(principal_addr_keys):
        anchored, basis = True, "Sunbiz-filed address of the principal"

    title = (candidate.get("title") or "").upper()
    has_control_title = title in octlib.CONTROL_TITLES
    is_ra = candidate.get("edge_type") == "registered-agent"

    if is_ra:
        pts = PERSON_RA_ANCHORED if anchored else PERSON_RA_UNANCHORED
        parts = ["person RA {}".format("anchored" if anchored else "unanchored")]
    else:
        pts = BASE
        parts = ["base {}".format(BASE)]
        if anchored:
            pts += ANCHOR_BONUS
            parts.append("anchor +{}".format(ANCHOR_BONUS))
        if has_control_title:
            pts += CONTROL_BONUS
            parts.append("control title {} +{}".format(title, CONTROL_BONUS))

    return {"score": pts, "score_basis": " · ".join(parts),
            "anchored": octlib.tri(anchored), "anchor_basis": basis,
            "has_control_title": has_control_title, "addr_key": key}


def build(entity_ledger, census_row):
    parcel_key = census_row.get("addr_key") or ""
    humans_in = []
    frontier = []
    principal_keys = set()

    for ent in entity_ledger.get("entities", []):
        frontier += [f.get("name") if isinstance(f, dict) else f
                     for f in (ent.get("unresolved_frontier") or [])]
        for h in ent.get("humans", []):
            humans_in.append(h)
            k = octlib.addr_key(h.get("addr") or "", h.get("city") or "",
                                h.get("state") or "", h.get("zip") or "")
            if k:
                principal_keys.add(k)

    for h in (census_row.get("free_pierce") or {}).get("people", []):
        humans_in.append({"name": "{} {}".format(h.get("first", ""), h.get("last", "")).strip(),
                          "edge_type": "unknown", "control_bearing": False,
                          "tier": "LEAD", "basis": h.get("basis")})

    candidates, excluded = [], []
    for h in humans_in:
        if octlib.is_commercial_agent(h.get("name") or ""):
            excluded.append({"name": h.get("name"), "reason":
                             "commercial registered agent — recorded and skipped, never "
                             "contacted. 57% of FL registered agents are commercial dead "
                             "ends before you spend anything."})
            continue
        c = dict(h)
        c.update(score(h, parcel_key, principal_keys))
        c["registry_officer_named"] = h.get("edge_type") not in (None, "unknown")
        c["edge_source_is_government_record"] = bool(h.get("doc"))
        c["edges"] = [{"edge_type": h.get("edge_type") or "unknown",
                       "source": "registry doc {}".format(h.get("doc") or "?"),
                       "dated": entity_ledger.get("cordata_vintage") or octlib.UNKNOWN}]
        status, why = anchor_gate.role_status(c)
        c["role_status"], c["role_reason"] = status, why
        candidates.append(c)

    ranked, ambiguous, why = anchor_gate.ambiguity_gate(candidates)
    kept = ranked[:KEEP_TOP]
    if ambiguous and len(ranked) >= 2:
        kept = ranked[:max(2, KEEP_TOP)]

    return {"run_id": entity_ledger.get("run_id", ""),
            "retrieved_at": octlib.utcnow_iso(),
            "parcel_addr_key": parcel_key,
            "candidates": kept,
            "excluded_commercial_agents": excluded,
            "ambiguity": ambiguous, "ambiguity_reason": why,
            "unresolved_frontier": sorted(set(x for x in frontier if x)),
            "note": ("Ranking orders REVIEW. It never converts an unsupported role into a "
                     "controller, and it never accepts. Competing managers and members are "
                     "preserved, not collapsed.")}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_humans.py",
        description="Stage 6: rank candidate humans for review. Free; spends nothing.")
    ap.add_argument("--entity-ledger", required=True)
    ap.add_argument("--census", help="CENSUS.json (for the parcel addr_key and free-pierce "
                                     "leads)")
    ap.add_argument("--apn", help="which census row to build against")
    ap.add_argument("--out-dir")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ledger = json.loads(pathlib.Path(args.entity_ledger).read_text(encoding="utf-8"))
    row = {}
    if args.census:
        cdoc = json.loads(pathlib.Path(args.census).read_text(encoding="utf-8"))
        rows = cdoc.get("rows", [])
        if args.apn:
            want = octlib.napn(args.apn)
            rows = [r for r in rows if r.get("apn_norm") == want] or rows
        row = rows[0] if rows else {}

    doc = build(ledger, row)
    if args.out_dir:
        d = pathlib.Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "HUMANS.json", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print("wrote {}".format(d / "HUMANS.json"))

    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0

    print("parcel addr_key  {}".format(doc["parcel_addr_key"] or "(none)"))
    for c in doc["candidates"]:
        print("  rank {} {:24} {:6} {:22} anchored={} — {}".format(
            c.get("rank"), (c.get("name") or "")[:24], c.get("score"),
            c.get("role_status"), c.get("anchored"), c.get("score_basis")))
    for e in doc["excluded_commercial_agents"]:
        print("  excluded {:22} {}".format((e["name"] or "")[:22], e["reason"]))
    if doc["ambiguity"]:
        print("  AMBIGUOUS: {}".format(doc["ambiguity_reason"]))
    print("  UNRESOLVED FRONTIER: {}".format(doc["unresolved_frontier"] or "(none)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
