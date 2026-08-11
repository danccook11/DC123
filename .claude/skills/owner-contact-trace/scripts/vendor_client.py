#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor_client.py — cached, ledgered, budgeted vendor client.

THE BUDGET GATE, which replaces asking per job:
  * `--budget <USD>` is required (default 25).
  * Before the first paid call in EVERY mode the run prints a WORST-CASE table -- per axis,
    per actor, with `max_results` shown -- and requires `--i-approve <USD>` equal to
    `--budget`.
  * Thereafter the cap is enforced by raising `BudgetExhausted`, NEVER by silent truncation,
    against the append-only ledger.

Estimate formula:  persons x max_results x p_name  +  expected_phones x p_reverse
Unit prices are read from the capability manifest WITH THE ACCOUNT TIER ATTACHED. one-api is
$0.007 at BRONZE and $0.02 on FREE -- a 2.9x swing. A price without a tier is not a price.

TRACERFY IS METERED IN CREDITS, NOT DOLLARS, so it gets a SECOND counter: 5 credits per
trace_lookup/parcel_lookup HIT (misses free, so the estimate is a ceiling), 1 per dnc_check.
The dollar value of a credit is NOT DOCUMENTED anywhere in our records; this module reports
credits and refuses to fabricate a dollar figure.

What this client will not do:
  * It will not ask a vendor who owns a parcel. `person_axis()` requires first+last+address.
    `parcel_axis()` exists but is CORROBORATION ONLY and its result is discarded unless the
    returned mailing address anchors.
  * It will not let dataset items enter context. Apify results are streamed to RUN_DIR
    (`.tmp` then `mv` on HTTP 200 only); a Placecraft list call once returned 168,571 chars.
  * It will not hard-code an input separator. The comma-vs-semicolon question is PROBED with
    a known-answer name at max_results:1 and the winner is logged with a date.

Usage:
    vendor_client.py --estimate --persons 200 --axis apivault_name --budget 25
    vendor_client.py --estimate --persons 200 --axis apivault_name --budget 25 --i-approve 25
    vendor_client.py --ledger-summary
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

LEDGER_HEADER = ["ts", "endpoint", "sent", "billable"]

# Seeds only. Runtime routing reads the capability manifest, never this table -- see
# references/source_ledger.md. A price with no tier is not usable for an estimate.
PRICE_SEED = {
    "one_api_address": {"usd_per_result": {"BRONZE": 0.007, "FREE": 0.02},
                        "default_max_results": 1, "recommended_max_results": 4,
                        "note": "REQUIRES ZIP. Name axis is broken -- address axis only. "
                                "max_results defaults to 1; the household/relative graph "
                                "depends on it being 4."},
    "one_api_reverse_phone": {"usd_per_result": {"BRONZE": 0.007, "FREE": 0.02},
                              "default_max_results": 1, "recommended_max_results": 1,
                              "note": "A SECOND BILLED CALL PER PHONE. It must appear in the "
                                      "estimate."},
    "apivault_name": {"usd_per_result": {"ANY": 0.0065}, "usd_start": 0.00005,
                      "default_max_results": 100, "recommended_max_results": 3,
                      "note": "BILLING IS PER DELIVERED MATCH and max_results DEFAULTS TO "
                              "100. One common surname = up to $0.65 on a single name. Set "
                              "it explicitly: 3 batch, 5 single."},
    "batchdata_address": {"usd_per_result": {"ANY": None},
                          "default_max_results": 1, "recommended_max_results": 1,
                          "note": "Pay-per-match; validation errors and no-match rows never "
                                  "bill. Price per match is not recorded in our files -- "
                                  "read it from the account before estimating. ADDRESS MODE "
                                  "ONLY: APN mode scored 0/4 on Knox."},
    "sherpa_person": {"usd_per_result": {"PAYG": 0.15, "TIER_1000": 0.10,
                                         "TIER_12500": 0.08},
                      "default_max_results": 1, "recommended_max_results": 1,
                      "note": "BLOCKED as of 2026-08-11. Hard cap 25 lookups/request; a "
                              "batch exceeding remaining quota is rejected WHOLE with 429, "
                              "unbilled. Batch at 10."},
}

