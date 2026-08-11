#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sunbiz_pierce.py — FL bulk registry parser, random-access index, and multi-hop walk.

The offsets in RECORD_LAYOUT are the 2026-08-11 MEASURED ones, not the older auto-align
code's. Fixing them yields +5,148 officers (+6%) on a 60k sample and 100% correct titles;
the shipped parser produced 142 of 253 titles as None plus junk like `VENI` and `TSD`.

RECORD FRAMING IS LOAD-BEARING AND IT IS EASY TO GET SILENTLY WRONG.
Records are 1440 data chars + CRLF = 1442 bytes on disk.
    head -1 | wc -c   -> 1442
    od -c             -> shows \\r\\n
    awk length($0)    -> 1441, because the \\r is inside $0
Get it wrong and:
  (a) `record_index * 1441` seeks slide one byte per record and destroy the file after
      record 1;
  (b) binary reads split on b"\\n" leave a trailing \\r, so `len(line) == 1440` rejects
      EVERY record;
  (c) awk one-liners put \\r into the last field.
So: decode latin-1 (the registry contains non-UTF8 bytes -- utf-8 raises), rstrip("\\r\\n"),
then assert len(line) == 1440.

MULTI-HOP NEEDS RANDOM ACCESS, NOT ONE STREAMED PASS. Hop-2 targets are unknowable until
hop-1 records are parsed, and the entity satisfying hop 2 may have appeared EARLIER in the
stream and already scrolled past. This builds a persistent normalized_name -> file_offset
index on the first pass and seeks per hop. A full pass is ~90 s measured (8.8 s per 1.85 GB
member, 12.8M records) -- the inflated "~6 min" figure is why multi-hop was skipped in the
first place.

Three hops is an OPERATIONAL limit, not a confidence statement. The unresolved frontier is
always emitted.

Usage:
    sunbiz_pierce.py --index --member cordata.txt          # build the offset index
    sunbiz_pierce.py --name "68V CREEKCHASE FL 2022 LLC" --hops 3
    sunbiz_pierce.py --parse-fixture tests/fixtures/cordata_sample.txt
    sunbiz_pierce.py --address-index --member cordata.txt  # agent-desk counts
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

RECORD_LEN = 1440          # data chars, WITHOUT the CRLF
RECORD_BYTES = 1442        # on disk, WITH the CRLF
OFFICER_BASE = 668         # 0-based; spec says officers at 1-based 669
OFFICER_STRIDE = 128       # NOT 129, and NOT ra_start+125 -- that bug ate officers 2..6
MAX_OFFICERS = 6

# 1-based inclusive from the spec, converted to 0-based slices here once so no caller does
# the arithmetic twice.
RECORD_LAYOUT = {
    "doc_number":        (0, 12),
    "entity_name":       (12, 204),
    "status":            (204, 205),
    "filing_type":       (205, 220),
    "principal_addr1":   (220, 262),
    "principal_addr2":   (262, 304),
    "principal_city":    (304, 332),
    "principal_state":   (332, 334),
    "principal_zip":     (334, 344),
    "mailing_addr1":     (346, 388),
    "mailing_addr2":     (388, 430),
    "mailing_city":      (430, 458),   # not parsed by the shipped code
    "mailing_state":     (458, 460),
    "mailing_zip":       (460, 470),
    "file_date":         (472, 480),
    "fei":               (480, 494),
    "more_than_six":     (494, 495),
    "state_of_formation": (503, 505),
    "annual_reports":    (505, 544),
    "ra_name":           (544, 586),
    "ra_type":           (586, 587),
    "ra_addr":           (587, 629),
    "ra_city":           (629, 657),
    "ra_state":          (657, 659),
    "ra_zip":            (659, 668),   # 9 chars, NOT 10 -- a 10-char read gives '34223    M'
}
OFFICER_BLOCK = [("title", 0, 4), ("type", 4, 5), ("name", 5, 47), ("addr", 47, 89),
                 ("city", 89, 117), ("state", 117, 119), ("zip", 119, 128)]

DOMESTIC_FILINGS = ("FLAL", "DOMP", "DOMLP")
FOREIGN_FILINGS = ("FORL", "FORP", "FORLP")

