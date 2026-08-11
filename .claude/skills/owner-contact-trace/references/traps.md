# Traps — symptom → cause → fix

Read this when something returns empty, 403s, 404s, or silently loses rows. Every entry is
symptom → cause → fix, in that shape. What *not to build at all* lives in
`references/dead_ends.md`, not here.

**Contents**

- [Vendor](#vendor)
- [Join](#join)
- [Cache](#cache)
- [Registry](#registry)
- [County](#county)
- [Deliverable](#deliverable)

Phone numbers in the examples below are reserved-fictional `555-01xx` placeholders. The
*formats* are the ones that matter and they are exact.

---

## Vendor

**one-api returns `First Name: "Person Not Found" / Last Name: "Invalid Adddress Format"`**
*(their typo, three d's)*
→ **Cause:** the submitted address has no ZIP.
→ **Fix:** always submit `street, city ST zip`. A 196-address run without ZIPs cost $1.40 and
returned nothing.

**Name-vs-address input separators are wrong and the batch returns nothing**
→ **Cause:** the separator was *asserted* rather than probed. The 2026-08-04 observation was
that `apivault` name input takes a **comma** and `one-api` address input a **semicolon**; the
live apivault schema (modified **2026-08-08**) documents `"Jane Doe; Springfield, IL 62704"` —
a **semicolon** — and `one-api`'s name field says the same.
→ **Fix:** before any batch, `vendor_client.py` fires the *same* known-answer name in both
forms at `max_results: 1` (≈$0.013) and adopts whichever returns a record, logging the winner
with a date. Never hard-code the separator.

**Sherpa `/api/business` returns `404 / expected_results 0` with no error**
→ **Cause:** `business_name` was sent alone.
→ **Fix:** add `mailing_address` **plus `omit_registered_agents: true`**. ZIP presence does
*not* matter: with zip 154×404 / 72×200, without 31×404 / 34×200.

**Sherpa `success_criteria: "owner-contact-phone"` 404s when phones demonstrably exist**
→ **Cause:** that is not a valid value.
→ **Fix:** use `"owner-name"`. **`owner_mobile_enrichment/scripts/pierce_entities_apn.py:59`
still sends the broken value; `sherpa_apn.py:117` sends the correct one while its own docstring
at line 9 shows the broken one — the docstring is stale, the code is right.** Grep any lifted
script for `owner-contact-phone` before running it.

**Sherpa returns 403 `error code: 1010` on urllib**
→ **Cause:** Cloudflare UA ban, not auth.
→ **Fix:** curl with a browser UA.

**A Sherpa key is rejected — but which kind of rejected?**
→ **Cause:** two distinct dead-key strings mean different things.
`"API Key is not active or is not valid anymore"` = recognized but deactivated (the
pre-rotation key). `"Invalid API Key"` = not recognized at all (the 2026-08-10 replacement).
→ **Fix:** probe for both and report which.

**A whole Sherpa batch 429s and nothing comes back**
→ **Cause:** the quota rejection is **atomic** — the batch is rejected whole and unbilled.
→ **Fix:** batch at 10 and trap 429. The hard cap is 25 lookups/request.

**A batch returns 0 items and the normalizer looks wrong**
→ **Cause:** it may be a transient rate limit, not malformed input. Four different address
spellings returned identical people.
→ **Fix:** A/B isolate before rewriting the normalizer.

**BatchData returns `errorCount: 0, matchCount: 0`**
→ **Cause:** this is a coverage gap, and it is **indistinguishable from a bad request**.
→ **Fix:** confirm liveness separately with the zero-cost auth probe: `POST {}` → 400
field-validation means live, 401 means dead.

**Melissa returns `GE05` on a key you just pasted**
→ **Cause:** **Melissa's `**` is part of the key, not masking.** Keys are 24 chars ending
`**`, so an *interior* `**` means the field holds TWO keys run together (box 2 did; pasting it
wholesale yields `GE05`).
→ **Fix:** split with `re.findall(r".+?\*\*", s)` after a whitespace split.

Melissa key-error table — `SE##` and `GE##` must raise, never pass silently:

| Code | Meaning |
|---|---|
| `GE04` | empty |
| `GE05` | invalid |
| `GE06` | disabled |
| `GE08` | valid key but product not enabled |
| `GE09` | unknown customer id |
| `GE10` / `GE11` | licence / customer disabled |

Success codes `YS02/YS04/YS05/YS06/YS07`; misses `YE01/YE02/YE03`.
Endpoints: `POST /v4/WEB/LookupProperty` (batch 100), `GET /v4/WEB/LookupDeeds`,
`GET /v4/WEB/LookupHomesByOwner`, `GET /v4/WEB/LookupListings`. Column preset `owner` =
`GrpPropertyAddress,GrpPrimaryOwner,GrpOwnerAddress,GrpLastDeedOwnerInfo`.
Support: tech@melissadata.com, 800-635-4772 ext. 3, account **121039763** registered to
mitchgonzalez5@gmail.com — **so the sender must be that gmail address.**

---

## Join

**The pierce produced 69 officer-address results and the call list got no better — 0
additional parcels contacted**
→ **Cause:** the call-list builder indexed vendor results under the **parcel's** mailing
address only, so hits keyed to a principal's *own filed address* never matched anything.
→ **Fix:** index on **both** address keys, recording which one matched:
`anchor_basis = "parcel mailing address"` | `"Sunbiz-filed address of <PRINCIPAL>"`.
**+11 parcels immediately (82 → 93).**

**Rows then duplicated after that fix**
→ **Cause:** each person was now indexed under two keys.
→ **Fix:** **dedupe on the person, not the address.**

---

## Cache

**Owner and mailing columns come back blank on rows the layer definitely has — 85 of 233 FL
rows, config correct, writer correct, nothing errors**
→ **Cause:** the parcel-feature cache was keyed on **county name only, with no field list in
the key**, so adding mailing fields to the config silently reused features fetched before
those fields existed.
→ **Fix:** **hash the requested field list into the cache key.** Then ship a *targeted*
backfill — 233 APNs → 233/233 resolved, 232 with mailing, reverse-address-eligible rows
73 → 97 — rather than re-running a 50,000-parcel pipeline.

---

## Registry

**RA zip reads `'34223    M'`**
→ **Cause:** a 10-char read of a 9-char field.
→ **Fix:** RA zip is bytes `660–668` — **9 chars, not 10.**

**Officer titles come back `None` / `GR` / `RM`, and officers 2–6 are missing entirely**
→ **Cause:** the shipped parser used `ra_start + 125` with stride **129**.
→ **Fix:** officers are at **`669 + 128·k`, k = 0..5**. `GRM`/`GR`/`RM` were never real
titles — they are artifacts of this bug, which is why they are dropped from `CONTROL_TITLES`.

**Parsed names like `"025 03062025LIFEBOAT REGISTE"`**
→ **Cause:** an offset scan landing on annual-report-year digits.
→ **Fix:** use the fixed offsets, and reject any parsed name containing `\d{4}` or an
`[A-Z]{2}\d` run — that is a slid window (`'E   FL34293  VPASPAYE'`).

**Officer parse is only ~60% clean — `FEDERAL NAVY`, `FUNERAL SCI`, `MINERAL CONTINENTAL`,
initial-only tokens**
→ **Cause:** fixed-width fields carry non-name content and registrant free text.
→ **Fix:** run every surviving name through a **person-plausibility filter before paying**.
10 of 57 name queries were rejected pre-spend.

**The registry/deed trail shows a purchase date that does not match who controls the entity
now**
→ **Cause:** **entity-interest purchases leave no deed and never change the CAD owner name.**
The trail dates the *entity's* purchase, not current control.
→ **Fix:** label `RECORD-OWNER-RESOLVED / BENEFICIAL-CONTROL-UNKNOWN`. The ClearTrail
Houston/Dallas-formation versus Richmond-VA-tax-mail split is the tell.

---

## County

The full per-county trap set lives in `references/county_access.md` (Knox double-space and the
401/403/404/414 matrix; Pecos CAD `SearchTableV2` and the silently-ignored `taxYear`; Orange
FL's WAF and `<`/`>`; Seminole GET-only; Escambia encoding; Collier unreachable; Leon's packed
`ADDR2`; Indian River's dead legacy hosts; NYS `PRINT_KEY` non-uniqueness and the `0,0`
centroid; Union NC's `ACCTNO`, `JAN1_*` and whitespace; Esri ring orientation; stale viewers;
the client's own sheet being wrong).

Two that belong here because they are not county-specific:

**A mailing address masquerades as a situs address**
→ **Cause:** a layer exposing one field under the other's name.
→ **Fix:** compare the situs field against the mailing field explicitly. Never assume.

**A CAD street-number filter loses parcels that exist**
→ **Cause:** number filters are unreliable across CADs.
→ **Fix:** always re-query by owner name.

---

## Deliverable

**Raw harvested text in a workbook column leaked 72 cleartext passwords into the iCloud root**
*(deleted 2026-08-07 — the Bane incident)*
→ **Cause:** raw source text was written straight into a deliverable column.
→ **Fix:** emit the **matched rule plus a scrubbed snippet**, never raw source. And keep every
intermediate out of any synced tree.

**The redaction regex misses real numbers**
→ **Cause:** the inherited pattern `\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b` misses `(314) 555-0177`
and `+1 (630) 555-0195`.
→ **Fix:** `octlib.PHONE_RE` handles the parenthesized and `+1` forms and is the single
definition `leak_scan.py` uses (acceptance test 16).

**Four "hits" across 36 addresses all share one number**
→ **Cause:** a toll-free scraper artifact. The signature is a detectable constant:
`+1-855-723-2747`.
→ **Fix:** blocklist it; treat any repeated cross-owner number as an artifact until proven
otherwise.

**`distinct_owner_count` is inflated**
→ **Cause:** Regrid/Placecraft split one human into multiple owners on string variation.
→ **Fix:** cluster with `octlib.fuzzy_owner_merge_ok()` — bounded Levenshtein ≤2, and **only**
between owners already sharing a mailing address.

**Grouping loses rows when one parcel lists a joint owner and another does not**
→ **Cause:** grouping on the raw `Owner Full Name` string.
→ **Fix:** **group on last-name-or-business + mailing address, never on the raw full-name
string.**

**Contact counts are inflated**
→ **Cause:** the dedupe signature `(re.sub(r"[^a-z]","",name.lower()), re.sub(r"\D","",p1))`
includes the phone, so **one human with two numbers survives as two contacts**.
→ **Fix:** dedupe on the person. If you choose not to, **state it in the deliverable** — do
not let the count stand unqualified.

**APN lists are truncated**
→ **Cause:** the source builder capped `apns` at 12.
→ **Fix:** **do not inherit that.** `octlib.split_apns()` never truncates and
`schemas/call_list.schema.json` documents `apns` as uncapped.

**A transplanted script produces a previous parcel's numbers**
→ **Cause:** hardcoded strings from a prior parcel survive the transplant. Four instances in
one run: `f7_geology_karst.py:155` and `a1_gis_facts.py` ×3.
→ **Fix:** grep every adapted script for the previous parcel's APN, owner, acreage and place
names before running it. `validate_skill.py` checks for absolute paths and hardcoded dates;
the parcel-string check is manual.

**QA passes but the deliverable over-claims**
→ **Cause:** the adversarial judge never finds arithmetic errors, only interpretive
over-claiming.
→ **Fix:** prefer *"this run does not establish X"* to a hedged estimate of X.
