#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""county_fetch.py — per-county adapter: parcel id -> census row.

Reads a machine-readable adapter from config/counties/<key>.json and returns the census
fields the rest of the pipeline anchors on. This is the free, authoritative leg; nothing
here spends money and nothing here asks a vendor who owns a parcel.

Two behaviours that exist because of specific measured failures:

  * The feature cache key hashes the REQUESTED FIELD LIST, not just the county. Keying on
    county name alone silently reused features fetched before mailing fields were added to
    the config -- 85 of 233 FL rows came back blank with the config correct, the writer
    correct, and nothing erroring.
  * `--fixture` replays a recorded layer response. Every test in this skill runs offline;
    the only live call permitted in the test surface is a zero-cost auth probe.

Usage:
    county_fetch.py --county tn_knox --apn "090 07403"
    county_fetch.py --county fl_duval --apn "019608 0050" --json
    county_fetch.py --county tn_knox --apn "090 07403" --fixture tests/fixtures/knox.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import octlib  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
DEFAULT_TIMEOUT = 45


class CountyFetchError(RuntimeError):
    pass


class NoCountyAdapter(CountyFetchError):
    pass


# ---------------------------------------------------------------- config


def config_dir():
    return pathlib.Path(__file__).resolve().parent.parent / "config" / "counties"


def load_config(county_key):
    p = config_dir() / (county_key + ".json")
    if not p.is_file():
        available = sorted(x.stem for x in config_dir().glob("*.json")
                           if not x.name.startswith("_"))
        raise NoCountyAdapter(
            "NO_COUNTY_ADAPTER {} — available: {}".format(county_key, ", ".join(available)))
    return json.loads(p.read_text(encoding="utf-8"))


def requested_fields(cfg):
    """Every field this adapter asks the layer for. Order-stable, deduped."""
    out = [cfg["parcel_id_field"]]
    out += list(cfg.get("parcel_id_aliases") or [])
    out += list(cfg.get("owner_fields") or [])
    mail = cfg.get("mail_fields") or {}
    if mail:
        out += list(mail.get("street") or [])
        for k in ("city", "state", "zip"):
            if mail.get(k):
                out.append(mail[k])
    situs = cfg.get("situs_fields") or {}
    for v in situs.values():
        if v:
            out.append(v)
    if cfg.get("combined_csz_field"):
        out.append(cfg["combined_csz_field"])
    out += list(cfg.get("extra_fields") or [])
    seen, uniq = set(), []
    for f in out:
        if f and f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


# ---------------------------------------------------------------- cache


def cache_path(county_key, fields, where):
    """Cache key = county + a hash of the REQUESTED FIELD LIST + the where clause.

    The field list is in the key on purpose. See the module docstring and
    references/traps.md, "the stale-cache silent blank".
    """
    h = hashlib.sha256(("|".join(sorted(fields)) + "||" + where).encode("utf-8")).hexdigest()
    d = octlib.cache_root() / "county_cache" / county_key
    return d / (h[:24] + ".json")