TRACERFY_CREDITS = {"trace_lookup": 5, "parcel_lookup": 5, "dnc_check": 1,
                    "check_balance": 0, "list_strategies": 0}

DO_NOT_USE = {
    "sian_agency_property_skip_tracing":
        "$0.01 + $0.75 per address that HITS -- ~100x everything else. Listed so nobody "
        "rediscovers it as 'purpose-built'.",
}


class BudgetExhausted(RuntimeError):
    """Raised when a call would exceed --budget. Never truncate silently instead."""


class NotApproved(RuntimeError):
    pass


class VendorRefusal(RuntimeError):
    """Raised when a call would violate doctrine, e.g. asking who owns a parcel."""


# ---------------------------------------------------------------- ledger


def ledger_path(run_dir=None):
    if run_dir:
        return pathlib.Path(run_dir) / "ledger.csv"
    return octlib.cache_root() / "ledger.csv"


def ledger_append(path, endpoint, sent, billable):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(LEDGER_HEADER)
        w.writerow([octlib.utcnow_iso(), endpoint, sent, "{:.6f}".format(billable)])


def ledger_total(path):
    path = pathlib.Path(path)
    if not path.is_file():
        return 0.0, 0
    total, rows = 0.0, 0
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            try:
                total += float(r.get("billable") or 0)
            except ValueError:
                pass
    return total, rows


# ---------------------------------------------------------------- pricing


def unit_price(axis, tier=None, manifest=None):
    """-> (usd_per_result, tier_used, source). Fails closed when the price is unknown.

    Runtime reads the manifest. PRICE_SEED is only a fallback and is labelled as such in
    the returned source string, so an estimate can never look more authoritative than it is.
    """
    if manifest:
        for rec in manifest.get("pricing", []):
            if rec.get("axis") == axis and rec.get("usd_per_result") is not None:
                return float(rec["usd_per_result"]), rec.get("tier"), "capability manifest"
    seed = PRICE_SEED.get(axis)
    if not seed:
        return None, None, "unknown axis"
    prices = seed["usd_per_result"]
    if tier and tier in prices and prices[tier] is not None:
        return prices[tier], tier, "PRICE_SEED (dated observation, not a runtime constant)"
    if "ANY" in prices and prices["ANY"] is not None:
        return prices["ANY"], "ANY", "PRICE_SEED (dated observation, not a runtime constant)"
    # No tier supplied and the price is tier-dependent: fail closed on the WORST case.
    known = [v for v in prices.values() if v is not None]
    if not known:
        return None, None, "price not recorded — read it from the account before estimating"
    return max(known), "WORST-CASE (tier unknown)", \
        "PRICE_SEED worst case — pass --tier to narrow it"