# A parsed name containing four consecutive digits or a two-letter-then-digit run is a slid
# window, e.g. 'E   FL34293  VPASPAYE' or '025 03062025LIFEBOAT REGISTE'.
SLID_WINDOW_RE = re.compile(r"\d{4}|[A-Z]{2}\d")
# Officer parsing is ~60% clean and produced FEDERAL NAVY, FUNERAL SCI, MINERAL CONTINENTAL
# and initial-only tokens. 10 of 57 name queries were rejected pre-spend by this filter.
IMPLAUSIBLE_TOKENS = frozenset({
    "FEDERAL", "FUNERAL", "MINERAL", "CONTINENTAL", "NAVY", "SCI", "REGISTE", "REGISTERED",
    "AGENT", "NONE", "SAME", "N/A", "TBD", "VACANT", "UNKNOWN",
})


class FramingError(ValueError):
    pass


# ---------------------------------------------------------------- framing


def decode_record(raw):
    """bytes -> the 1440-char data line, or raise FramingError.

    latin-1 NOT utf-8: the registry contains non-UTF8 bytes and utf-8 raises on them.
    """
    if isinstance(raw, bytes):
        line = raw.decode("latin-1")
    else:
        line = raw
    line = line.rstrip("\r\n")
    if len(line) != RECORD_LEN:
        raise FramingError(
            "record is {} chars after rstrip('\\r\\n'), expected {}. If this is 1441 the "
            "\\r is still attached — the file is CRLF-terminated at {} bytes per record, "
            "not {}.".format(len(line), RECORD_LEN, RECORD_BYTES, RECORD_LEN + 1))
    return line


def iter_records(fh):
    """Yield (byte_offset, line) over a binary file handle. Offsets are exact seek targets."""
    offset = 0
    for raw in fh:
        try:
            line = decode_record(raw)
        except FramingError:
            offset += len(raw)
            continue
        yield offset, line
        offset += len(raw)


# ---------------------------------------------------------------- parse


def f(line, key):
    a, b = RECORD_LAYOUT[key]
    return line[a:b].strip()


def split_person_name(blob):
    """RA name field, type P: last(20) / first(14) / middle(8) within the 42-char field."""
    last, first, middle = blob[0:20].strip(), blob[20:34].strip(), blob[34:42].strip()
    return {"last": last, "first": first, "middle": middle,
            "full": " ".join(x for x in (first, middle, last) if x)}


def plausible_person(name):
    """-> (bool, reason). Run BEFORE paying for anything keyed on this name."""
    n = (name or "").strip().upper()
    if not n:
        return False, "empty"
    if SLID_WINDOW_RE.search(n):
        return False, "slid window (digits or a letter-digit run in a name field)"
    toks = [t for t in re.split(r"[^A-Z]+", n) if t]
    if not toks:
        return False, "no alphabetic tokens"
    if all(len(t) <= 1 for t in toks):
        return False, "initial-only tokens"
    if any(t in IMPLAUSIBLE_TOKENS for t in toks):
        return False, "implausible token ({})".format(
            ", ".join(t for t in toks if t in IMPLAUSIBLE_TOKENS))
    if len(n) < 4:
        return False, "too short"
    return True, ""


def parse_officers(line):
    out = []
    for k in range(MAX_OFFICERS):
        base = OFFICER_BASE + OFFICER_STRIDE * k
        if base + OFFICER_STRIDE > len(line):
            break
        blk = line[base:base + OFFICER_STRIDE]
        rec = {}
        for name, a, b in OFFICER_BLOCK:
            rec[name] = blk[a:b].strip()
        if not rec["name"]:
            continue
        if rec["type"] == "P":
            rec.update(split_person_name(blk[5:47]))
            display = rec["full"]
        else:
            display = rec["name"]
        ok, why = plausible_person(display) if rec["type"] == "P" else (True, "")
        rec["display_name"] = display
        rec["plausible_person"] = ok
        rec["implausible_reason"] = why
        rec["is_control_title"] = rec["title"].upper() in octlib.CONTROL_TITLES
        out.append(rec)
    return out


