#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sos_route.py — per-state registry dispatcher. Returns (route, disposition, reason).

THE RULE THIS FILE EXISTS TO ENFORCE: a registry outage NEVER escalates to a paid identity
query. That is doctrine 2. A state with no route is a coverage disposition, never a silent
zero and never a reason to ask a vendor who owns a parcel.

`--probe <ST>` runs a known-answer liveness check before any work in that state. On failure
it emits `UNEVALUATED — <ST> registry route down (<code>, probed <ts>)`.

The TN probe is the one that matters most and it is the easiest to get wrong: as of
2026-08-11 every OpenGovUS QUERY form returns HTTP 500 while LANDING pages return 200. A
naive status check hits the landing page and reports the route healthy. So the probe hits
the query form.

Usage:
    sos_route.py --probe TN
    sos_route.py --route FL --json
    sos_route.py --probe-all --offline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

ROUTES = {
    "FL": {
        "route": "SUNBIZ_BULK",
        "detail": "SFTP bulk quarterly (primary) + search.sunbiz.org per-entity for <=10 "
                  "stragglers per run, behind a browser-availability doctor check. "
                  "Use get_page_text — read_page returns empty on this site.",
        "officer_reverse_search":
            "search.sunbiz.org/Inquiry/CorporationSearch/ByOfficerAndRegisteredAgentName",
        "probe": {"url": "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
                  "expect": [200], "known_answer": "NHG HOLDINGS LLC / L06000038390"},
        "miss_disposition": "NO-SOS-MATCH",
        "notes": ["A 'no Sunbiz match' where the county shows a recent conveyance is "
                  "'possible post-snapshot formation', not a flat miss.",
                  "38 of 124 matched entities were FOREIGN filings and nothing follows them "
                  "home. A foreign filing is a NAMED GAP, never 'pierced'."],
    },
    "TN": {
        "route": "OPENGOVUS_MIRROR",
        "detail": "https://opengovus.com/tennessee-business?name=<NAME>  (?name=, NOT ?q=), "
                  "detail /tennessee-business/<control#>, 0.8 s delay, browser UA required "
                  "(403 without one). Detail labels include the state's own misspelling "
                  "'Principle Address' — match it literally. pick() ladder is "
                  "exact-normalized -> unique-prefix -> prefix-ambiguous, never a loose guess.",
        "probe": {"url": "https://opengovus.com/tennessee-business?name=SCHAAD",
                  "expect": [200],
                  "known_answer": "any row matching /tennessee-business/(\\d{6,12})",
                  "warning": "PROBE THE QUERY FORM, NOT THE LANDING PAGE. As of 2026-08-11 "
                             "every query form returns 500 while landing pages return 200."},
        "miss_disposition": "NO-SOS-MATCH",
        "known_state": {"verdict": "DOWN", "observed": "2026-08-11",
                        "evidence": "HTTP 500 on ?name=SCHAAD, ?q=, ?name=HOLSTON+HILLS and "
                                    "detail /tennessee-business/000625089. tnbear.tn.gov "
                                    "returns 000 from this machine, the in-app browser and "
                                    "Apify's infrastructure. whetstonetools has no TN."},
        "notes": ["Even when up, the snapshot ends ~2015-16: 15 of 44 entities (34%) "
                  "returned no match, mostly post-snapshot formations. That is acceptable — "
                  "long-held family land sits in old entities.",
                  "Knox — this skill's own canonical county — currently has ZERO "
                  "entity-pierce route.",
                  "Corroboration-tier-only fallbacks: company-detail.com/company-<slug>-"
                  "<DOSID>, and litigation-snippet search."],
    },
    "TX": {
        "route": "SOCRATA_9CIR_EFMM",
        "detail": "data.texas.gov dataset 9cir-efmm, free.",
        "probe": {"url": "https://data.texas.gov/resource/9cir-efmm.json?$limit=1",
                  "expect": [200], "known_answer": "one JSON row"},
        "miss_disposition": "NO-SOS-MATCH",
        "notes": ["Carries the FORMATION-ERA address, not the current one. Ship that caveat "
                  "with every result.",
                  "ROAD RUNNER TX LP is absent from the dataset entirely — absence is NOT "
                  "evidence the entity does not exist.",
                  "Comptroller franchise search is JS-driven and returns the search page, "
                  "not results. SOSDirect requires a login."],
    },
    "NC": {
        "route": "NO_ROUTE",
        "detail": "none",
        "probe": None,
        "miss_disposition": "NO-ROUTE-STATE",
        "reason": "sosnc.gov is Cloudflare-challenged AND its terms prohibit automated "
                  "search — ASK Mitch before OpenSOSData or the $2,750 bulk subscription",
        "notes": ["monty15/north-carolina-sos-business-search is the only NC-capable actor "
                  "(~$0.0055/result, ~$10 for ~1,500 entities) and FAILED all three "
                  "attempts. Its schema has registered_agent_name but NO registered-agent "
                  "address. Do not budget on it without a 20-entity known-answer gate.",
                  "Bulk subscription: $2,000/state fiscal year + $750 setup, CSV over FTP, "
                  "weekly, 'no technical support is offered', 919-814-5400. The FTP hostname "
                  "and column layout are UNVERIFIED — the data dictionary lives on the FTP "
                  "and is released only after subscribing. ASK NC SoS whether "
                  "registered-agent address is a discrete column BEFORE paying.",
                  "OpenSOSData's 10 free lookups require signup. Claude cannot create the "
                  "account — Blocked on Mitch."],
    },
    "NY": {
        "route": "ROLL_PLUS_COMPANY_DETAIL",
        "detail": "Assessment roll + shared-mailing clustering (PO BOX 630 Brewerton "
                  "collapsed a 4-party assemblage to 2), plus the entity hop "
                  "company-detail.com/company-<slug>-<DOSID> which returns the NY DOS CEO "
                  "name AND full home address, the DOS process address, and the principal "
                  "executive office. No auth, WebFetch-friendly.",
        "probe": {"url": "https://gisservices.its.ny.gov/arcgis/rest/services/"
                         "NYS_Tax_Parcels_Public/MapServer/1?f=json",
                  "expect": [200], "known_answer": "layer metadata"},
        "miss_disposition": "NO-SOS-MATCH",
        "notes": ["great_pistachio/us-business-search works for NY but is COMPANY-NAME "
                  "SEARCH ONLY — an officer-name query silently returns nothing.",
                  "Litigation records name principals (Kopp v Fietta Realty Corp., 2006). "
                  "law.justia.com 403s WebFetch, but the search-result SNIPPET carries the "
                  "party name.",
                  "For any NY manufactured-home-park owner, NYS DHCR sxi2-m23m returns a "
                  "Tier-1 GOVERNMENT phone: data.ny.gov/resource/sxi2-m23m.json?$q=<NAME>"
                  "&$limit=200"],
    },
    "SC": {"route": "NO_ROUTE", "detail": "none", "probe": None,
           "miss_disposition": "NO-ROUTE-STATE",
           "reason": "no working registry route identified", "notes": []},
    "MI": {"route": "NO_ROUTE", "detail": "none", "probe": None,
           "miss_disposition": "NO-ROUTE-STATE",
           "reason": "mibusinessregistry.lara.state.mi.us is browser-only behind a "
                     "self-clearing Cloudflare interstitial and has NO officer or "
                     "registered-agent search — so even a successful browser session does "
                     "not answer this skill's question",
           "notes": ["pta.waynecounty.com is the delinquent-tax portal ONLY — a valid "
                     "address returns nothing. BS&A defeats read_page/get_page_text; drive "
                     "it with screenshots."]},
}