def estimate(persons, axis, max_results=None, tier=None, manifest=None,
             expected_phones=0, reverse_axis="one_api_reverse_phone",
             scrub=False, dnc_numbers=0):
    """Worst-case estimate. persons x max_results x p_name + expected_phones x p_reverse."""
    seed = PRICE_SEED.get(axis) or {}
    # If max_results was not set explicitly, the worst case is the ACTOR'S DEFAULT, because
    # that is what will actually be sent -- not the value we wish had been used. apivault
    # defaults to 100 and bills per delivered match, so estimating with the recommended 3
    # would understate a 200-name batch by 33x and let it sail through the budget gate.
    mr_explicit = max_results is not None
    mr = max_results if mr_explicit else seed.get("default_max_results", 1)
    p_name, tier_used, src = unit_price(axis, tier, manifest)

    lines, usd = [], 0.0
    if p_name is None:
        lines.append({"axis": axis, "persons": persons, "max_results": mr,
                      "usd_per_result": None, "usd": None, "tier": tier_used,
                      "source": src,
                      "status": "FAIL CLOSED — price unknown, cannot estimate this axis"})
    else:
        cost = persons * mr * p_name + float(seed.get("usd_start") or 0)
        usd += cost
        note = seed.get("note")
        if not mr_explicit:
            note = ("max_results WAS NOT SET — estimating at the actor's own default of {}, "
                    "because that is what will be sent. Set it explicitly ({} recommended) "
                    "before firing. {}".format(mr, seed.get("recommended_max_results"), note))
        lines.append({"axis": axis, "persons": persons, "max_results": mr,
                      "max_results_explicit": mr_explicit,
                      "usd_per_result": p_name, "usd": round(cost, 4),
                      "tier": tier_used, "source": src, "note": note})

    if expected_phones:
        p_rev, rtier, rsrc = unit_price(reverse_axis, tier, manifest)
        if p_rev is None:
            lines.append({"axis": reverse_axis, "persons": expected_phones,
                          "max_results": 1, "usd": None, "tier": rtier, "source": rsrc,
                          "status": "FAIL CLOSED — price unknown"})
        else:
            cost = expected_phones * p_rev
            usd += cost
            lines.append({"axis": reverse_axis, "persons": expected_phones,
                          "max_results": 1, "usd_per_result": p_rev,
                          "usd": round(cost, 4), "tier": rtier, "source": rsrc,
                          "note": "A SECOND BILLED CALL PER PHONE — required to promote to "
                                  "CONFIRMED."})

    credits = persons * TRACERFY_CREDITS["trace_lookup"]
    credit_lines = [{"axis": "tracerfy.trace_lookup", "calls": persons,
                     "credits_per_hit": TRACERFY_CREDITS["trace_lookup"],
                     "credits": credits,
                     "note": "MISSES ARE FREE, so this is a ceiling, not a forecast."}]
    if scrub:
        n = dnc_numbers or expected_phones or persons
        credit_lines.append({"axis": "tracerfy.dnc_check", "calls": n,
                             "credits_per_hit": TRACERFY_CREDITS["dnc_check"],
                             "credits": n,
                             "note": "--scrub. Without it every number ships stamped "
                                     "'{}'".format(octlib.NOT_SCRUBBED_STAMP)})
        credits += n

    return {"usd_total": round(usd, 4), "lines": lines,
            "credits_total": credits, "credit_lines": credit_lines,
            "usd_per_credit": None,
            "usd_per_credit_note": ("NOT DOCUMENTED anywhere in our records. Ask Mitch once "
                                    "and write it into references/source_ledger.md. Until "
                                    "then report credits, never a dollar figure."),
            "worst_case": True}


def print_estimate(est, budget, credit_balance=None):
    print("\nWORST-CASE ESTIMATE — this is a ceiling, computed with max_results explicit\n")
    print("  {:<28} {:>8} {:>6} {:>12} {:>10}  {}".format(
        "axis", "calls", "max_r", "$/result", "$", "tier / source"))
    for l in est["lines"]:
        print("  {:<28} {:>8} {:>6} {:>12} {:>10}  {} / {}".format(
            l["axis"], l.get("persons", ""), l.get("max_results", ""),
            l.get("usd_per_result", "?"), l.get("usd", "FAIL-CLOSED"),
            l.get("tier"), l.get("source")))
        if l.get("note"):
            print("      {}".format(l["note"]))
        if l.get("status"):
            print("      {}".format(l["status"]))
    print("\n  USD TOTAL (worst case)  ${:.4f}   against --budget ${:.2f}".format(
        est["usd_total"], budget))

    print("\n  TRACERFY CREDITS — a separate counter, not dollars")
    for c in est["credit_lines"]:
        print("  {:<28} {:>8} calls x {} credits = {}".format(
            c["axis"], c["calls"], c["credits_per_hit"], c["credits"]))
        print("      {}".format(c["note"]))
    print("  CREDITS TOTAL  {}".format(est["credits_total"]))
    if credit_balance is not None:
        print("  opening balance {}  -> {}".format(
            credit_balance,
            "OK" if est["credits_total"] <= credit_balance
            else "REFUSING TO FIRE: estimate exceeds balance"))
    print("  {}".format(est["usd_per_credit_note"]))


