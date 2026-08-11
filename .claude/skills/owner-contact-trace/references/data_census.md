# The data census — `CENSUS.json`

Stage 1 builds `CENSUS.json`, the complete identity inventory, and **no paid call may fire
while any REQ field is `missing`** (as distinct from `explicitly-unavailable`).

`census.py --coverage` emits `CENSUS_COVERAGE.json` — per REQ field, three counts:
`populated` / `explicitly-unavailable` / `missing` — validated against
`schemas/census_coverage.schema.json`. That file is what the budget gate reads.

---

## The "Source" column is a per-county field map, not a global schema

The literal field names live in `config/counties/*.json`. The table below names the
**concept**.

The draft's `CURR_*` names are **Union County NC only**. Knox has `OWNER` (one string carrying
both owners — `FUGATE RONALD ALLEN & VIRGINIA M`), `FULL_MAIL_ADDRESS`, and a single combined
`FULL_MAIL_CITY_STATE_ZIP`.

---

## Field table

| Field | Source (per-county field map) | Req before paid call | What breaks if missing |
|---|---|---|---|
| `apn` (raw) + `apn_norm` | county GIS/assessor | **REQ** | No join key; every deliverable is APN-keyed |
| `parcel_id` / `acctno` | county | OPT | `ACCTNO` is **not** the parcel key (Union NC); anti-join before use |
| `county`, `state` | list/source | **REQ** | County gate impossible; BatchData/Sherpa reject |
| `fips` (5-digit) | Census **batch** geocoder (free, keyless) or hardcoded map | PREF | Falls back to string county matching |
| `situs_address/city/zip` | county situs field | PREF | Deal-email header rule; **never confuse with the mailing field** |
| `owner_of_record` (raw) | assessor primary owner name | **REQ** | Root of everything; blank → retry county, then `NO-OWNER-NAME` |
| `owner_2` | assessor second owner name | **per-county OPT** | The spouse the trace needs. Knox packs both into one string — mark OPT per county or Knox reports a permanent false gap |
| `owner_norm` (spaced) + `owner_tight` | derived | **REQ** | Tight form caught 13 `C S X TRANSPORTATION` parcels |
| `owner_base` (suffix-stripped) | derived | **REQ for SoS match** | `ET AL` / trailing `+` caused 3 registry misses |
| `owner_class` / `entity_type` | classifier | **REQ** | Routes: individual → trace, entity → pierce, trust → deed, gov → suppress |
| `owner_mailing_address` (+city/state/**zip**) | assessor mailing fields | **REQ** | This *is* the anchor. No ZIP → `one-api` returns "Invalid Adddress Format" |
| `mail_csz` split → city/state/zip | derived, `csz_split()` | **REQ** | Knox ships `"KNOXVILLE, TN 37931"` as one field; naive split produced 33 of 312 mangled rows (`city="SAINT", state="LO"`) |
| `mail_class` + `mail_class_reason` | classifier | **REQ** | Only `residential` may be reverse-searched |
| `jan1_addr_*` (prior mailing) | Union NC `JAN1_ADDR1/2/CITY/STATE/ZIPCO` | PREF | **PRIOR mailing address (372 targets differ from CURR), NOT a backfill** — `CURR_ADDR1 IS NULL AND JAN1_ADDR1 IS NOT NULL` returns **0** on the live layer. Second anchor + recent-move signal only |
| `entities_at_this_address` | registry address-frequency index | PREF | Agent-desk detection. **FL only** — see the scope caveat in `veil_piercing.md` |
| `entity_mailing_address` | SoS record | PREF | Sherpa `/api/business` returns empty without it |
| `registered_agent` `{name, type P/C, addr, commercial?}` | SoS | **REQ if entity** | Cannot distinguish agent from principal |
| `officers[]` `{title, type, name, addr}` | SoS | **REQ if entity** | No human to reach |
| `sos_doc`, `status`, `filing_type`, `file_date`, `fei`, `state_of_formation` | SoS | PREF | Active-record preference; foreign-filing detection; corroboration only |
| `trustee_names` | name parse / recorded deed | REQ if trust | No registry lists trustees |
| `person.first/last`, `person_addr` | derived/SoS | **REQ before person-axis call** | Assessor format is `LAST FIRST MID` |
| `phone`, `.type`, `.carrier`, `.last_seen`, `.dnc`, `.is_litigator` | one-api / Sherpa / Tracerfy | output | Type / last_seen / DNC are dialling gates |
| `deceased` | vendor inline | **disclosure gate, not a data gate** | See `compliance.md`. Tracerfy supplies it; where no source ran it is `UNKNOWN`, never `N` |
| `relatives` / `household_others` | vendor | PREF | The compounding loop — co-trustees David B Fiser and George Akans were found only here |
| `crm_hit` (Zoho account/contact ids) | Zoho MCP | **REQ before spend** | Duplicate spend on existing relationships |

---

## Normalization and join-key rules

Each is implemented as a tested function in `scripts/octlib.py` and covered in
`tests/test_octlib.py`.

1. **`norm_owner()`** — strips leading `C/O` | `ATTN` | `%`, removes
   `ET AL` | `ETAL` | `ET UX` | `ET VIR` | `AND OTHERS`, maps `[^A-Z0-9& ]` to space, collapses
   whitespace. Returns **both** `spaced` and `tight`. The tight form is what caught the 13
   `C S X TRANSPORTATION` parcels.
2. **`strip_suffix()`** — additionally removes
   `LLC / L L C / LC / INC / CORP / CO / COMPANY / LP / LLP / LLLP / LTD / PLLC / PARTNERSHIP /
   TRUST / TR / PA`, leading and trailing `THE`, and a trailing `[+&]`.
3. **`classify()`** — order is load-bearing: **gov → trust_company → trust/estate → entity →
   individual.**
   `TRUST_CO_RE = \bTRUST\b.*\b(LLC|INC|CORP|COMPANY|BANK|ADVISORS|SERVICES)\b`.
   **Bare `ESTATE` is not a trust marker** (only `ESTATE OF`, `LIFE EST`) or
   `REAL ESTATE INVESTMENTS INC` escapes the company block.
   **`TRUST_LIKE` is evaluated before the company matcher specifically so `CO TR` (co-trustee)
   is not read as `CO` = Company.**
4. **`csz_split(s)`** — parse **from the right**:
   `^(?P<city>.+?),?\s+(?P<st>[A-Z]{2})\s+(?P<zip>\d{5}(-\d{4})?)?$`, then validate `state`
   against the 51-code set before submitting.
   **Do not treat this as the fix for the `/api/business` 404s** — empirically the 33 mangled
   rows scored 19/34 with a person (56%) versus 87/257 (34%) for well-formed rows. That is a
   separate bug.
5. **`naddr(street, csz)`** — coarse dedupe: collapse `RD/ROAD`, `DR/DRIVE`, `LN`, `ST`, `AVE`,
   `PIKE`, `HWY`, `CIR`; **delete all directionals**; strip ZIP+4; reduce to `[A-Z0-9]`.
6. **`addr_key()`** — anchor comparison. Truncate at
   `STE|SUITE|UNIT|APT|RM|ROOM|FL|FLOOR|BLDG|DEPT|#`; strip a leading `C/O <name>` up to the
   PO Box or house number — Wingate University's mail runs through two named staffers at one
   box (`C O TAMMY BRITT PO BOX 159` vs `C O JENNY WALDEN PO BOX 159`); **the box is the
   identity, not the staffer.** Key = `street|city|ST|zip5`.
   *Deliberate divergence from `naddr`, documented in the code:* `addr_key` **canonicalizes**
   directionals rather than deleting them. `naddr` is a clustering key and can afford to be
   lossy; the anchor is the verdict, and collapsing `100 N MAIN` into `100 S MAIN` would accept
   the wrong household.
7. **`napn(s)`** = `re.sub(r"[^A-Z0-9]","",s.upper())`; **`split_apns()`** splits multi-APN
   cells on `[;,]` and **never truncates**.
8. **Fuzzy owner merging only between owners already sharing a mailing address**, bounded
   Levenshtein ≤2 — `fuzzy_owner_merge_ok()`. Two axes, never conflated:
   `owner_cluster_id` (same legal owner) and `rel_cluster_id` (same mailing address = one
   relationship, many owners). `STEGALL JOHN A` and `JOHN A STEGALL PROPERTIES LLC` sharing a
   PO Box remain **2 owner clusters, 1 relationship cluster**;
   `LANDPEDDLARS`/`LANDPEDDLERS` at one PO Box merge to 1 (acceptance test 13).
9. **Institutional detection tests BOTH the owner string AND the mailing blob** —
   `institutional_match()`. `SOUTHERN REGION IND REALTY INC` and
   `ATLANTIC LAND & IMPROVEMENT COMPANY` are only identifiable as Norfolk Southern / CSX land
   subsidiaries via their `C/O` line. Regex families ported from `build_master.py:45-84`:
   `RAIL_TIGHT` / `GOV_SPACED` / `CHURCH_SPACED` / `CORP_MAIL` / `CORP_OWNER_TIGHT` /
   `SUPERFUND_TIGHT`.
   `CORP_MAIL = [r"\bTAX DEPT\b", r"\bTAX DEPARTMENT\b", r"PROPERTY TAX", r"GENERAL COUNSEL",
   r"\bINDIRECT TAX\b", r"ATTN\s*:?\s*TAX"]`.
   Real dropped row: `ANHEUSER BUSCH BREWING PROPERTIES LLC`,
   `mail1: "ATTN GENERAL COUNSEL"`, 119 net acres. **45 rows dropped, each with an auditable
   reason.**
10. **`.strip()` every raw assessor value** — Union County writes `' '` for empty, and
    **46.3% of address values carried trailing whitespace**.
11. **Never key on `OBJECTID`** (layers republish and OIDs shift) **or on a per-parcel
    ownership id like `JAN1_OWNERID`** — tested and rejected: 41 distinct ids for one
    university's 41 parcels, and 8 ids reused across unrelated owners.

---

## Batch contract for the paid axis

Address batches are written as:

```json
{
  "batch": "<id>",
  "priority": "P1|P2|P3",
  "addresses": ["<street, city ST zip>", "..."],
  "map": {
    "<address>": {
      "owner_raw": "...", "entity_type": "...", "county": "...", "state": "..",
      "apns": ["..."], "parcel_count": 1
    }
  }
}
```

`BATCH = 250`.

**The `map` is what makes the join back possible — do not lose it.** `one-api`'s `Input Given`
field echoes the query back verbatim (`"2121 KENNEDY RD; KNOXVILLE, TN 37914"`) and **is** the
join key into this map.

**Priority buckets**

| Bucket | Contents |
|---|---|
| `P1` | individual + never-traced |
| `P2` | entity / trust / gov |
| `P3` | individual + already-traced |

**Eligibility.** Only `mail_class == "residential"` **and** a non-empty `mail_csz` are
eligible. 1,990 unique addresses survived from 2,659 Tier-A owners; the 669 rejected broke
down as `po_box 194` / `suite_or_co 150` / `none 193`.

Note the consequence of the FL-only agent-desk index: outside Florida `mail_class` is
`UNEVALUATED` rather than `residential`, so those rows are **not** reverse-address eligible.
That is deliberate (doctrine 9 + the scope caveat) and it must be reported as a coverage
figure, not hidden.