def cache_get(path, max_age_s):
    if not path.is_file():
        return None
    if max_age_s is not None and (time.time() - path.stat().st_mtime) > max_age_s:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def cache_put(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    tmp.replace(path)                      # .tmp then atomic rename, never a partial file


# ---------------------------------------------------------------- HTTP


def build_where(cfg, apn):
    """Build the layer's where clause, honouring per-county parcel-id format quirks."""
    field = cfg["parcel_id_field"]
    fmt = cfg.get("parcel_id_format") or {}
    if fmt.get("double_space"):
        # Knox PARCELID embeds double spaces ('090  07403'). Preserve them; normalize only
        # for comparison. REPLACE() in a where clause 400s on this layer.
        pat = apn if "  " in apn else re.sub(r"\s+", "  ", apn.strip())
        return "{} LIKE '{}%'".format(field, pat.replace("'", "''"))
    return "{} = '{}'".format(field, apn.replace("'", "''"))


def interleaved_wildcard(apn):
    """Fallback for layers that reject both exact match and a literal-space LIKE.

    Produces LIKE '0%9%0%0%7%4%0%3%' from '090 07403'. Deliberately loose -- results are
    filtered client-side by normalized equality, never trusted as-is.
    """
    chars = [c for c in octlib.napn(apn)]
    return "%".join(chars) + "%"


def http_get_json(url, headers, timeout, method="GET", body=None):
    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if "User-Agent" not in (headers or {}):
        req.add_header("User-Agent", BROWSER_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        hint = ""
        if e.code == 401:
            hint = " — this layer 401s anonymously; it needs the proxy plus a Referer header"
        elif e.code == 403:
            hint = " — 403 on POST usually means a missing Referer; WebFetch also 403s some " \
                   "of these hosts, use curl"
        elif e.code == 404:
            hint = " — 404 here often means the request should have been a POST"
        elif e.code in (400, 414):
            hint = " — a long geometry, a % in a GET, or an unencoded space in a POST body"
        raise CountyFetchError("HTTP {} from {}{}".format(e.code, url, hint))
    except urllib.error.URLError as e:
        raise CountyFetchError("network error for {}: {}".format(url, e.reason))
    try:
        return json.loads(raw)
    except ValueError:
        raise CountyFetchError(
            "non-JSON response from {} ({} bytes). A WAF 403 on this host can look like an "
            "empty result set — check the raw body before believing a zero.".format(
                url, len(raw)))


def query_layer(cfg, where, fields, timeout=DEFAULT_TIMEOUT):
    params = {"where": where, "outFields": ",".join(fields),
              "returnGeometry": "false", "f": "json"}
    base = cfg.get("layer_url")
    if not base.rstrip("/").endswith("/query"):
        base = base.rstrip("/") + "/query"
    headers = dict(cfg.get("headers") or {})
    method = (cfg.get("http_method") or "GET").upper()

    if method == "POST":
        url, body = base, urllib.parse.urlencode(params)
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    else:
        url, body = base + "?" + urllib.parse.urlencode(params), None

    proxy = cfg.get("proxy")
    if proxy:
        # KGIS-style pass-through proxy: the whole target URL is the query string.
        target = base + "?" + urllib.parse.urlencode(params)
        url = proxy.replace("{urlencoded_target}", urllib.parse.quote(target, safe=""))
        method, body = "GET", None

    doc = http_get_json(url, headers, timeout, method=method, body=body)
    if isinstance(doc, dict) and doc.get("error"):
        raise CountyFetchError("layer error: {}".format(doc["error"]))
    return doc


def features_of(doc):
    feats = (doc or {}).get("features") or []
    return [f.get("attributes") or f.get("properties") or {} for f in feats]


# ---------------------------------------------------------------- row build


def first_present(attrs, names):
    """First non-blank value among candidate fields. .strip() everything.

    Union County writes ' ' for empty and 46.3% of address values carry trailing
    whitespace, so an unstripped truthiness test silently accepts a blank.
    """
    for n in names or []:
        v = attrs.get(n)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def join_present(attrs, names, sep=" "):
    parts = []
    for n in names or []:
        v = attrs.get(n)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            parts.append(s)
    return sep.join(parts)


def build_row(cfg, attrs, apn_raw):
    owner_raw = first_present(attrs, cfg.get("owner_fields"))
    mail = cfg.get("mail_fields") or {}
    street = join_present(attrs, mail.get("street"), sep=" ")

    city = state = zipc = ""
    csz_ok, csz_reason = None, ""
    mode = cfg.get("csz_mode") or "split"

    if mode == "combined":
        blob = first_present(attrs, [cfg.get("combined_csz_field")])
        parsed = octlib.csz_split(blob)
        city, state, zipc = parsed["city"], parsed["state"], parsed["zip"]
        csz_ok, csz_reason = parsed["ok"], parsed["reason"]
    elif mode == "packed_in_addr2":
        # Leon packs "CITY ST ZIP" into ADDR2: the LAST street line is really the CSZ.
        lines = [first_present(attrs, [n]) for n in (mail.get("street") or [])]
        lines = [l for l in lines if l]
        if len(lines) >= 2:
            parsed = octlib.csz_split(lines[-1])
            if parsed["ok"]:
                street = " ".join(lines[:-1])
                city, state, zipc = parsed["city"], parsed["state"], parsed["zip"]
                csz_ok, csz_reason = True, "parsed from packed ADDR2"
            else:
                csz_ok, csz_reason = False, parsed["reason"]
        zipc = zipc or first_present(attrs, [mail.get("zip")])
    else:
        city = first_present(attrs, [mail.get("city")])
        state = first_present(attrs, [mail.get("state")])
        zipc = first_present(attrs, [mail.get("zip")])
        if city or state or zipc:
            csz_ok = bool(state and state.upper() in octlib.STATE_CODES)
            csz_reason = "" if csz_ok else "state {!r} failed validation".format(state)

    situs = cfg.get("situs_fields") or {}
    norm = octlib.norm_owner(owner_raw)

    row = {
        "apn": apn_raw,
        "apn_norm": octlib.napn(apn_raw),
        "parcel_id": first_present(attrs, [cfg["parcel_id_field"]]) or None,
        "county": cfg["county"],
        "state": cfg["state"],
        "fips": cfg.get("fips"),
        "situs_address": first_present(attrs, [situs.get("street")]) or None,
        "situs_city": first_present(attrs, [situs.get("city")]) or None,
        "situs_zip": first_present(attrs, [situs.get("zip")]) or None,
        "owner_of_record": owner_raw or "",
        "owner_2": None,
        "owner_norm": norm["spaced"],
        "owner_tight": norm["tight"],
        "owner_base": octlib.strip_suffix(owner_raw),
        "owner_mailing_address": street,
        "mail_city": city,
        "mail_state": state,
        "mail_zip": zipc,
        "mail_csz_ok": csz_ok,
        "mail_csz_reason": csz_reason,
        "addr_key": octlib.addr_key(street, city, state, zipc),
        "naddr": octlib.naddr(street, " ".join([city, state, zipc]).strip()),
        "county_raw": {k: (str(v).strip() if v is not None else None)
                       for k, v in attrs.items()},
        "provenance": octlib.provenance(
            source="county layer {} ({})".format(cfg["county_key"], cfg.get("layer_url")),
            anchor_basis="parcel mailing address",
            identity_tier=1,
            confidence_basis="government assessor record, retrieved directly"),
    }

    # Knox packs both owners into one OWNER string. Splitting it here is what makes the
    # spouse reachable; marking owner_2 REQ for this county instead would report a
    # permanent false gap.
    if cfg.get("owner_field_packs_both_owners") and owner_raw:
        parts = octlib.split_owner_string(owner_raw)
        if len(parts) > 1:
            row["owner_2"] = parts[1]
            row["owner_split"] = parts

    # A situs that equals the mailing address is a signal, not a contact axis.
    if row["situs_address"] and street:
        row["situs_equals_mailing"] = (
            octlib.naddr(row["situs_address"]) == octlib.naddr(street))

    if not (cfg.get("mail_fields") or {}):
        row["mail_class_note"] = (
            "this layer publishes no owner mailing fields — owner_mailing_address is "
            "explicitly-unavailable, not missing")
    return row


# ---------------------------------------------------------------- fetch


def fetch(county_key, apn, fixture=None, no_cache=False, max_age_s=86400, timeout=DEFAULT_TIMEOUT):
    cfg = load_config(county_key)
    fields = requested_fields(cfg)
    where = build_where(cfg, apn)

    if cfg.get("adapter_kind") == "web_grid":
        raise CountyFetchError(
            "{} is a web-grid adapter, not an ArcGIS layer. Its POST form contract is in "
            "config/counties/{}.json under 'form_contract'; it is NOT IMPLEMENTED in this "
            "build. Emit a named gap rather than a zero.".format(county_key, county_key))

    if fixture:
        doc = json.loads(pathlib.Path(fixture).read_text(encoding="utf-8"))
        source = "fixture:" + os.path.basename(fixture)
    else:
        cp = cache_path(county_key, fields, where)
        doc = None if no_cache else cache_get(cp, max_age_s)
        source = "cache" if doc else "live"
        if doc is None:
            doc = query_layer(cfg, where, fields, timeout=timeout)
            attrs = features_of(doc)
            if not attrs and (cfg.get("parcel_id_format") or {}).get("double_space"):
                # Documented Knox fallback: interleaved wildcard, then client-side
                # normalized equality. Never trust the loose match as-is.
                doc = query_layer(cfg, "{} LIKE '{}'".format(
                    cfg["parcel_id_field"], interleaved_wildcard(apn)), fields, timeout=timeout)
            cache_put(cp, doc)

    rows = []
    want = octlib.napn(apn)
    for attrs in features_of(doc):
        row = build_row(cfg, attrs, apn)
        got = octlib.napn(row.get("parcel_id") or "")
        if want and got and not (got == want or got.startswith(want)):
            continue                       # client-side normalized equality
        row["fetch_source"] = source
        rows.append(row)
    return cfg, rows


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="county_fetch.py",
        description="Per-county adapter: resolve a parcel id to a census row from the "
                    "county assessor layer. Free; spends nothing.")
    ap.add_argument("--county", required=True, help="adapter key, e.g. tn_knox, fl_duval")
    ap.add_argument("--apn", required=True, help="parcel id in county-native format")
    ap.add_argument("--fixture", help="replay a recorded layer response instead of the "
                                      "network (used by the offline test suite)")
    ap.add_argument("--no-cache", action="store_true", help="bypass the feature cache")
    ap.add_argument("--max-age", type=int, default=86400,
                    help="cache max age in seconds (default 86400)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--json", action="store_true", help="emit JSON rather than a summary")
    ap.add_argument("--list-counties", action="store_true",
                    help="list available adapter keys and exit")
    args = ap.parse_args(argv)

    if args.list_counties:
        for p in sorted(config_dir().glob("*.json")):
            print(p.stem)
        return 0

    try:
        cfg, rows = fetch(args.county, args.apn, fixture=args.fixture,
                          no_cache=args.no_cache, max_age_s=args.max_age,
                          timeout=args.timeout)
    except NoCountyAdapter as e:
        print(str(e), file=sys.stderr)
        return 3
    except CountyFetchError as e:
        print("county_fetch failed: {}".format(e), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"county_key": args.county, "apn": args.apn,
                          "retrieved_at": octlib.utcnow_iso(), "rows": rows},
                         indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print("no features matched {} in {} — disposition NO-OWNER-NAME after one retry"
              .format(args.apn, args.county))
        return 1
    for r in rows:
        print("APN            {}  ({})".format(r["apn"], r["apn_norm"]))
        print("owner          {!r}".format(r["owner_of_record"]))
        if r.get("owner_split"):
            print("owner split    {}".format(r["owner_split"]))
        print("situs          {}".format(r.get("situs_address")))
        print("mailing        {} | {} {} {}".format(
            r["owner_mailing_address"], r["mail_city"], r["mail_state"], r["mail_zip"]))
        print("addr_key       {}".format(r["addr_key"]))
        if r.get("situs_equals_mailing") is False:
            print("note           situs != mailing (absentee) — situs is not a contact axis")
        if r.get("mail_csz_ok") is False:
            print("WARN           csz parse failed: {}".format(r.get("mail_csz_reason")))
        print("source         {}".format(r.get("fetch_source")))
    for t in (cfg.get("traps") or [])[:3]:
        print("trap           {}".format(t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