# ---------------------------------------------------------------- gates


def check_approval(budget, i_approve):
    if i_approve is None:
        raise NotApproved(
            "--i-approve is required before any paid call and must EQUAL --budget "
            "(${:.2f}). Nothing fires until it does.".format(budget))
    if abs(float(i_approve) - float(budget)) > 1e-9:
        raise NotApproved(
            "--i-approve ${:.2f} does not equal --budget ${:.2f}. They must match exactly."
            .format(float(i_approve), float(budget)))
    return True


def check_budget(ledger, budget, next_cost):
    spent, _ = ledger_total(ledger)
    if spent + next_cost > budget + 1e-9:
        raise BudgetExhausted(
            "would spend ${:.4f} on top of ${:.4f} already ledgered, exceeding --budget "
            "${:.2f}. Raising rather than truncating silently — a truncated run looks like "
            "a complete one.".format(next_cost, spent, budget))
    return True


def guard_person_axis(first, last, address):
    """Doctrine 2: vendors are asked HOW TO REACH A NAMED PERSON, never who owns a parcel."""
    if not (first and last):
        raise VendorRefusal(
            "person axis requires first_name AND last_name. Omitting them asks the vendor "
            "to discover the resident, which is NOT the owner — that is the Fort Stockton "
            "failure (doctrine 2).")
    if not address:
        raise VendorRefusal(
            "person axis requires an address to anchor against. A returned person with no "
            "anchor cannot be accepted (doctrine 3).")
    return True


def guard_zip(address_line):
    """one-api returns 'Invalid Adddress Format' (their typo) when the ZIP is missing.

    A 196-address run without ZIPs cost $1.40 and returned nothing.
    """
    import re
    if not re.search(r"\b\d{5}(-\d{4})?\b", address_line or ""):
        raise VendorRefusal(
            "address has no ZIP: {!r}. Submit as 'street, city ST zip' or one-api returns "
            "'Person Not Found' / 'Invalid Adddress Format' and bills you for it."
            .format(address_line))
    return True


def anchor_or_discard(returned_mailing, parcel_addr_key, principal_addr_key=None):
    """Doctrine 1 exception, held one-directional.

    An APN-keyed or reverse-address result may CORROBORATE a candidate a government record
    already named. It may never CREATE one. A result that does not anchor is discarded --
    never promoted, never printed.
    """
    key = octlib.addr_key(returned_mailing.get("street", ""),
                          returned_mailing.get("city", ""),
                          returned_mailing.get("state", ""),
                          returned_mailing.get("zip", ""))
    if key and key == parcel_addr_key:
        return True, "parcel mailing address"
    if principal_addr_key and key and key == principal_addr_key:
        return True, "Sunbiz-filed address of the principal"
    return False, ("addr_key {!r} matches neither the parcel mailing address nor the "
                   "pierced principal's filed address — DISCARDED. Anchoring proves "
                   "association with an address, and its absence proves nothing was "
                   "corroborated.".format(key))


# ---------------------------------------------------------------- separator probe


def separator_probe_plan(known_answer_name="Jane Doe", locality="Springfield, IL 62704"):
    """Probe the input separator; never assert it.

    The 2026-08-04 observation was comma for apivault and semicolon for one-api. The live
    apivault schema (modified 2026-08-08) documents a SEMICOLON, and one-api's name field
    says the same. Rather than pick, fire the same known-answer name in both forms at
    max_results:1 (about $0.013) and adopt whichever returns a record.
    """
    return {
        "cost_usd": 0.013,
        "max_results": 1,
        "forms": [{"separator": ";", "input": "{}; {}".format(known_answer_name, locality)},
                  {"separator": ",", "input": "{}, {}".format(known_answer_name, locality)}],
        "adopt": "whichever returns a record",
        "log": "record the winner WITH A DATE in the capability manifest; re-probe when the "
               "actor's modified date changes",
    }


