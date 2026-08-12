# Source ledger — vendors, prices, tiers, dated verdicts

## EVERY ROW BELOW IS A DATED OBSERVATION, NOT A RUNTIME CONSTANT

This is the single most important thing about this file, because a skill that hard-codes
vendor prices, balances, actor defaults, availability and dead-ends will rot silently and keep
routing to a source that changed under it.

**At run start, `doctor.py` builds a capability manifest** — one record per source containing:

- zero-cost probe result
- response-schema fingerprint
- **declared upstream data source** (lineage)
- price **and account tier**
- quota / credit balance
- permitted axes
- last successful known-answer control

**Runtime routing reads the manifest, never the table below.** A changed schema, an unknown
upstream lineage, a failed control, or an undiscoverable price makes that capability **fail
closed** — degraded to `UNEVALUATED`, never silently skipped, and **never escalated to a
different vendor to paper over**.

The table seeds the manifest and records what was true on the stated date. Treat every
`DEAD`/`BLOCKED` verdict as a dated observation with a re-probe attached, not a permanent
prohibition.

**Credentials — including published bulk-download credentials like the Sunbiz `Public`
account — live in operator-managed config (`config/credentials.example.yaml` plus a real file
outside the repo), never inline in `SKILL.md` and never in source code.**

**Never record a per-result price without the account tier next to it.** `one-api` is $0.007
at BRONZE (this account) and **$0.02 on FREE** — a 2.9× swing. Read `pricing.userTier` from
`fetch-actor-details` at estimate time.

---

## The table