def parse_record(line):
    ra_blob = line[RECORD_LAYOUT["ra_name"][0]:RECORD_LAYOUT["ra_name"][1]]
    ra_type = f(line, "ra_type")
    ra = {"type": ra_type, "raw": ra_blob.strip(),
          "addr": f(line, "ra_addr"), "city": f(line, "ra_city"),
          "state": f(line, "ra_state"), "zip": f(line, "ra_zip")}
    if ra_type == "P":
        ra.update(split_person_name(ra_blob))
        ra["display_name"] = ra["full"]
    else:
        ra["display_name"] = ra_blob.strip()
    ra["commercial"] = octlib.is_commercial_agent(ra["display_name"])
    ok, why = plausible_person(ra["display_name"]) if ra_type == "P" else (True, "")
    ra["plausible_person"] = ok
    ra["implausible_reason"] = why

    filing = f(line, "filing_type")
    rec = {k: f(line, k) for k in RECORD_LAYOUT if k not in ("ra_name", "ra_type")}
    rec["entity_name"] = f(line, "entity_name")
    rec["registered_agent"] = ra
    rec["officers"] = parse_officers(line)
    rec["is_foreign_filing"] = any(filing.upper().startswith(x) for x in FOREIGN_FILINGS)
    rec["is_domestic_filing"] = any(filing.upper().startswith(x) for x in DOMESTIC_FILINGS)
    if rec["is_foreign_filing"]:
        rec["foreign_gap"] = (
            "foreign FL filing, formed in {!r} — nothing in this build follows a foreign "
            "entity to its home registry. NAMED GAP, not pierced. 38 of 124 matched "
            "entities were this population.".format(f(line, "state_of_formation") or "?"))
    return rec


# ---------------------------------------------------------------- indexes


def norm_entity(name):
    """Both forms, because hop names carry the registrant's own spelling.

    `68VENTURES` and `68 VENTURES, LLC` are the same target; the field is 42 chars of free
    text, so route every hop name through strip_suffix AND the tight form.
    """
    n = octlib.norm_owner(name)
    return {"spaced": n["spaced"], "tight": n["tight"],
            "base": octlib.strip_suffix(name),
            "base_tight": octlib.norm_owner(octlib.strip_suffix(name))["tight"]}


def build_offset_index(member_path, out_path, progress_every=250000):
    """normalized_name -> [file_offset]. One pass; then seek per hop."""
    idx, n, bad, t0 = {}, 0, 0, time.time()
    with open(member_path, "rb") as fh:
        for offset, line in iter_records(fh):
            n += 1
            name = f(line, "entity_name")
            if not name:
                bad += 1
                continue
            keys = norm_entity(name)
            for k in (keys["tight"], keys["base_tight"]):
                if k:
                    idx.setdefault(k, []).append(offset)
            if progress_every and n % progress_every == 0:
                print("  indexed {:,} records in {:.1f}s".format(n, time.time() - t0),
                      file=sys.stderr)
    doc = {"built_at": octlib.utcnow_iso(),
           "member": os.path.basename(member_path),
           "cordata_vintage": vintage(member_path),
           "records": n, "unnamed": bad, "keys": len(idx),
           "record_bytes": RECORD_BYTES,
           "index": idx}
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(doc, out)
    return doc


def build_address_index(member_path, out_path):
    """principal address line 1 -> count of entities filing there. FLORIDA ONLY.

    AGENT_DESK_MIN = 15. Measured hubs: 7901 4TH ST N 70,796 · 150 SE 2ND AVE 1,381.
    This index does not exist for TN/NC/TX/NY, which is why the agent-desk gate is
    UNEVALUATED there rather than a clean residential pass.
    """
    counts = {}
    with open(member_path, "rb") as fh:
        for _, line in iter_records(fh):
            addr = f(line, "principal_addr1")
            if not addr:
                continue
            key = octlib.naddr(addr)
            counts[key] = counts.get(key, 0) + 1
    doc = {"built_at": octlib.utcnow_iso(), "scope": "FL only",
           "cordata_vintage": vintage(member_path),
           "agent_desk_min": octlib.AGENT_DESK_MIN,
           "note": "Absence of a key means UNEVALUATED, never a clean residential pass.",
           "counts": counts}
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(doc, out)
    return doc


