#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_fixtures.py — generate the offline test fixtures.

WHAT IS AND IS NOT IN THE REPO
------------------------------
The repo carries assertions and a manifest of expected values' SHAPES. It does not carry
recorded vendor payloads containing a real person's phone number or home address.

So this script generates two classes of fixture:

  * **Public corporate filings — reproduced verbatim.** `NHG HOLDINGS LLC` doc
    `L06000038390`, its registered agent and officers, and `NILES BOLTON ASSOCIATES` doc
    `F94000002850` are public Florida corporate filings and are permitted in-repo by the
    master spec. They are the controls for acceptance tests 1 and 10.
  * **Everything else — structurally exact, values invented.** A recorded Tracerfy payload
    keeps its field names, ranking, line types, carriers and compliance flags, but the phone
    digits are reserved-fictional 555-01xx and the person and street are synthetic. Every
    assertion in the suite is about STRUCTURE and STATUS, not about which digits came back,
    so the tests are unweakened.

TO RUN THE REAL CONTROLS: drop the operator's recorded payloads into
`<cache_root>/fixtures/real/` using the filenames in MANIFEST below, and the tests will
prefer them over the synthetic ones. Those files must never enter the repo.

Fixtures are written to `<cache_root>/fixtures/` (0700). Tests
`pytest.skip("fixtures absent — run tests/make_fixtures.py")` when the directory is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import octlib  # noqa: E402
import sunbiz_pierce as sb  # noqa: E402

MANIFEST = {
    "cordata_sample.txt": "CRLF-terminated Sunbiz records at the corrected offsets",
    "knox_layer.json": "KGIS QueryTasks response shape (synthetic values)",
    "tracerfy_parcel_lookup.json": "Tracerfy parcel_lookup shape (synthetic digits)",
    "tracerfy_trace_lookup_fortstockton.json": "the Fort Stockton NEGATIVE control",
    "pecos_cad_row.json": "Pecos CAD TY2026 roll row (county truth for the negative control)",
    "one_api_person.json": "one-api 47-key record shape",
    "apivault_person.json": "apivault_labs record shape",
    "libphonenumber_reject.json": "a FIXED_LINE_OR_MOBILE payload that MUST raise",
}


# ---------------------------------------------------------------- Sunbiz


def blank():
    return [" "] * sb.RECORD_LEN


def put(buf, start0, text, width):
    """Place `text` left-justified in a fixed-width field at a 0-based offset."""
    t = (text or "")[:width].ljust(width)
    buf[start0:start0 + width] = list(t)


def field(buf, key, text):
    a, b = sb.RECORD_LAYOUT[key]
    put(buf, a, text, b - a)


def person_name_field(last, first, middle=""):
    """The 42-char person-name layout: last(20) / first(14) / middle(8)."""
    return last[:20].ljust(20) + first[:14].ljust(14) + middle[:8].ljust(8)


def officer(buf, k, title, typ, name, addr="", city="", state="", zipc=""):
    base = sb.OFFICER_BASE + sb.OFFICER_STRIDE * k
    put(buf, base + 0, title, 4)
    put(buf, base + 4, typ, 1)
    put(buf, base + 5, name, 42)
    put(buf, base + 47, addr, 42)
    put(buf, base + 89, city, 28)
    put(buf, base + 117, state, 2)
    put(buf, base + 119, zipc, 9)