| Source | Returns | Cost | Auth path | Verified | Verdict |
|---|---|---|---|---|---|
| County CAD/GIS | owner + mailing address | free | per-county (`county_access.md`) | ongoing | **USE — the anchor of record** |
| FL Sunbiz SFTP bulk | full registry, RA + officers | **free** | `sftp.floridados.gov` / `Public` / `PubAccess1845!` | 2026-08-10 | **USE — best FL route** |
| Sunbiz per-entity browser | + FEI, authorized persons | free | `search.sunbiz.org/Inquiry/...` | 2026-08-06 | USE for ≤10 stragglers/run, behind a browser-availability check |
| OpenGovUS TN mirror | RA, county, formation | free | `?name=` | **HTTP 500 on every form 2026-08-11** | **DOWN — probe first; emit UNEVALUATED, never escalate to a paid vendor** |
| TX franchise `9cir-efmm` | entity + formation address | free | Socrata | 2026-08-10 | USE with caveat (formation ≠ current) |
| FDOR Florida Statewide Cadastral | verify PID; **same-owner assemblage discovery** | free | ArcGIS | in use | **USE — free portfolio finder** |
| **NYS DHCR MHP registrations (`sxi2-m23m`)** | park owner/operator name, address, **and PHONE**, 1989–2019 | free, no key | `data.ny.gov/resource/sxi2-m23m.json?$q=<NAME>&$limit=200` | 2026-08-04 | **USE for any NY manufactured-home-park owner — Tier-1 government phone.** Fields incl. `park_owner_1…7`, `owner_or_operator_name/address/city/zip_code/phone`. Live: 31 records for `Fietta`; a named principal with a 2007–2019 phone |
| Census **batch** geocoder | FIPS, standardized address | free, **no key** | `geocoding.geo.census.gov` | 200 on 2026-08-11 | USE. For a list use the **batch** endpoint (file upload, ≤10,000 rows) — a keyless per-row loop over 3,000 parcels will be throttled with no documented backoff |
| Placecraft MCP `get_parcel` | owner_name + owner_mailing_address | free | OAuth, `/mcp/` trailing slash | 2026-08-10 | USE for owner-of-record; **cannot pierce entities** (deep trace is web-UI-only); mailing is street-only, no city |
| **Tracerfy MCP `trace_lookup`** | person at a US address (or a named person at it): name, age, `deceased`, `property_owner`, mailing address, ranked `phones[]` with **`type` (Mobile/Landline), `carrier`, `dnc`, `tcpa`**, ranked `emails[]` | **5 credits/hit; a miss costs 0** | MCP connector, opaque `mcp__<uuid>__` prefix — resolve via ToolSearch | **LIVE 2026-08-11, balance 915 credits** | **USE — the backbone for the person→phone axis.** Pass `first_name`+`last_name` to trace a *named* person (doctrine 2); omit them only to discover the resident, which is **not** the owner |
| **Tracerfy MCP `parcel_lookup`** | same person payload, keyed `parcel_id + county + state` | **5 credits/hit; a miss costs 0** | as above | **LIVE 2026-08-11 — Knox `090 07403` hit, anchored exactly** | **USE as a corroboration axis only** (doctrine 1 exception). Succeeds where BatchData's APN mode scored 0/4 in the same county |
| **Tracerfy MCP `dnc_check`** | `national_dnc`, `state_dnc` + `state_dnc_list`, `litigator`, `is_clean` | billed per lookup (credits) | as above | **LIVE 2026-08-11** | **USE — this closes the DNC gap.** Run over every number that will be dialled or texted; the only live scrub source since Sherpa died |
| **Tracerfy `check_balance` / `list_strategies`** | credit balance; 25 strategy presets + valid filter keys | **free** | as above | 2026-08-11 | **USE in `doctor.py`** — `check_balance` is the pre-spend gate; `list_strategies` validates a strategy name before `preview_lead_list` |
| **Tracerfy lead-list tools** | `preview_lead_list` / `execute_lead_list` / `get_lead_list_status` / `get_lead_list_rows` | credits | as above | 2026-08-11 | **ADJACENT — discovery, not rundown. Out of scope.** Named in `SKILL.md` `## Not this skill`. **Never fire `execute_lead_list` inside a rundown** |
| Apify `one-api/skip-trace` (`vmf6h5lxPAkB1W2gT`) | address + reverse-phone axes, **source line type** | **$0.007/result at BRONZE (this account) / $0.02 on FREE** | Apify MCP | live, 9,229 users, 2026-08-11 | **USE — backbone.** Requires ZIP. **Name axis broken.** **`max_results` defaults to 1 — set it explicitly: 4 on the address axis (the household/relative graph depends on it), 1 on reverse-phone** |
| Apify `apivault_labs/skip-trace-people-finder` (`gSv8lJykdzOrYycAq`) | best name axis, relatives, currentAddress | **$0.0065 per matched record + $0.00005 start** | Apify | live, modified 2026-08-08 | USE with anchor. **No line-type field** — pipe through one-api reverse-phone. **⛔ `max_results` defaults to 100 and billing is per delivered match: one common surname = up to $0.65. Set it explicitly — 3 batch, 5 single — and estimate worst case** |
| Apify `scrapyspider/truepeoplesearch-contact-finder` | **`mobileNumbers[]` / `landlineNumbers[]` pre-separated** — the only actor that does | **free on Apify**, needs your own `scrapFlyApiKey` | Apify | store | **EVALUATE — confirm tool, not cold search.** Needs `name` AND `address`, exactly what this pipeline produces |
| Apify `shelvick/county-property-records` | 1,350 counties / 42 states; **`ownerLookups[]` enumerates every parcel an LLC owns** | $0.0475/resolved, free on `failed`/`not_covered` | Apify | store | **EVALUATE — free-ish portfolio finder** |
| Apify `jungle_synthesizer/truepeoplesearch-people-search-scraper` | name / reverse-phone / **reverse-address**; Bright Data internally | $0.10 start + $0.003/record | Apify | store | Fallback if scrapyspider's ScrapFly key is unavailable |
| Apify `sian.agency/property-skip-tracing` | purpose-built reverse-address | **$0.01 + $0.75 per address that hits** | Apify | store | **DO NOT USE — ~100× everything else.** Listed so nobody rediscovers it as "purpose-built" |
| Skip Sherpa REST | `type` enum, carrier, `last_seen`, **inline `dnc_statuses`**, `deceased` | PAYG **$30/mo = 200 @ $0.15**; **$100/mo = 1,000 @ $0.10**; → **$0.08 at 12,500**. DNC add-on $100/mo (1k/min) or $750/mo uncapped — **not needed** | `~/.skipsherpa/key`, header `API-Key:` (not Bearer), **all PUT**, spec at `/api/docs/openapi.json` | **BLOCKED 2026-08-10, re-probed 2026-08-11: `PUT /api/person {}` → 403 `permission_denied_exception` / "Invalid API Key"** | **DEGRADED — code the client, gate on the probe, fall back to one-api.** Surface: `/api/properties`, `/api/apn_properties`, `/api/property_details`, `/api/property_search`, `/api/person`, `/api/reverse_phone`, `/api/business`, `/api/workplace`, `/api/criminal`, `/api/dnc/status`, `/address/property_by_legal_description`. **Hard cap 25 lookups/request**; a batch exceeding remaining quota is rejected **whole** with 429, unbilled → batch at 10 |
| BatchData | person + phones + emails | pay-per-match; validation errors and no-match rows never bill | `~/.batchdata/key` (0600, dir 0700, **no trailing newline**), `Authorization: Bearer`, `POST https://api.batchdata.com/api/v1/property/skip-trace` (+ `/async` needs `options.webhook`), body `{"requests":[…]}` | **LIVE 2026-08-11** (`POST {}` → 400 `"The requests field is required."`) | **USE address mode only** — APN mode 0/4 on Knox. **`api.batchdata.io` does not resolve. Rotate — the token was pasted into a chat transcript** |
| Melissa Property Cloud | `fips+apn → owner + mailing` in one call; `LookupHomesByOwner` = portfolio finder; `GrpShape` = parcel WKT nationally | credits (per record; narrowing column groups cuts latency, not cost) | `~/.melissa/credits_key` | **BLOCKED — `GET usage.melissadata.net/v1/license?id=<key>` returned 200 `GE05` on 2026-08-11** | Would be the best anchor source. **Probe is `id` alone, no `t=`; `GE05`/`GE08` ⇒ skip silently and note the gap; any `YS##` ⇒ run `melissa.py selftest` (1 credit) before trusting it.** Rejected keys cost $0 |
| Telnyx Number Lookup | line type + **portability** | $0.007 | key needed | doc-verified | Recommended real line-type API |
| Twilio Lookup | `line_type_intelligence` | $0.008 flat | key needed | doc-verified | Alternative |
| Apify `whetstonetools/...sos-search` (`qXk703Eo2kBGmx5Bp`) | RA only, 28 states | $0.002/result | Apify | 2026-08-06 | Marginal — **no TN**; FL 24% usable-person yield |
| Wiza MCP | B2B work contacts | subscription (payment was failing) | connector | 2026-07-28 | Corporate humans only, **not property owners** |
| Zoho CRM MCP | existing accounts/contacts/deals | free | connector | 2026-08-10 | **USE FIRST** |
| Rent Manager / AppFolio / RentCafe `/applynow` | operator's full managed-property list | free | `curl` + grep `<option>` on `https://<operator>.twa.rentmanager.com/applynow` | 2026-08-06 | **USE for operators** — exposed 19 communities vs 8 in the CRM. **Trap both directions: a management portal proves management, not ownership, and its absence does not disprove it** (Willow Glen was theirs by deed since 2019-06-19 and absent). Segregate confirmed-owned (deed) / publicly-associated / disputed; never total across the three. Check `mhvillage.com/parks/<id>` for the *current* manager |
| OpenCorporates | — | — | — | 2026-08-06 | **DEAD for US** — 0 US matches, all UK |
| libphonenumber class (`pink_comic` `DEy6qJYYU1sOLH44l`, `zhorex` `4BeCzxeOpgUqO2BNu`, `nexgendata` `51GODKVRgMzD13Gjp`) | `FIXED_LINE_OR_MOBILE` | trivial | Apify | 2026-08-06 | **DEAD for this purpose** |
| Consumer aggregators | — | — | direct HTTP | 2026-08-10 | **ALL blocked. No curl path.** Failure signatures are NOT uniform — see below |