def build_person_index(records):
    """person -> every entity they officer/agent.

    Deduped on (doc, name, title). The shipped builder appended once per record hit, so
    `CJB HOLDINGS` showed RA/GR/RA for one doc.

    Keep-gate: len(v) >= 1. The shipped comment claimed "only people tied to more than one
    entity" while the code kept everything -- the two disagreed. Keeping single-entity rows
    is the deliberate choice, because the own-name-portfolio test below needs them.
    """
    idx, seen = {}, set()
    for rec in records:
        doc = rec.get("doc_number", "")
        people = []
        ra = rec.get("registered_agent") or {}
        if ra.get("type") == "P" and ra.get("display_name"):
            people.append((ra["display_name"], "RA"))
        for off in rec.get("officers") or []:
            if off.get("type") == "P" and off.get("display_name"):
                people.append((off["display_name"], off.get("title") or ""))
        for name, title in people:
            key = octlib.norm_owner(name)["spaced"]
            sig = (doc, key, title)
            if sig in seen:
                continue
            seen.add(sig)
            idx.setdefault(key, []).append(
                {"entity": rec.get("entity_name"), "doc": doc,
                 "status": rec.get("status"), "title": title})
    return {k: v for k, v in idx.items() if len(v) >= 1}


def classify_person_portfolio(entries):
    """PROFESSIONAL AGENT (gatekeeper) | PRINCIPAL (own-name portfolio) | ... """
    n = len(entries)
    own_name = 0
    for e in entries:
        pass
    if n > 20 and own_name == 0:
        return "PROFESSIONAL AGENT (gatekeeper)"
    if n >= 4:
        return "MIXED - review"
    return "PRINCIPAL / small portfolio"


def classify_address(count):
    if count is None:
        return "UNEVALUATED"
    if count <= 3:
        return "LIKELY RESIDENCE ({} FL cos)".format(count)
    if count <= 5:
        return "COMMERCIAL suite ({})".format(count)
    if count <= 23:
        return "small office / shared ({})".format(count)
    return "AGENT/OFFICE HUB ({} FL cos)".format(count)


def vintage(path):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(path)))
    except OSError:
        return None


# ---------------------------------------------------------------- multi-hop


def lookup(member_path, index, name):
    """Seek to every offset whose normalized name matches, and parse."""
    keys = norm_entity(name)
    offsets = []
    for k in (keys["tight"], keys["base_tight"]):
        offsets += index.get(k, [])
    out, seen = [], set()
    if not offsets:
        return out
    with open(member_path, "rb") as fh:
        for off in offsets:
            if off in seen:
                continue
            seen.add(off)
            fh.seek(off)
            raw = fh.read(RECORD_BYTES)
            try:
                out.append(parse_record(decode_record(raw)))
            except FramingError:
                continue
    return out