def route_for(state):
    st = (state or "").strip().upper()
    r = ROUTES.get(st)
    if not r:
        return {
            "state": st, "route": "UNEVALUATED",
            "disposition": "UNEVALUATED",
            "reason": "UNEVALUATED — no working registry route for {} as of {}".format(
                st or "??", octlib.utcnow_iso()[:10]),
            "escalate_to_paid_vendor": False,
        }
    out = dict(r)
    out["state"] = st
    out["disposition"] = r["miss_disposition"]
    out["reason"] = r.get("reason", r["detail"])
    out["escalate_to_paid_vendor"] = False       # never, in any branch
    return out


def probe(state, offline=False, timeout=20):
    st = (state or "").strip().upper()
    r = ROUTES.get(st)
    ts = octlib.utcnow_iso()
    if not r:
        return {"state": st, "status": "UNEVALUATED", "probed_at": ts,
                "disposition": "UNEVALUATED — no working registry route for {} as of {}"
                               .format(st, ts[:10])}
    if not r.get("probe"):
        return {"state": st, "status": "NO_ROUTE", "probed_at": ts,
                "disposition": "NO-ROUTE-STATE", "reason": r.get("reason")}
    if offline:
        return {"state": st, "status": "UNEVALUATED", "probed_at": ts,
                "reason": "--offline: no probe attempted",
                "disposition": "UNEVALUATED — {} registry route not probed ({})".format(st, ts)}

    url = r["probe"]["url"]
    req = urllib.request.Request(url)
    req.add_header("User-Agent", BROWSER_UA)      # 403 without one on several of these
    code = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except urllib.error.URLError as e:
        return {"state": st, "status": "DOWN", "http_code": None, "probed_at": ts,
                "url": url,
                "disposition": "UNEVALUATED — {} registry route down (network error: {}, "
                               "probed {})".format(st, e.reason, ts),
                "escalate_to_paid_vendor": False}

    ok = code in r["probe"]["expect"]
    out = {"state": st, "url": url, "http_code": code, "probed_at": ts,
           "known_answer": r["probe"].get("known_answer"),
           "escalate_to_paid_vendor": False}
    if ok:
        out["status"] = "LIVE"
        out["disposition"] = None
    else:
        out["status"] = "DOWN"
        out["disposition"] = ("UNEVALUATED — {} registry route down ({}, probed {})"
                              .format(st, code, ts))
        out["do_not"] = ("Do NOT fall through to a paid vendor. That would violate doctrine "
                         "2. Emit the disposition and continue.")
    if r["probe"].get("warning"):
        out["warning"] = r["probe"]["warning"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sos_route.py",
        description="Per-state Secretary-of-State dispatcher. A registry outage NEVER "
                    "escalates to a paid identity query (doctrine 2).")
    ap.add_argument("--route", help="print the route for a state and exit")
    ap.add_argument("--probe", help="known-answer liveness check for a state")
    ap.add_argument("--probe-all", action="store_true")
    ap.add_argument("--offline", action="store_true", help="skip network probes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.route:
        r = route_for(args.route)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print("state        {}".format(r["state"]))
            print("route        {}".format(r["route"]))
            print("disposition  {}".format(r["disposition"]))
            print("reason       {}".format(r["reason"]))
            for n in r.get("notes", []):
                print("note         {}".format(n))
            print("escalate to a paid vendor on failure: {}".format(
                r["escalate_to_paid_vendor"]))
        return 0

    states = list(ROUTES) if args.probe_all else ([args.probe] if args.probe else [])
    if not states:
        ap.print_help()
        return 0

    results = [probe(s, offline=args.offline) for s in states]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    worst = 0
    for r in results:
        print("{:3} {:12} http={} {}".format(
            r["state"], r["status"], r.get("http_code"), r.get("disposition") or "route live"))
        if r.get("warning"):
            print("    WARNING {}".format(r["warning"]))
        if r.get("do_not"):
            print("    {}".format(r["do_not"]))
        if r["status"] in ("DOWN", "UNEVALUATED"):
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
