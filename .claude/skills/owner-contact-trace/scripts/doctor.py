#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py — stage 0: capability manifest and zero-cost probes.

Builds `capability_manifest.json`: one record per source carrying its zero-cost probe
result, response-schema fingerprint, declared upstream lineage, price AND ACCOUNT TIER,
quota/credit balance, permitted axes, and last successful known-answer control.

**Runtime routing reads the manifest, never a hard-coded table.** A changed schema, an
unknown upstream lineage, a failed control, or an undiscoverable price makes that
capability FAIL CLOSED -- degraded to UNEVALUATED, never silently skipped and never
escalated to a different vendor to paper over.

THE FREE-TOOL GATE (acceptance test 24). A doctor run makes ZERO credit-consuming calls.
It may call Tracerfy `check_balance` and `list_strategies`, which are free. It must never
call `trace_lookup`, `parcel_lookup`, `dnc_check` or `execute_lead_list`. The permitted and
forbidden lists are explicit constants below so the test can assert against them.

MCP tools are not callable from a plain Python process. Where a probe needs an MCP
connector, doctor.py emits the exact ToolSearch query for the agent to run and records the
capability as UNEVALUATED until the agent supplies the result via --mcp-results. It never
guesses, and it never reports a connector as healthy on the strength of a hardcoded prefix.

Usage:
    doctor.py --probe                      # everything free, including network auth probes
    doctor.py --probe --offline            # dependencies and config only, no network
    doctor.py --probe --mcp-results mcp.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Free. A doctor run may call these.
TRACERFY_FREE_TOOLS = ("check_balance", "list_strategies")
# Credit-consuming. A doctor run must NEVER call these.
TRACERFY_FORBIDDEN_IN_DOCTOR = ("trace_lookup", "parcel_lookup", "dnc_check",
                                "preview_lead_list", "execute_lead_list",
                                "get_lead_list_status", "get_lead_list_rows")

# Resolve MCP tools by keyword search. NEVER hardcode the mcp__<uuid>__ prefix -- it
# differs per machine. A bare select:mcp__apify__... fails because these tools are deferred.
MCP_RESOLVERS = {
    "apify": 'ToolSearch(query: "apify actor call dataset", max_results: 8)',
    "zoho": 'ToolSearch(query: "zoho searchRecords COQL", max_results: 6)',
    "tracerfy": 'ToolSearch(query: "tracerfy trace lookup dnc balance", max_results: 8)',
}

DEPENDENCIES = [
    ("openpyxl", "XLSX output; CSV still writes without it"),
    ("jsonschema", "schema validation in delivery_gate.py"),
    ("yaml", "reading config/run.yaml"),
]

# Zero-cost HTTP auth probes. Each records what a LIVE response looks like versus a DEAD
# one, because for several of these the two are easy to confuse.
HTTP_PROBES = [
    {"name": "batchdata", "url": "https://api.batchdata.com/api/v1/property/skip-trace",
     "method": "POST", "body": "{}", "headers": {"Content-Type": "application/json"},
     "live_codes": [400], "dead_codes": [401],
     "live_means": "400 field-validation ('The requests field is required') = LIVE",
     "dead_means": "401 = key dead",
     "note": "api.batchdata.io does not resolve — use api.batchdata.com. ROTATE the token: "
             "it was pasted into a chat transcript."},
    {"name": "census_geocoder",
     "url": "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
            "?address=1600+Pennsylvania+Ave+NW+Washington+DC&benchmark=Public_AR_Current"
            "&format=json",
     "method": "GET", "live_codes": [200], "dead_codes": [],
     "live_means": "200 = LIVE, free and keyless",
     "note": "For a LIST use the BATCH endpoint (file upload, <=10,000 rows). A keyless "
             "per-row loop over 3,000 parcels will be throttled with no documented backoff."},
]