---

## Tracerfy credit accounting

Tracerfy is metered in **credits, not dollars**, so the budget gate needs a second counter.

| Call | Cost |
|---|---|
| `trace_lookup` **hit** | 5 credits |
| `parcel_lookup` **hit** | 5 credits |
| a **miss** on either | **0** — so a credit estimate is a ceiling, not a forecast |
| `dnc_check` | 1 credit per number (only when `--scrub` is set) |
| `check_balance` | **free** |
| `list_strategies` | **free** |

`doctor.py` calls `check_balance` (free) before every run and records the opening balance in
the run manifest. The estimator adds a `credits` column and **refuses to fire when the
estimate exceeds the balance**.

**Opening balance observed 2026-08-11: 915 credits**, of which 10 were spent on the two
acceptance-test controls (Knox `parcel_lookup`, Fort Stockton `trace_lookup`).

### ⛔ 2026-08-12 — BALANCE IS ZERO

Probed 2026-08-12T21:04Z. `ping` returns `pong`, `check_balance` returns **0 credits**,
`list_strategies` returns all 25 presets. **The server is healthy; the account is empty.**

915 → 0 in one day. Something consumed the balance between 2026-08-11 and 2026-08-12 and it
was not this skill.

**Consequence, and it is the exact scenario the standing caveat warns about:** a zero balance
turns the person-to-phone backbone off *silently*. `trace_lookup`, `parcel_lookup` and
`dnc_check` cannot fire. Because `dnc_check` is the **only live scrub source since Sherpa
died**, every row on every run degrades to `NOT YET SCRUBBED — do not dial or text` until the
balance is restored.

`doctor.py` reads `check_balance` before every run and the estimator refuses to fire when the
estimate exceeds the balance — at 0 credits that means **it refuses everything**, which is
correct. Restoring the balance is a `## Blocked on Mitch` item (account/payment).

### ❓ UNANSWERED — ask Mitch once, then write the answer here

**The dollar value of one Tracerfy credit is not documented anywhere in our records.**
Until Mitch answers, **report credits, never a fabricated dollar figure.** Do not estimate it
from any other vendor's pricing.

---

## Consumer-aggregator failure signatures

A naive status check will read two of these as working.