# ---------------------------------------------------------------- results


def stash_results(run_dir, name, payload):
    """Write vendor results to RUN_DIR. NEVER let dataset items enter context.

    Writes .tmp then renames, so a partial write is never mistaken for a result set.
    """
    d = pathlib.Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    tmp.replace(p)
    n = len(payload) if isinstance(payload, list) else 1
    return {"path": str(p), "records": n,
            "note": "Results are on disk. Do not read them into context — a Placecraft list "
                    "call once returned 168,571 chars."}


def cache_key(axis, payload):
    return hashlib.sha256(
        (axis + "||" + json.dumps(payload, sort_keys=True)).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="vendor_client.py",
        description="Budgeted, ledgered vendor client. Prints a WORST-CASE estimate and "
                    "refuses to fire until --i-approve equals --budget.")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--persons", type=int, default=0)
    ap.add_argument("--axis", default="apivault_name",
                    choices=sorted(PRICE_SEED.keys()))
    ap.add_argument("--max-results", type=int,
                    help="ALWAYS set this explicitly. apivault defaults to 100 and bills "
                         "per delivered match.")
    ap.add_argument("--tier", help="account tier, e.g. BRONZE. A price without a tier is "
                                   "not a price: one-api is $0.007 BRONZE / $0.02 FREE.")
    ap.add_argument("--expected-phones", type=int, default=0,
                    help="phones expected into the reverse-phone leg — a SECOND billed call "
                         "per phone")
    ap.add_argument("--scrub", action="store_true", help="add the dnc_check credit line")
    ap.add_argument("--budget", type=float, default=25.0)
    ap.add_argument("--i-approve", type=float, default=None,
                    help="must EQUAL --budget or nothing fires")
    ap.add_argument("--credit-balance", type=int, help="Tracerfy opening balance")
    ap.add_argument("--manifest", help="capability_manifest.json from doctor.py")
    ap.add_argument("--run-dir")
    ap.add_argument("--ledger-summary", action="store_true")
    ap.add_argument("--separator-probe-plan", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.ledger_summary:
        p = ledger_path(args.run_dir)
        total, rows = ledger_total(p)
        print("ledger {}\n  {} row(s), ${:.4f} billable".format(p, rows, total))
        return 0

    if args.separator_probe_plan:
        print(json.dumps(separator_probe_plan(), indent=2))
        return 0

    if not args.estimate:
        ap.print_help()
        return 0

    manifest = None
    if args.manifest:
        manifest = json.loads(pathlib.Path(args.manifest).read_text(encoding="utf-8"))

    est = estimate(args.persons, args.axis, max_results=args.max_results, tier=args.tier,
                   manifest=manifest, expected_phones=args.expected_phones,
                   scrub=args.scrub)
    if args.json:
        print(json.dumps(est, indent=2, ensure_ascii=False))
    else:
        print_estimate(est, args.budget, args.credit_balance)

    try:
        check_approval(args.budget, args.i_approve)
    except NotApproved as e:
        print("\nNOT ARMED: {}".format(e))
        return 3

    if est["usd_total"] > args.budget:
        print("\nREFUSING TO FIRE: worst case ${:.4f} exceeds --budget ${:.2f}. Lower "
              "max_results, reduce the person count, or raise the budget deliberately."
              .format(est["usd_total"], args.budget))
        return 4
    if args.credit_balance is not None and est["credits_total"] > args.credit_balance:
        print("\nREFUSING TO FIRE: {} credits exceeds the opening balance of {}."
              .format(est["credits_total"], args.credit_balance))
        return 4

    print("\nARMED: --i-approve ${:.2f} matches --budget. Worst case ${:.4f}, {} credits."
          .format(args.i_approve, est["usd_total"], est["credits_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