# Sources whose verdict is a dated observation, carried into the manifest with its re-probe
# so nobody codes around a source that may have come back.
DATED_VERDICTS = [
    {"name": "skipsherpa", "verdict": "BLOCKED", "observed": "2026-08-11",
     "reprobe": "PUT /api/person {} with header API-Key — 403 permission_denied_exception "
                "means dead",
     "note": "Two distinct dead-key strings mean different things: 'API Key is not active "
             "or is not valid anymore' = recognized but deactivated; 'Invalid API Key' = "
             "not recognized at all.",
     "price": "$0.15/lookup PAYG, $0.10 at 1,000/mo, $0.08 at 12,500", "tier": "PAYG"},
    {"name": "melissa", "verdict": "BLOCKED", "observed": "2026-08-11",
     "reprobe": "GET usage.melissadata.net/v1/license?id=<key> — id alone, no t= parameter. "
                "Rejected keys cost $0. GE05/GE08 means skip and note the gap; any YS## "
                "means run melissa.py selftest (1 credit) first.",
     "price": "credits", "tier": "unknown"},
    {"name": "opengovus_tn", "verdict": "DOWN", "observed": "2026-08-11",
     "reprobe": "GET https://opengovus.com/tennessee-business?name=SCHAAD with a browser UA "
                "— HTTP 500 on every query form as of 2026-08-11 while landing pages return "
                "200, so check the QUERY form, not the landing page.",
     "note": "TN has NO entity-pierce route today. Emit UNEVALUATED; never escalate to a "
             "paid vendor (doctrine 2).", "price": "free", "tier": "n/a"},
    {"name": "opencorporates", "verdict": "DEAD-FOR-US", "observed": "2026-08-06",
     "reprobe": "none — 0 US matches on every name, all UK. Affirmatively dead.",
     "price": "n/a", "tier": "n/a"},
    {"name": "sosnc", "verdict": "NO_ROUTE", "observed": "2026-08-10",
     "reprobe": "none — Cloudflare-challenged AND terms prohibit automated search. Ask "
                "Mitch before OpenSOSData or the $2,750 bulk subscription.",
     "price": "$2,000/yr + $750 setup", "tier": "n/a"},
]

# Declared upstream lineage. phone_attributed() reads this: two actors reselling the same
# aggregator are ONE source, and unknown lineage fails closed.
LINEAGE = {
    "tracerfy": "UNDECLARED — ask the vendor and record the answer here. Until then any "
                "corroboration involving Tracerfy fails closed to SINGLE-SOURCE-PHONE.",
    # DECLARED 2026-08-12 from the actor's own store description. This COLLIDES with the
    # TPS-backed actors below: one-api may not corroborate either of them, and they may not
    # corroborate each other. One source, three hats (acceptance test 27).
    "one-api/skip-trace": "TruePeopleSearch, FastPeopleSearch, Lead Finder, Truthfinder, "
                          "Spokeo, BeenVerified, PeopleFinders",
    "apivault_labs/skip-trace-people-finder": "UNDECLARED — ask the vendor. Until declared, "
                                              "any corroboration involving it fails closed.",
    "scrapyspider/truepeoplesearch-contact-finder": "TruePeopleSearch (via ScrapFly)",
    "jungle_synthesizer/truepeoplesearch-people-search-scraper":
        "TruePeopleSearch (via Bright Data)",
    "batchdata": "UNDECLARED",
}


def probe_dependencies():
    out = []
    for mod, why in DEPENDENCIES:
        try:
            __import__(mod)
            out.append({"module": mod, "present": True, "why": why, "install": None})
        except ImportError:
            pkg = "pyyaml" if mod == "yaml" else mod
            out.append({"module": mod, "present": False, "why": why,
                        "install": "{} -m pip install --user {}".format(
                            os.path.basename(sys.executable), pkg)})
    return out


def probe_key_files():
    out = []
    for path, vendor in ((("~/.skipsherpa/key"), "skipsherpa"),
                         (("~/.batchdata/key"), "batchdata"),
                         (("~/.melissa/credits_key"), "melissa")):
        p = pathlib.Path(path).expanduser()
        rec = {"vendor": vendor, "path": path, "present": p.is_file()}
        if rec["present"]:
            st = p.stat()
            rec["mode"] = oct(st.st_mode & 0o777)
            rec["dir_mode"] = oct(p.parent.stat().st_mode & 0o777)
            rec["mode_ok"] = rec["mode"] == "0o600" and rec["dir_mode"] == "0o700"
            rec["fix"] = None if rec["mode_ok"] else \
                "chmod 700 {} && chmod 600 {}".format(path.rsplit("/", 1)[0], path)
            # Never read, print, or hash the key value.
            rec["value_read"] = False
        else:
            rec["note"] = ("Mitch places key values. Claude cannot install a key via Bash — "
                           "the command classifier blocks it — but the Write tool CAN place "
                           "the file.")
        out.append(rec)
    return out