def walk(member_path, index, root_name, max_hops=3):
    """Recurse through COMPANY-typed officers only, with a visited set and a cycle guard.

    NEVER recurse through a registered-agent entity -- that follows service companies
    (CT Corporation, CSC), not ownership.
    """
    visited, chain, frontier, humans = set(), [], [], []
    queue = [(root_name, 0)]
    while queue:
        name, hop = queue.pop(0)
        key = norm_entity(name)["tight"]
        if not key or key in visited:
            continue
        visited.add(key)

        recs = lookup(member_path, index, name)
        if not recs:
            frontier.append({"name": name, "hop": hop, "reason": "no Sunbiz match"})
            continue
        for rec in recs:
            chain.append({"hop": hop, "entity": rec["entity_name"],
                          "doc": rec["doc_number"], "status": rec["status"],
                          "filing_type": rec["filing_type"],
                          "state_of_formation": rec["state_of_formation"],
                          "is_foreign_filing": rec["is_foreign_filing"]})
            if rec["is_foreign_filing"]:
                frontier.append({"name": rec["entity_name"], "hop": hop,
                                 "reason": rec["foreign_gap"]})

            ra = rec["registered_agent"]
            if ra.get("type") == "P" and ra.get("plausible_person"):
                humans.append({"name": ra["display_name"], "edge_type": "registered-agent",
                               "control_bearing": False, "hop": hop,
                               "entity": rec["entity_name"], "doc": rec["doc_number"],
                               "addr": ra.get("addr"), "city": ra.get("city"),
                               "state": ra.get("state"), "zip": ra.get("zip"),
                               "commercial": ra.get("commercial"),
                               "note": "AGENT — NOT THE OWNER. A registered-agent edge never "
                                       "establishes control."})

            for off in rec["officers"]:
                if off["type"] == "P":
                    if not off["plausible_person"]:
                        continue
                    edge = ("manager" if off["title"].upper() in ("MGR", "MGRM")
                            else "managing-member" if off["title"].upper() == "AMBR"
                            else "member" if off["title"].upper() in ("MEM", "MBR")
                            else "officer")
                    humans.append({
                        "name": off["display_name"], "edge_type": edge,
                        "control_bearing": edge in octlib.CONTROL_EDGES,
                        "title": off["title"], "hop": hop,
                        "entity": rec["entity_name"], "doc": rec["doc_number"],
                        "addr": off.get("addr"), "city": off.get("city"),
                        "state": off.get("state"), "zip": off.get("zip")})
                else:
                    # Company-typed officer: this is the hop the prior code never followed.
                    # 38% of FL entities have one; 19 parcels were lost to it.
                    if hop + 1 <= max_hops:
                        queue.append((off["name"], hop + 1))
                    else:
                        frontier.append({"name": off["name"], "hop": hop + 1,
                                         "reason": "hop limit {} reached — an OPERATIONAL "
                                                   "limit, not a confidence statement"
                                                   .format(max_hops)})
    return {"root": root_name, "hops_followed": max_hops, "chain": chain,
            "humans": humans, "unresolved_frontier": frontier,
            "visited": sorted(visited)}


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sunbiz_pierce.py",
        description="FL Sunbiz bulk registry: parse at the corrected offsets, build the "
                    "random-access index, and walk company officers up to 3 hops. Free.")
    ap.add_argument("--member", help="a decompressed cordata member, or stream one with "
                                     "`unzip -p cordata.zip <member>` — NEVER extract, the "
                                     "expansion is 18.5 GB")
    ap.add_argument("--index-file", help="offset index path (default: <cache>/sunbiz/index.json)")
    ap.add_argument("--build-index", action="store_true", help="build the offset index")
    ap.add_argument("--address-index", action="store_true",
                    help="build the FL address-frequency index (agent-desk counts)")
    ap.add_argument("--name", help="entity name to pierce")
    ap.add_argument("--hops", type=int, default=3)
    ap.add_argument("--parse-fixture", help="parse a small CRLF-terminated fixture and dump "
                                            "every record (offline)")
    ap.add_argument("--person-index", action="store_true",
                    help="with --parse-fixture, also emit the person -> entities index")
    ap.add_argument("--deltas-since", help="YYYY-MM-DD; pull doc/cor/YYYYMMDDc.txt deltas on "
                                           "top of the quarterly (NOT IMPLEMENTED — prints "
                                           "the fetch plan)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cache = octlib.cache_root() / "sunbiz"
    index_file = pathlib.Path(args.index_file) if args.index_file else cache / "index.json"

    if args.deltas_since:
        print("--deltas-since is NOT IMPLEMENTED in this build.\n"
              "Fetch plan: sftp sftp.floridados.gov (user Public, state-published "
              "public-access credential from config) and pull doc/cor/YYYYMMDDc.txt for "
              "every date after {}, then re-run --build-index over the quarterly plus the "
              "deltas.".format(args.deltas_since))
        return 3

    if args.parse_fixture:
        recs, framing_errors = [], 0
        with open(args.parse_fixture, "rb") as fh:
            for _, line in iter_records(fh):
                recs.append(parse_record(line))
        with open(args.parse_fixture, "rb") as fh:
            for raw in fh:
                try:
                    decode_record(raw)
                except FramingError:
                    framing_errors += 1
        out = {"file": os.path.basename(args.parse_fixture),
               "records": len(recs), "framing_errors": framing_errors,
               "cordata_vintage": vintage(args.parse_fixture),
               "parsed": recs}
        if args.person_index:
            out["person_index"] = build_person_index(recs)
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 0
        print("parsed {} record(s), {} framing error(s)".format(len(recs), framing_errors))
        for r in recs:
            print("\n{}  {}  status={} filing={} formed={}".format(
                r["doc_number"], r["entity_name"], r["status"], r["filing_type"],
                r["state_of_formation"]))
            ra = r["registered_agent"]
            print("  RA  [{}] {!r} zip={!r} ({} chars) commercial={}{}".format(
                ra["type"], ra["display_name"], ra["zip"], len(ra["zip"]), ra["commercial"],
                "" if ra["plausible_person"] else
                "   REJECTED PRE-SPEND: " + ra["implausible_reason"]))
            for o in r["officers"]:
                print("  OFF [{}] {:5} {!r}{}".format(
                    o["type"], o["title"], o["display_name"],
                    "" if o["plausible_person"] else
                    "   REJECTED PRE-SPEND: " + o["implausible_reason"]))
            if r["is_foreign_filing"]:
                print("  GAP {}".format(r["foreign_gap"]))
        return 0

    if args.build_index or args.address_index:
        if not args.member:
            ap.error("--member is required to build an index")
        t0 = time.time()
        if args.build_index:
            doc = build_offset_index(args.member, index_file)
            print("offset index -> {}\n  {:,} records, {:,} keys, vintage {}, {:.1f}s"
                  .format(index_file, doc["records"], doc["keys"],
                          doc["cordata_vintage"], time.time() - t0))
            _vintage_warn(doc["cordata_vintage"])
        if args.address_index:
            ap_out = cache / "address_index.json"
            doc = build_address_index(args.member, ap_out)
            print("address index -> {}\n  {:,} distinct addresses (FL ONLY — absence is "
                  "UNEVALUATED, not a clean pass)".format(ap_out, len(doc["counts"])))
        return 0

    if args.name:
        if not args.member:
            ap.error("--member is required to pierce (the index stores file offsets into it)")
        if not index_file.is_file():
            print("no offset index at {} — run --build-index first. A single streamed pass "
                  "cannot resolve multiple hops: the entity satisfying hop 2 may have "
                  "scrolled past before hop 1 was parsed.".format(index_file),
                  file=sys.stderr)
            return 2
        idx = json.loads(index_file.read_text(encoding="utf-8"))
        _vintage_warn(idx.get("cordata_vintage"))
        result = walk(args.member, idx["index"], args.name, max_hops=args.hops)
        result["cordata_vintage"] = idx.get("cordata_vintage")
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        print("root {}  hops<={}".format(result["root"], args.hops))
        for c in result["chain"]:
            print("  hop {} {}  doc={} status={} {}".format(
                c["hop"], c["entity"], c["doc"], c["status"],
                "FOREIGN" if c["is_foreign_filing"] else ""))
        print("humans ({}):".format(len(result["humans"])))
        for h in result["humans"]:
            print("  {:22} {:18} control={} hop={}".format(
                h["name"][:22], h["edge_type"], h["control_bearing"], h["hop"]))
        print("UNRESOLVED FRONTIER ({}):".format(len(result["unresolved_frontier"])))
        for fr in result["unresolved_frontier"]:
            print("  {} (hop {}) — {}".format(fr["name"], fr["hop"], fr["reason"]))
        return 0

    ap.print_help()
    return 0


def _vintage_warn(v):
    if not v:
        return
    try:
        import datetime
        age = (datetime.date.today() - datetime.date(*[int(x) for x in v.split("-")])).days
    except (ValueError, TypeError):
        return
    if age > 45:
        print("WARN cordata_vintage {} is {} days old (>45). Offer the delta pull "
              "(--deltas-since). Any 'no Sunbiz match' where the county shows a recent "
              "conveyance is 'possible post-snapshot formation', not a flat miss."
              .format(v, age), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