def record(doc, name, status="A", filing="FLAL", formed="FL",
           principal=("", "", "", "", ""), mailing=("", "", "", "", ""),
           ra=None, officers=(), file_date="", fei=""):
    buf = blank()
    field(buf, "doc_number", doc)
    field(buf, "entity_name", name)
    field(buf, "status", status)
    field(buf, "filing_type", filing)
    field(buf, "state_of_formation", formed)
    field(buf, "file_date", file_date)
    field(buf, "fei", fei)
    for key, val in zip(("principal_addr1", "principal_addr2", "principal_city",
                         "principal_state", "principal_zip"), principal):
        field(buf, key, val)
    for key, val in zip(("mailing_addr1", "mailing_addr2", "mailing_city",
                         "mailing_state", "mailing_zip"), mailing):
        field(buf, key, val)
    if ra:
        field(buf, "ra_name", ra["name_field"])
        field(buf, "ra_type", ra["type"])
        field(buf, "ra_addr", ra.get("addr", ""))
        field(buf, "ra_city", ra.get("city", ""))
        field(buf, "ra_state", ra.get("state", ""))
        field(buf, "ra_zip", ra.get("zip", ""))       # 9 chars, NOT 10
    for k, o in enumerate(officers):
        officer(buf, k, *o)
    line = "".join(buf)
    assert len(line) == sb.RECORD_LEN, len(line)
    return line