def http_probe(spec, timeout=20):
    rec = {"name": spec["name"], "url": spec["url"], "method": spec["method"],
           "live_means": spec.get("live_means"), "dead_means": spec.get("dead_means"),
           "note": spec.get("note")}
    data = spec.get("body", "").encode("utf-8") if spec.get("body") else None
    req = urllib.request.Request(spec["url"], data=data, method=spec["method"])
    req.add_header("User-Agent", BROWSER_UA)
    for k, v in (spec.get("headers") or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code, body = resp.getcode(), resp.read(4096)
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read(4096)
    except urllib.error.URLError as e:
        rec.update({"status": "UNEVALUATED", "http_code": None,
                    "reason": "network error: {}".format(e.reason)})
        return rec
    rec["http_code"] = code
    rec["schema_fingerprint"] = hashlib.sha256(body[:2048]).hexdigest()[:16]
    if code in spec.get("live_codes", []):
        rec["status"] = "LIVE"
    elif code in spec.get("dead_codes", []):
        rec["status"] = "DEAD"
    else:
        rec["status"] = "UNEVALUATED"
        rec["reason"] = ("HTTP {} is neither the documented live nor the documented dead "
                         "code — fail closed rather than guess".format(code))
    return rec


def probe_counties():
    out = []
    for f in sorted(glob.glob(str(pathlib.Path(__file__).resolve().parent.parent
                                  / "config" / "counties" / "*.json"))):
        base = os.path.basename(f)
        if base.startswith("_"):
            continue
        try:
            cfg = json.load(open(f, encoding="utf-8"))
        except ValueError as e:
            out.append({"county_key": base, "status": "BROKEN", "reason": str(e)})
            continue
        rec = {"county_key": cfg.get("county_key"), "verified": cfg.get("verified"),
               "has_mail_fields": bool(cfg.get("mail_fields")),
               "has_owner_fields": bool(cfg.get("owner_fields")),
               "adapter_kind": cfg.get("adapter_kind", "arcgis"),
               "traps": len(cfg.get("traps") or [])}
        alt = cfg.get("alt_layer_fields") or {}
        rec["has_alt_mail_fields"] = bool(cfg.get("alt_layer_url") and alt.get("mail_fields"))
        if not rec["has_owner_fields"]:
            rec["status"] = "DEGRADED"
            rec["reason"] = "layer publishes no owner field — rows take NO-OWNER-NAME"
        elif not rec["has_mail_fields"] and rec["has_alt_mail_fields"]:
            rec["status"] = "OK"
            rec["reason"] = ("primary layer carries no mailing fields; the ALT layer does — "
                             "county_fetch must use alt_layer_url for the anchor")
        elif not rec["has_mail_fields"]:
            rec["status"] = "DEGRADED"
            rec["reason"] = ("layer publishes no owner mailing fields — the ANCHOR cannot "
                             "be built from this layer alone")
        elif rec["adapter_kind"] != "arcgis":
            rec["status"] = "NOT_IMPLEMENTED"
            rec["reason"] = "web-grid adapter; form contract recorded but not implemented"
        else:
            rec["status"] = "OK"
        out.append(rec)
    return out


def mcp_records(supplied):
    """MCP capabilities. Never guessed, never hardcoded.

    A plain Python process cannot call an MCP tool. Each record is UNEVALUATED until the
    agent runs the printed ToolSearch query and feeds the result back with --mcp-results.
    """
    out = []
    for name, resolver in MCP_RESOLVERS.items():
        rec = {"name": name, "kind": "mcp", "resolver": resolver,
               "status": "UNEVALUATED",
               "reason": "MCP tools are not callable from this process; the agent must "
                         "resolve them with the resolver query above",
               "lineage": LINEAGE.get(name, "UNDECLARED")}
        if name == "tracerfy":
            rec["free_tools_permitted_in_doctor"] = list(TRACERFY_FREE_TOOLS)
            rec["credit_consuming_forbidden_in_doctor"] = list(TRACERFY_FORBIDDEN_IN_DOCTOR)
            rec["credit_costs"] = {"trace_lookup_hit": 5, "parcel_lookup_hit": 5,
                                   "miss": 0, "dnc_check": 1}
            rec["usd_per_credit"] = None
            rec["usd_per_credit_note"] = (
                "NOT DOCUMENTED anywhere in our records. Ask Mitch once and write it into "
                "references/source_ledger.md. Until then report credits, never a fabricated "
                "dollar figure.")
        if supplied and name in supplied:
            rec.update(supplied[name])
            rec.setdefault("status", "LIVE")
        out.append(rec)
    return out


def build_manifest(offline=False, mcp_supplied=None):
    m = {
        "built_at": octlib.utcnow_iso(),
        "cache_root": str(octlib.cache_root()),
        "python": sys.version.split()[0],
        "routing_rule": ("Runtime routing reads THIS manifest, never a hard-coded table. A "
                         "changed schema, unknown lineage, failed control or undiscoverable "
                         "price FAILS CLOSED to UNEVALUATED — never silently skipped, never "
                         "escalated to another vendor to paper over."),
        "dependencies": probe_dependencies(),
        "key_files": probe_key_files(),
        "counties": probe_counties(),
        "mcp": mcp_records(mcp_supplied),
        "http_probes": [],
        "dated_verdicts": DATED_VERDICTS,
        "lineage": LINEAGE,
    }
    if offline:
        m["http_probes"] = [{"name": s["name"], "status": "UNEVALUATED",
                             "reason": "--offline: no network probe attempted"}
                            for s in HTTP_PROBES]
    else:
        m["http_probes"] = [http_probe(s) for s in HTTP_PROBES]
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="doctor.py",
        description="Stage 0: build the capability manifest from zero-cost probes. Spends "
                    "nothing and consumes no vendor credits.")
    ap.add_argument("--probe", action="store_true", help="run the probes (default)")
    ap.add_argument("--offline", action="store_true", help="skip all network probes")
    ap.add_argument("--mcp-results",
                    help="JSON the agent produced by resolving the MCP tools and calling "
                         "only the FREE ones (tracerfy check_balance / list_strategies)")
    ap.add_argument("--out", help="write capability_manifest.json here")
    ap.add_argument("--json", action="store_true", help="print the full manifest")
    args = ap.parse_args(argv)

    supplied = None
    if args.mcp_results:
        supplied = json.loads(pathlib.Path(args.mcp_results).read_text(encoding="utf-8"))
        # Look for evidence a forbidden tool was CALLED, not for its NAME appearing in prose.
        # A blanket substring scan makes it impossible to write an honest note explaining
        # why the backbone is off ("trace_lookup cannot fire at zero credits"), which is
        # exactly the note an operator most needs to read.
        for name, rec in supplied.items():
            called = []
            if isinstance(rec, dict):
                called += [k for k in rec if k in TRACERFY_FORBIDDEN_IN_DOCTOR]
                for key in ("called", "calls", "invoked", "tools_called"):
                    v = rec.get(key)
                    if isinstance(v, str):
                        called.append(v)
                    elif isinstance(v, (list, tuple)):
                        called += [str(x) for x in v]
                if rec.get("credits_deducted"):
                    called.append("something deducted {} credit(s)".format(
                        rec["credits_deducted"]))
            hits = [c for c in called if any(b in str(c)
                                             for b in TRACERFY_FORBIDDEN_IN_DOCTOR)] \
                or [c for c in called if "credit(s)" in str(c)]
            if hits:
                print("REFUSING: --mcp-results shows {!r} CALLED {}, which is "
                      "credit-consuming and must never run in doctor mode "
                      "(acceptance test 24).".format(name, hits), file=sys.stderr)
                return 2

    m = build_manifest(offline=args.offline, mcp_supplied=supplied)

    out = pathlib.Path(args.out) if args.out else \
        octlib.cache_root() / "capability_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if args.json:
        print(json.dumps(m, indent=2, ensure_ascii=False))
        return 0

    print("doctor: capability manifest -> {}".format(out))
    print("  cache root   {}".format(m["cache_root"]))
    print("\ndependencies")
    missing = 0
    for d in m["dependencies"]:
        print("  {:12} {}".format(d["module"], "ok" if d["present"] else "MISSING"))
        if not d["present"]:
            missing += 1
            print("               install: {}".format(d["install"]))
    print("\nvendor key files")
    for k in m["key_files"]:
        if k["present"]:
            print("  {:12} present  mode {} dir {} {}".format(
                k["vendor"], k["mode"], k["dir_mode"],
                "" if k.get("mode_ok") else "-> " + (k.get("fix") or "")))
        else:
            print("  {:12} absent   (Mitch places key values; Write can create the file, "
                  "Bash cannot)".format(k["vendor"]))
    print("\nMCP connectors — resolve by keyword, never hardcode the mcp__<uuid>__ prefix")
    for c in m["mcp"]:
        print("  {:10} {:12} {}".format(c["name"], c["status"], c["resolver"]))
    print("\nzero-cost HTTP probes")
    for p in m["http_probes"]:
        print("  {:18} {:12} {}".format(p["name"], p.get("status"),
                                        p.get("live_means") or p.get("reason") or ""))
    print("\ndated verdicts — every BLOCKED entry carries its re-probe")
    for v in m["dated_verdicts"]:
        print("  {:16} {:14} {}".format(v["name"], v["verdict"], v["observed"]))
    degraded = [c for c in m["counties"] if c.get("status") != "OK"]
    print("\ncounty adapters: {} ok, {} degraded/not-implemented".format(
        len(m["counties"]) - len(degraded), len(degraded)))
    for c in degraded:
        print("  {:16} {:16} {}".format(c.get("county_key"), c.get("status"),
                                        c.get("reason", "")))
    print("\nTracerfy credit gate: doctor called NONE of {} (acceptance test 24)".format(
        ", ".join(TRACERFY_FORBIDDEN_IN_DOCTOR)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