| Site | Signature |
|---|---|
| TruePeopleSearch | **403, 518 KB** — Cloudflare `cf-mitigated: challenge` **+ PerimeterX** (`px-captcha`, `challenge-platform`) |
| FastPeopleSearch | 403, 99 KB |
| Whitepages | 403, 5,840 B |
| Radaris | 403, 5,658 B |
| CyberBackgroundChecks | 403, 5,893 B |
| Nuwber | 403, 92 KB |
| SearchPeopleFree | 403, 5,692 B |
| ThatsThem | **403, 3,510 B — custom `<meta name="sentinel-challenge">`, NOT Cloudflare** |
| Spokeo | **200, 554 KB — open homepage; all result data behind login + paid subscription** |
| BeenVerified | **200, 176 KB — same. A 200 here is not success.** |

**Never solve a CAPTCHA.**

**Silver lining worth recording:** TruePeopleSearch is the only aggregator that labels line
type on the page itself (carrier + `Wireless`/`LandLine`, carrier-derived not algorithmic) —
which is why the TPS-backed actors above matter.

---

## Apify mechanics

- **Default datasets are publicly readable with plain curl, no token** (verified 200 on
  2026-08-11):
  `https://api.apify.com/v2/datasets/<id>/items?clean=true&format=json`
- Fire the actor via MCP, capture `runId` / `datasetId`, then **poll
  `https://api.apify.com/v2/actor-runs/{runId}` with an `until` loop** — Bash `sleep N && cmd`
  is blocked by the command classifier — then pull items into `RUN_DIR` (`.tmp` first, then
  `mv` on HTTP 200 only).
- **Never let dataset items enter context.** Precedent: a Placecraft list call returned
  168,571 chars and spilled to a file.
- `doctor` also checks `fetch-actor-details` returns `isDeprecated: false` on both actor ids,
  and reads `pricing.userTier` for the estimate.

---

## ⛔ 2026-08-12 — the Apify account tier is FREE, not BRONZE

Read from `fetch-actor-details` `pricing.userTier` at probe time, which is exactly what the
rule at the top of this file exists to force.

| Actor | Recorded 2026-08-11 | Measured 2026-08-12 |
|---|---|---|
| `one-api/skip-trace` | $0.007 at **BRONZE** | **$0.02 — the account is on FREE** |
| `apivault_labs/skip-trace-people-finder` | $0.0065/match flat | $0.0065/match flat (no tier variation on that event) |

**This is the 2.9× swing the rule was written about, and it is live.** A 200-address batch at
`max_results: 4`:

- at BRONZE — $5.60 (22% of a $25 budget)
- **at FREE — $16.00 (64% of a $25 budget)**

The estimator reads the tier and, when the tier is unknown, **fails safe to the worst case
($0.02) rather than the cheap one.** Do not re-plan a run on the BRONZE number.

Both actors probed `isDeprecated: false`. `one-api` modified 2026-08-10, 9,288 total users.
`apivault_labs` modified **2026-08-08**, which matches the date on the separator-probe note —
so that guidance still stands.

## ⛔ 2026-08-12 — `one-api` lineage is now DECLARED, and it collides

`one-api/skip-trace`'s own store description names its upstreams:

> TruePeopleSearch, FastPeopleSearch, Lead Finder, Truthfinder, Spokeo, BeenVerified,
> PeopleFinders

That moves `one-api` from `UNDECLARED` to **declared — and it overlaps with the
TruePeopleSearch-backed actors in this same table**: `scrapyspider/truepeoplesearch-contact-finder`
(TPS via ScrapFly) and `jungle_synthesizer/truepeoplesearch-people-search-scraper`
(TPS via Bright Data).

**Therefore `one-api` may NOT corroborate either of those, and they may not corroborate each
other.** They are one source wearing three hats, and a pair drawn from that set yields
`SINGLE-SOURCE-PHONE`, never `VERIFIED-PHONE` (acceptance test 27).

This narrows the corroboration options considerably. What can still serve as an
upstream-independent source B: `apivault_labs` (lineage still undeclared — so it also fails
closed until asked), BatchData, Skip Sherpa, and the government sources (NYS DHCR
`sxi2-m23m`, county recorder). **Ask both Tracerfy and apivault_labs to declare lineage** —
until they do, every corroboration involving them fails closed.

## Corroboration requires UPSTREAM independence

Two Apify actors that both resell the same people-search aggregator are **one source wearing
two hats**. `source_b_is_UPSTREAM_INDEPENDENT` is read from the capability manifest's
declared-lineage field; **if lineage is unknown, corroboration fails closed** to
`SINGLE-SOURCE-PHONE` (acceptance test 27).

A carrier/HLR lookup confirms the **number's type**, not its **subscriber**, and never
satisfies source B.