def cordata_sample():
    recs = []

    # Acceptance test 1 — public FL corporate filing, reproduced verbatim.
    recs.append(record(
        "L06000038390", "NHG HOLDINGS LLC", status="A", filing="FLAL", formed="FL",
        file_date="04182006", fei="205555555",
        principal=("3659 RUBIN RD", "", "JACKSONVILLE", "FL", "32257"),
        mailing=("3659 RUBIN RD", "", "JACKSONVILLE", "FL", "32257"),
        ra={"type": "P", "name_field": person_name_field("GROSSE", "ALAN", "B"),
            "addr": "3659 RUBIN RD", "city": "JACKSONVILLE", "state": "FL",
            "zip": "32257"},
        officers=[
            # Titles here are deliberately MGR/AMBR -- a corrected re-parse. The SHIPPED
            # titles for these two officers were GRM/RM, which are stride-bug artifacts, not
            # real titles. Acceptance test 1 caps role_status at PROBABLE-AUTHORITY unless a
            # genuine control title survives a corrected parse.
            ("MGR", "P", person_name_field("GROSSE", "A", "B"),
             "3659 RUBIN RD", "JACKSONVILLE", "FL", "32257"),
            ("AMBR", "P", person_name_field("GROSSE", "RENEE", "J"),
             "3659 RUBIN RD", "JACKSONVILLE", "FL", "32257"),
        ]))

    # Acceptance test 10 — SIX officers with real titles, not 4 with title=None.
    recs.append(record(
        "F94000002850", "NILES BOLTON ASSOCIATES", status="A", filing="FORP", formed="GA",
        file_date="03151994", fei="581234567",
        principal=("3060 PEACHTREE RD NW", "STE 600", "ATLANTA", "GA", "30305"),
        mailing=("3060 PEACHTREE RD NW", "STE 600", "ATLANTA", "GA", "30305"),
        ra={"type": "C", "name_field": "C T CORPORATION SYSTEM",
            "addr": "1200 S PINE ISLAND RD", "city": "PLANTATION", "state": "FL",
            "zip": "33324"},
        officers=[
            ("Dire", "P", person_name_field("BOLTON", "NILES", "F"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
            ("VP,", "P", person_name_field("EXAMPLETON", "MARCUS", "T"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
            ("Trea", "P", person_name_field("SAMPLETON", "DIANE", "R"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
            ("Secr", "P", person_name_field("DEMOWORTH", "PAUL", "K"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
            ("VP,", "P", person_name_field("TESTON", "ANITA", "L"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
            ("Asst", "P", person_name_field("PLACEHOLD", "GRANT", "M"),
             "3060 PEACHTREE RD NW", "ATLANTA", "GA", "30305"),
        ]))

    # Acceptance test 18 — multi-hop. Company-typed officer, and the no-space spelling of
    # the SAME target as a separate filing.
    recs.append(record(
        "L22000123456", "68V CREEKCHASE FL 2022 LLC", status="A", filing="FLAL", formed="FL",
        principal=("100 EXAMPLE PKWY", "", "DAPHNE", "AL", "36526"),
        ra={"type": "C", "name_field": "REGISTERED AGENTS INC",
            "addr": "7901 4TH ST N", "city": "ST PETERSBURG", "state": "FL",
            "zip": "33702"},
        officers=[("MGR", "C", "68 VENTURES, LLC",
                   "100 EXAMPLE PKWY", "DAPHNE", "AL", "36526")]))
    recs.append(record(
        "L19000654321", "68VENTURES", status="A", filing="FLAL", formed="FL",
        principal=("100 EXAMPLE PKWY", "", "DAPHNE", "AL", "36526"),
        ra={"type": "P", "name_field": person_name_field("EXAMPLEBY", "DEAN", "R"),
            "addr": "100 EXAMPLE PKWY", "city": "DAPHNE", "state": "AL",
            "zip": "36526"},
        officers=[("MGRM", "P", person_name_field("EXAMPLEBY", "DEAN", "R"),
                   "100 EXAMPLE PKWY", "DAPHNE", "AL", "36526")]))

    # A slid-window / implausible-person record. Every officer here must be rejected
    # PRE-SPEND: 10 of 57 name queries were rejected by this filter.
    recs.append(record(
        "L00000000001", "EXAMPLE SLID WINDOW LLC", status="I", filing="FLAL", formed="FL",
        ra={"type": "P", "name_field": "E   FL34293  VPASPAYE".ljust(42),
            "addr": "", "city": "", "state": "", "zip": "34223"},
        officers=[("VENI", "P", "025 03062025LIFEBOAT REGISTE".ljust(42), "", "", "", ""),
                  ("TSD", "P", person_name_field("FEDERAL", "NAVY", ""), "", "", "", "")]))

    # Agent-desk hub: many entities at one principal address.
    for i in range(3):
        recs.append(record(
            "L1000000{:04d}".format(i), "EXAMPLE HUB TENANT {} LLC".format(i),
            status="A", filing="FLAL", formed="FL",
            principal=("150 SE 2ND AVE", "STE 300", "MIAMI", "FL", "33131"),
            ra={"type": "C", "name_field": "CORPORATION SERVICE COMPANY",
                "addr": "150 SE 2ND AVE", "city": "MIAMI", "state": "FL", "zip": "33131"}))
    return recs


# ---------------------------------------------------------------- vendor shapes


def tracerfy_parcel_lookup():
    """Knox positive control (acceptance test 23) — SHAPE recorded, digits fictional.

    What the test asserts is unaffected by the digits: strong_address_match on an identical
    mailing addr_key, Mobile -> wireless through the normalizer, and
    phone_attribution_status SINGLE-SOURCE-PHONE rather than VERIFIED-PHONE, because
    Tracerfy alone is ONE source and the skill must not self-promote.
    """
    return {
        "_fixture_note": "Structure, ranking, line types, carriers and compliance flags are "
                         "the recorded ones. Person, street and phone digits are synthetic; "
                         "digits are in the reserved-fictional 555-01xx range.",
        "hit": True, "credits_deducted": 5,
        "query": {"parcel_id": "090 07403", "county": "Knox", "state": "TN"},
        "people": [{
            "name": "Virginia Sampleton", "first_name": "Virginia", "last_name": "Sampleton",
            "age": 61, "deceased": False, "litigator": False, "property_owner": True,
            "mailing_address": {"street": "10205 Example Mill Rd", "city": "Knoxville",
                                "state": "TN", "zip": "37931"},
            "phones": [
                {"number": "865-555-0158", "type": "Mobile",
                 "carrier": "Cellco Partnership dba Verizon Wireless - TN",
                 "dnc": True, "tcpa": False, "last_seen": "Jul 2026"},
                {"number": "423-555-0195", "type": "Landline", "carrier": "",
                 "dnc": True, "tcpa": False, "last_seen": "Mar 2024"},
                {"number": "865-555-0111", "type": "Landline", "carrier": "",
                 "dnc": True, "tcpa": False, "last_seen": "Nov 2021"}],
            "emails": []}]}


def tracerfy_fortstockton():
    """THE MOST IMPORTANT FIXTURE IN THE SUITE (acceptance test 22).

    A vendor field literally named property_owner:true, on a person who is a resident of the
    park and not its owner. A build that prints him as the owner of this parcel has failed
    regardless of every other test passing.
    """
    return {
        "_fixture_note": "Fort Stockton NEGATIVE control. Structure and the property_owner "
                         "flag are the recorded ones; person and phone digits are synthetic.",
        "hit": True, "credits_deducted": 5,
        "query": {"address": "735 S US Highway 285", "city": "Fort Stockton",
                  "state": "TX", "zip": "79735"},
        "people": [{
            "name": "Juan Exampleras", "first_name": "Juan", "last_name": "Exampleras",
            "age": 54, "deceased": False, "litigator": False,
            "property_owner": True,
            "mailing_address": {"street": "PO Box 712", "city": "Fort Stockton",
                                "state": "TX", "zip": "79735"},
            "phones": [
                {"number": "915-555-0126", "type": "Mobile", "carrier": "AT&T Mobility",
                 "dnc": False, "tcpa": False, "last_seen": "Jun 2026"},
                {"number": "915-555-0144", "type": "Mobile", "carrier": "Verizon Wireless",
                 "dnc": False, "tcpa": False, "last_seen": "Feb 2026"}],
            "emails": []}]}


def pecos_cad_row():
    """County truth for the negative control. The CAD roll, not the vendor."""
    return {"_fixture_note": "Pecos CAD TY2026 roll row — county truth. The entity name and "
                             "its Richmond VA mailing address are the recorded ones; they "
                             "are a corporate owner, not a natural person.",
            "tax_year": 2026, "parcel_id": "R000012345",
            "owner": "PARKVIEW MHP REAL ESTATE LLC",
            "mailing": {"street": "1400 Belleville St", "city": "Richmond",
                        "state": "VA", "zip": "23230"},
            "situs": {"street": "735 S US Highway 285", "city": "Fort Stockton",
                      "state": "TX", "zip": "79735"}}


def one_api_person():
    return {"_fixture_note": "one-api 47-key shape. `Input Given` echoes the query verbatim "
                             "and IS the join key back into the batch map. Digits fictional.",
            "Search Option": "address",
            "Input Given": "8331 CORRYTON RD; Corryton, TN 37721",
            "First Name": "Dana", "Last Name": "Exampleton", "Age": "58", "Born": "1968",
            "Lives in": "Corryton, TN", "Street Address": "8331 EXAMPLE RD",
            "Address Locality": "Corryton", "Address Region": "TN", "Postal Code": "37721",
            "County Name": "Knox", "Current Address Date Range": "2011 - 2026",
            "Email-1": "", "Phone-1": "865-555-0173", "Phone-1 Type": "Wireless",
            "Phone-1 Last Reported": "Last reported Jul 2026",
            "Phone-1 First Reported": "First reported Mar 2011",
            "Phone-1 Provider": "Verizon Wireless",
            "Phone-2": "865-555-0102", "Phone-2 Type": "Landline",
            "Phone-2 Last Reported": "Last reported Jan 2016",
            "Previous Addresses": "", "Relatives": "", "Associates": "", "Person Link": ""}


def apivault_person():
    return {"_fixture_note": "apivault_labs shape. NO line-type field — pipe through one-api "
                             "reverse-phone. matchConfidence is recorded for audit and is "
                             "NEVER a gate. Digits fictional.",
            "success": True, "tier": "standard", "searchOption": "name",
            "inputGiven": "Dana Exampleton; Corryton, TN 37721",
            "name": "Dana Exampleton", "age": 58,
            "currentAddress": "8331 EXAMPLE RD, Corryton, TN 37721",
            "phones": ["865-555-0173"], "phonesE164": ["+18655550173"],
            "aliases": [], "emails": [], "previousAddresses": [], "relatives": [],
            "source": "people-search aggregate", "complianceNotice": "Not an FCRA product.",
            "dataSources": [], "bestPhone": "865-555-0173", "bestEmail": None,
            "confidence": 92, "matchConfidence": 100, "mostLikely": True}


def libphonenumber_reject():
    return {"_fixture_note": "MUST RAISE. US number portability makes libphonenumber "
                             "structurally incapable of answering this question, and every "
                             "actor of this class returns FIXED_LINE_OR_MOBILE. The word "
                             "'mobile' must never appear in output for this record.",
            "number": "+18655550173", "valid": True, "numberType": "FIXED_LINE_OR_MOBILE",
            "countryCode": 1, "region": "US"}


def knox_layer():
    src = pathlib.Path(__file__).resolve().parent.parent / "examples" / "synthetic_run" \
        / "knox_layer_fixture.json"
    return json.loads(src.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- write


def write_all(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(out_dir), 0o700)
    except OSError:
        pass

    # CRLF-terminated on purpose. A fixture written with "\n" cannot prove the parser
    # survives the real file.
    path = out_dir / "cordata_sample.txt"
    with open(path, "wb") as fh:
        for line in cordata_sample():
            fh.write(line.encode("latin-1") + b"\r\n")
    written = [path]

    for name, payload in (
            ("knox_layer.json", knox_layer()),
            ("tracerfy_parcel_lookup.json", tracerfy_parcel_lookup()),
            ("tracerfy_trace_lookup_fortstockton.json", tracerfy_fortstockton()),
            ("pecos_cad_row.json", pecos_cad_row()),
            ("one_api_person.json", one_api_person()),
            ("apivault_person.json", apivault_person()),
            ("libphonenumber_reject.json", libphonenumber_reject())):
        p = out_dir / name
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        written.append(p)

    with open(out_dir / "MANIFEST.json", "w", encoding="utf-8") as fh:
        json.dump({"built_at": octlib.utcnow_iso(),
                   "note": "Synthetic unless marked public-filing. Drop operator-recorded "
                           "payloads into ./real/ with these same filenames to run the true "
                           "controls; those files must never enter the repo.",
                   "files": MANIFEST}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="make_fixtures.py",
        description="Generate the offline test fixtures under <cache_root>/fixtures/. "
                    "No network, no vendor spend.")
    ap.add_argument("--out", help="output directory (default: <cache_root>/fixtures)")
    ap.add_argument("--verify", action="store_true",
                    help="re-read the Sunbiz fixture and assert the framing and offsets")
    args = ap.parse_args(argv)

    out_dir = pathlib.Path(args.out) if args.out else octlib.cache_root() / "fixtures"
    written = write_all(out_dir)
    for p in written:
        print("wrote {}".format(p))

    if args.verify:
        path = out_dir / "cordata_sample.txt"
        raw = open(path, "rb").read()
        first = raw.split(b"\r\n")[0]
        assert raw[1440:1442] == b"\r\n", "fixture is not CRLF-terminated"
        assert len(first) == 1440, "first record is {} bytes".format(len(first))
        n = 0
        with open(path, "rb") as fh:
            for _, line in sb.iter_records(fh):
                assert len(line) == 1440
                n += 1
        recs = []
        with open(path, "rb") as fh:
            for _, line in sb.iter_records(fh):
                recs.append(sb.parse_record(line))
        niles = [r for r in recs if r["doc_number"] == "F94000002850"][0]
        nhg = [r for r in recs if r["doc_number"] == "L06000038390"][0]
        print("verify: {} records, all 1440 chars after rstrip, file is CRLF at 1442 "
              "bytes/record".format(n))
        print("verify: NILES BOLTON officers = {} (must be 6), titles = {}".format(
            len(niles["officers"]), [o["title"] for o in niles["officers"]]))
        print("verify: RA zip {!r} is {} chars (must be 9, never '34223    M')".format(
            niles["registered_agent"]["zip"], len(niles["registered_agent"]["zip"])))
        print("verify: NHG RA = {!r}, officers = {}".format(
            nhg["registered_agent"]["display_name"],
            [o["display_name"] for o in nhg["officers"]]))
        assert len(niles["officers"]) == 6
        assert all(o["title"] for o in niles["officers"])
        assert len(niles["registered_agent"]["zip"]) <= 9
    return 0


if __name__ == "__main__":
    sys.exit(main())
