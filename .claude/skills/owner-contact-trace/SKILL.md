---
name: owner-contact-trace
description: >
  Resolve a property to the human who controls it and that human's mobile number.
  Identity is settled free first from county assessor records and Secretary-of-State
  registries, piercing LLC, LP, corporate and trust ownership to a natural person; a
  paid vendor is only ever asked how to reach a person already named, never who owns a
  parcel. Use when Mitch says skip trace this, who owns this and what's their cell, find
  the owner's mobile, run down the owner, pierce this LLC, who's behind this entity,
  build me a call list, enrich these parcels, goal-seek mobile numbers, or hands over an
  APN, address, owner string or parcel CSV and wants contacts. Single lookups emit an
  OWNER RUNDOWN card, batches a call-list workbook. Not for zoning, entitlement or
  feasibility (florida-development-feasibility, zoning-livelocal-memo, mhp-feasibility,
  parcel-zoning-verification); not for B2B work contacts (Wiza); not for tenant
  screening, employment, credit or insurance, not an FCRA product. Supersedes
  owner-skiptrace.
license: Proprietary. Internal use for Mitch's land-acquisition practice.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, ToolSearch, WebFetch, Skill
metadata:
  version: "1.0.0"
compatibility: >
  macOS, system Python 3.9.6. Stdlib plus openpyxl 3.1.5, jsonschema 4.25.1 and pyyaml,
  all present in user site-packages; no pandas, no requests, no bs4, no pwsh, no node,
  no codex. HTTP via urllib with a browser UA, or curl. Requires three MCP connectors —
  Tracerfy (the person-to-phone backbone and the DNC scrub), Apify (fallback vendor axes)
  and Zoho CRM (stage 0 is a hard gate). All three are exposed under opaque per-machine
  mcp__UUID__ prefixes; resolve them with ToolSearch, never hardcode. Vendor keys are
  placed by MITCH at ~/.skipsherpa/key, ~/.batchdata/key,
  ~/.melissa/credits_key — Claude never handles a key value, never enters a payment
  method, never provisions an account.
---

If `anthropic-skills:owner-skiptrace` was loaded for this request, stop and use this skill instead. That skill's line-type step is structurally impossible in the US (number portability — every libphonenumber actor returns `FIXED_LINE_OR_MOBILE`), its OpenCorporates leg returned 0 US matches on every name (2026-08-06), and it has no address anchor. Do not run its `scripts/score_contacts.py`; its install path is a per-session UUID directory and will not exist next session.

This skill answers one question end to end: given a property, who is the human that controls it and what is their mobile number. It runs in two modes — a single-property inline rundown card, and a batch enrichment producing a call-list workbook. "Done" means every input APN carries either a named human with a source-classified mobile that passes the address anchor, or an explicit named disposition from a closed vocabulary. Never a blank. As of 2026-08-11 the output can be dial-ready, because Tracerfy returns line type, carrier, `dnc`, `tcpa`, `deceased` and `litigator` inline on every person and exposes a standalone `dnc_check`. **That stamp is conditional and per-row, never per-workbook:** any row whose phone carries no DNC value — Apify-sourced, or `dnc_check` not run — ships stamped `NOT YET SCRUBBED — do not dial or text`, and `delivery_gate.py` enforces it row by row.

**THREE CONCLUSIONS, NEVER ONE.** The skill produces three separately-labelled conclusions: (1) record owner as of a stated date, (2) documented human authority or contact role, (3) phone attribution and line type. Never collapse them into a claim that a human "owns" or "controls" the property. Public records reliably establish the record owner; they frequently cannot establish the current beneficial controller of a trust, land trust, nominee arrangement, series LLC, or an entity whose membership interests were sold without a deed ever recording. Where the evidence establishes the title-holding entity but not its controller, emit `RECORD-OWNER-RESOLVED / BENEFICIAL-CONTROL-UNKNOWN`. A completed row may be unresolved; it may never be guessed.

**The one thing to understand first: a skip-trace vendor asked "who owns this parcel" is 53% accurate (79/150 APN-keyed entity lookups) and returns the same wrong human for unrelated entities. Asked "how do I reach this named person" it was 100% (95/95 name-plus-address lookups). The entire pipeline exists to make identity free and certain before any vendor is paid.**

## Non-negotiable guardrails

1. **Never let a bare APN be the identity source** — 51 of 84 APN-only "hits" came back on a different parcel. (Narrow exception: Tracerfy `parcel_lookup` may *corroborate* a candidate a government record already named; it may never create one.)
2. **Never ask a vendor who owns a parcel** — `RLR INVESTMENTS LLC` returned Publix's CEO; a field literally named `property_owner: true` is still a vendor claim.
3. **The address anchor is the verdict, not a vendor's "CONFIRMED"** — ungated, one common name returned 115 phones across 20 states.
4. **`matchConfidence` / `matched: true` is never a gate** — BatchData confidently returned a named human for 1600 Pennsylvania Ave NW.
5. **Join on BOTH normalized owner name AND normalized mailing address** — name-only joins silently lost ~180 parcels.
6. **A registered agent is not the owner** — 57% of FL registered agents are commercial dead ends; record them and skip.
7. **Line type comes from the source record, never computed** — US number portability makes libphonenumber structurally incapable.
8. **Recency outranks line type** — a Wireless number last seen 2016 is worse than a landline seen this year (reassigned-number hazard).
9. **Only `mail_class == residential` may be reverse-address searched** — querying an LLC's office returns building tenants.
10. **A residential-looking address hosting ≥15 registry filings is an agent desk, not a home** — `7901 4TH ST N` hosts 70,796 entities.
11. **Geography is a disambiguation signal, never a universal identity gate** — reject a candidate only when its jurisdiction, ids, names, addresses or dates *conflict*; absentee ownership is the norm.
12. **Situs is not a contact axis** — measured yield was 5 of 6,930 contact rows.
13. **Never ingest a listing-supplied parcel ID or owner** — a $9.45M LOI went out on parcel IDs belonging to two unrelated entities.
14. **Check the CRM first** — ClearTrail was already a Zoho account with 5 direct dials and a prior deal.
15. **Nothing is deleted silently, and a suppression must be executable** — a comment in a config is not a filter; `UNEVALUATED` is distinct from "we looked and rejected."
16. **Every emitted field carries provenance** `{source, retrieved_at, anchor_basis, identity_tier, confidence_basis}` — a $0 name parse must never render like a verified mobile.
17. **Authoritative before inferential — this outranks free-before-paid** — the assessor roll is a billing record; an assessor-only conclusion is `TAX-ROLL-OWNER`, never `VERIFIED-OWNER`.
18. **Every truth-valued field supports `UNKNOWN`, and missing evidence is never coerced to `N`/`false`** — a deceased check that never ran must not render as "not deceased".

`references/doctrine.md` expands all 18 under the same numbers, with the evidence.

## Prerequisites

```sh
# 1. Dependencies (system python3; the doctor prints the exact line for anything missing)
python3 -m pip install --user openpyxl jsonschema pyyaml

# 2. Key directory modes. ~/.skipsherpa is still 755 while every other key dir is 700.
chmod 700 ~/.skipsherpa ~/.batchdata ~/.melissa
chmod 600 ~/.skipsherpa/key ~/.batchdata/key ~/.melissa/credits_key

# 3. Operator credentials file, outside the repo
cp config/credentials.example.yaml ~/.owner-contact-trace/credentials.yaml

# 4. Capability report — free probes only, spends nothing
python3 scripts/doctor.py --probe
```

**Claude cannot install a key via Bash** — the command classifier blocks commands that handle API key values — **but the Write tool CAN place the file.** Key *values* are supplied by Mitch; Claude never handles one, never enters a payment method, never provisions an account.

**MCP tool names are per-machine UUIDs.** *"Apify and Zoho tools are exposed under an opaque `mcp__<uuid>__<toolname>` prefix that differs per machine. Never hardcode the prefix. Resolve them with `ToolSearch(query: "apify actor call dataset", max_results: 8)` and `ToolSearch(query: "zoho searchRecords COQL", max_results: 6)`, then use the names returned. These tools are deferred — a bare `select:mcp__apify__…` fails; keyword search succeeds."* Tracerfy resolves the same way (`ToolSearch(query: "tracerfy trace lookup dnc balance", max_results: 8)`). Placecraft, by contrast, is stably `mcp__placecraft__*`.

`RUN_DIR` is `<cache_root>/runs/<state>_<county>_<YYYYMMDD-HHMM>/`, where `cache_root` resolves at runtime — `$OWNER_TRACE_CACHE`, else `~/Library/Caches/claude-owner-enrich` on macOS, else `$XDG_CACHE_HOME`, else `~/.cache/claude-owner-enrich`. No script hardcodes it. All intermediates, fixtures, caches and the ledger live there, outside any synced tree: `CENSUS.json`, `HUMANS.json` and `phone_verdicts.json` carry names, home addresses, phones and deceased flags. Only the final workbook or card may be copied to `<project>/output/owner_trace_<geo>_<YYYYMMDD>/`, and only after `leak_scan.py` and `delivery_gate.py` pass. Never `/private/tmp` (swept at 3 days), never the session scratchpad (dies with the session; a re-run cannot resume).

## Quick start

```sh
# 0. ALWAYS FIRST — snapshot the skill out of any synced tree, then run from the snapshot.
#    A mid-run iCloud sync half-wrote a script during the Davenport run.
bash scripts/freeze.sh                    # prints RUN_SKILL_DIR and the snapshot hash

# 1. Synthetic end-to-end, spends nothing, no network
python3 scripts/census.py    --in examples/synthetic_run/parcels.csv --county tn_knox --out-dir /tmp/oct-demo
python3 scripts/classify_owner.py --in /tmp/oct-demo/CENSUS.json --out-dir /tmp/oct-demo
python3 scripts/build_call_list.py --run-dir /tmp/oct-demo --format calllist --dry-run

# 2. Single property, real county layer, free identity only
python3 scripts/county_fetch.py --county tn_knox --apn "090 07403"

# 3. Batch, paid axis gated. --i-approve must equal --budget or nothing fires.
python3 scripts/census.py --in parcels.csv --county fl_duval --out-dir "$RUN_DIR"
python3 scripts/build_call_list.py --run-dir "$RUN_DIR" --budget 25 --i-approve 25 --format calllist
python3 scripts/delivery_gate.py --workbook "$RUN_DIR/call_list.xlsx"   # fresh process, blocking
```

## Pipeline

| # | Phase | Executed by | Key artifacts |
|---|---|---|---|
| 0 | Freeze + doctor | `freeze.sh`, `doctor.py` | skill snapshot + hash, `capability_manifest.json`, opening Tracerfy credit balance |
| 0a | CRM pre-check (advisory) | Zoho MCP via `doctor.py --crm` | `crm_precheck.json` — advisory only, never a stop |
| 1 | Census | `county_fetch.py`, `census.py` | `CENSUS.json`, `CENSUS_COVERAGE.json` |
| 1a | Recorder / title validation | manual + `census.py --deed` | deed fields or `DEED-UNAVAILABLE (<county>, <date>)`; conflict ⇒ `OWNERSHIP-CONFLICT` halts spend |
| 0b | CRM authoritative dedupe | Zoho MCP | `CRM-HIT (account <id>, <n> contacts)` — suppresses duplicate spend only, never proves ownership |
| 2 | Classify + suppress | `classify_owner.py` | `owner_class`, `mail_class`, suppression flags with the matched pattern |
| 3 | Free pierce ($0) | `free_pierce.py` | trust/eponymous leads from the frozen lexicon, tier `LEAD` |
| 4 | Registry pierce ($0) | `sos_route.py`, `sunbiz_pierce.py` | `ENTITY_LEDGER.json`, officers, RA, address-frequency index |
| 5 | Multi-hop | `sunbiz_pierce.py --hops 3` | hop chain + the unresolved frontier |
| 6 | Rank candidates | `build_humans.py` | `HUMANS.json` — top 3 ranked, commercial RA excluded |
| 7 | Person→phone (PAID) | `vendor_client.py`, `build_queues.py` | `contacts.jsonl`, `ledger.csv` — **budget gate** |
| 7a | APN corroboration (PAID, optional) | `vendor_client.py --apn-axis` | discarded unless the returned mailing address anchors |
| 8 | Reverse-phone corroborate | `verify_reverse.py` | `phone_verdicts.json` — a second billed call per phone |
| 9 | Gate + status | `anchor_gate.py` | the five status fields + the verdict ladder; **ambiguity gate** emits rank 1 and 2, never picks |
| 10 | Deliverable | `build_call_list.py`, `leak_scan.py`, `delivery_gate.py` | rundown card or workbook, `COVERAGE.json`, disclosure sheet |

## CLI flags

| Flag | Applies to | Meaning |
|---|---|---|
| `--in` / `--out-dir` / `--run-dir` | most | inputs and `RUN_DIR`; never an absolute default |
| `--county <key>` | `county_fetch.py`, `census.py` | adapter key from `config/counties/` |
| `--apn` | `county_fetch.py` | single-parcel mode |
| `--coverage` | `census.py`, `build_call_list.py` | emit `CENSUS_COVERAGE.json` / the KPI denominator |
| `--budget <USD>` | paid stages | required, default 25 |
| `--i-approve <USD>` | paid stages | must equal `--budget` or nothing fires |
| `--scrub` | `build_call_list.py` | run `dnc_check` per number; adds a credits line to the estimate |
| `--format calllist\|sherpa\|launchcontrol` | `build_call_list.py` | output shape |
| `--probe` | `doctor.py`, `sos_route.py` | zero-cost liveness only |
| `--hops N` | `sunbiz_pierce.py` | default 3; an operational limit, not a confidence statement |
| `--deltas-since` | `sunbiz_pierce.py` | daily registry deltas on top of the quarterly |
| `--dry-run` | paid stages | print the worst-case estimate and exit |
| `--strict` | `validate_skill.py`, `delivery_gate.py` | warnings become failures |

## Canonical outputs (per run)

```
<cache_root>/runs/<state>_<county>_<YYYYMMDD-HHMM>/
├── manifest.json                 # snapshot hash, cordata_vintage, opening credit balance
├── capability_manifest.json      # per-source probe, schema fingerprint, lineage, tier, price
├── CENSUS.json  CENSUS_COVERAGE.json
├── ENTITY_LEDGER.json            # per-entity disposition + hop chain + unresolved frontier
├── HUMANS.json                   # ranked candidates + evidence edges
├── contacts.jsonl  phone_verdicts.json
├── COVERAGE.json                 # one row per input APN, closed disposition vocabulary
├── ledger.csv                    # append-only: ts,endpoint,sent,billable
└── call_list.csv / call_list.xlsx
<project>/output/owner_trace_<geo>_<YYYYMMDD>/   # final workbook or card ONLY, after both gates
```

## When to read what

| Read | When |
|---|---|
| `references/doctrine.md` | before any judgement call about accepting a candidate, or when tempted to relax a guardrail |
| `references/data_census.md` | building or debugging `CENSUS.json`; any normalization or join-key question |
| `references/veil_piercing.md` | any entity, trust, LP, series LLC or multi-hop work; the Sunbiz record layout and offsets |
| `references/county_access.md` | before touching any county layer — endpoints, field maps, per-county traps |
| `references/state_routes.md` | before any Secretary-of-State work; what each state's route and disposition is |
| `references/source_ledger.md` | before any paid call, or when a vendor behaves unexpectedly — prices, tiers, dated verdicts |
| `references/traps.md` | when something returns empty, 403s, 404s, or silently loses rows |
| `references/dead_ends.md` | before adding any new source — what has already been tried and is affirmatively dead |
| `references/compliance.md` | before any deliverable ships, and before any outreach decision |
| `references/authoritative_sources.md` | when the registry gives officers but no control edge, or a trust/estate/entity-interest transfer stalls |
| `references/name_lexicon.json` | consumed by `free_pierce.py`; read it only to check a token's support or its bootstrap provenance |

## Cost routing

Standing envelope: **$200 Apify + $50 prepaid card**. Acceptance bar: **≥50% classified-mobile coverage**, computed by `build_call_list.py --coverage` as classified mobiles ÷ non-suppressed owner rows. Reference spend: the 2,996-parcel run consumed ~$38 of the $200 for 2,398 parcels with a contact (80.0%); the FL 188-parcel run consumed ~$5 Apify + $0 registries for 110/188 (59%).

Order within each tier is authoritative before inferential, then free before paid — doctrine 17 outranks cost, so a deed pull that costs money still precedes a cheaper vendor call. Before the first paid call in every mode the run prints a **worst-case** table (per axis, per actor, with `max_results` shown) and requires `--i-approve` equal to `--budget`. Thereafter `vendor_client.py` raises `BudgetExhausted` against the append-only ledger — never silent truncation.

**Tracerfy is metered in credits, not dollars, and needs a second counter.** 5 credits per `trace_lookup`/`parcel_lookup` **hit** (misses are free, so the estimate is a ceiling), 1 per `dnc_check` when `--scrub` is set; `check_balance` and `list_strategies` are free. `doctor.py` records the opening balance and refuses to fire when the estimate exceeds it. **The dollar value of a Tracerfy credit is not documented anywhere in our records. Ask Mitch once and write it into `references/source_ledger.md`. Until then report credits, never a fabricated dollar figure.**

Reserve a genuine ask-Mitch stop for exactly three things: a vendor not in `references/source_ledger.md`; any account provisioning, payment method, or DNC-scrub purchase; the NC bulk subscription. `CLAUDE.md`'s ">$1 → ask" rule stays scoped to OpenRouter LLM jobs, which is what it was written about.

## Delivery gate

`scripts/delivery_gate.py` runs **in a fresh process** against the finished workbook and blocks delivery if any of: a phone row lacks `{source, retrieved_at, anchor_basis, identity_tier}`; a number lacks a DNC value and lacks the literal `NOT YET SCRUBBED — do not dial or text`; a phone has `primary_line_type` but no `line_type_source`; any input APN has no `COVERAGE.json` disposition; `leak_scan.py` hits; a suppressed owner appears on the Call List sheet; `deceased == true` or `is_litigator == true` appears outside the disclosure sheet; any truth-valued field was coerced to `N`/`false` where no check ran; `HOUSEHOLD-PHONE` or `SINGLE-SOURCE-PHONE` is rendered as `PRIMARY MOBILE`; `ownership_status == TAX-ROLL-OWNER` on a row printed as `VERIFIED-OWNER`; or a `role_status` above `PROBABLE-AUTHORITY` rests only on a registered-agent, director, generic-officer or limited-partner edge. On failure it moves the workbook to `qa_quarantine/` and exits nonzero.

`leak_scan.py` is **scoped, not global** — this skill's product *is* phone numbers, so a blanket phone scan would reject every correct output. It scans raw-source columns, hidden sheets, cell comments, formulas, document metadata, temp files and any non-approved output location. Approved phone columns are schema-enumerated and pass; a phone number found anywhere else blocks delivery.

## Not this skill

Zoning, entitlement and feasibility → `florida-development-feasibility`, `zoning-livelocal-memo`, `mhp-feasibility`, `parcel-zoning-verification`. Drafting the offer to a found owner → `humanly-loi` and the `mail` skill; finding the human is this skill, writing to them is not. Cold outreach copy → `anthropic-skills:cold-email`. Cleaning an owner spreadsheet with no contact intent → `xlsx`. Lot yield → `land-planning-master`. B2B work email or phone for a corporate human → the **Wiza connector's `enrich_contact` directly**, not through this skill (Wiza is an MCP connector, not a skill; its subscription payment was failing as of 2026-07-28 — check `get_credits` first).

**List *generation* is not this skill.** Tracerfy's `execute_lead_list` and its 25 strategy presets (`vacant_land`, `probate_inherited`, `tired_landlord`, …) answer "which properties should I target" — the opposite direction from "who owns this one". Firing it inside a rundown spends credits on parcels nobody asked about. Hand it to acquisitions sourcing.

**And: "Who owns 090 07403?" with no contact intent is a one-call county lookup, not a run.** Answer it inline from the assessor layer and stop. Do not open a run directory, do not build a census, do not spend.

## Blocked on Mitch

Never attempted mid-run: any new vendor; any account provisioning, signup or payment (including **OpenSOSData's 10 free lookups**, which require an account); any DNC-scrub purchase; the **NC bulk subscription** ($2,750 year 1 — and ask NC SoS whether registered-agent address is a discrete column *before* paying); licensed title/skip platforms (DataTree, CLEAR, TLOxp, Accurint) pending licensing, contract scope and permissible-purpose confirmation; the counsel-maintained state outreach matrix; the dollar value of one Tracerfy credit. `chmod 700 ~/.skipsherpa` is Claude-runnable but key *placement* is not. Every outbound email is drafts-first, one message one native dialog, no batching. Before profiling a named individual with no property context, ask what the context is.

## Blocked — NOT IMPLEMENTED in this build

Stated plainly rather than described as working:

- **`references/name_lexicon.json` is a BOOTSTRAP lexicon, not the corpus build.** The 1,787 assessor-format records in `owner_mobile_enrichment/output/MASTER_OWNERS.csv` were not present in the build environment. Support values are bootstrap ranks, not measured counts. Rebuild with `scripts/build_lexicon.py --in MASTER_OWNERS.csv` before relying on support thresholds for anything but lead generation.
- **The FL Sunbiz `cordata.zip` quarterly (1,819,049,954 bytes, members dated 2026-07-10) is not present.** `sunbiz_pierce.py` is proven against a synthetic CRLF-terminated fixture at the corrected offsets, not against the live quarterly. Run `getcor.exp` and re-run the parser against a real member before trusting a production pierce.
- **No recorder/deed route is implemented for any county.** Stage 1a therefore emits `DEED-UNAVAILABLE (<county>, <date>)` and every assessor-only row is labelled `TAX-ROLL-OWNER`. Trusts stop at `TRUST-NEEDS-DEED`. This is the largest functional gap in the skill and it is deliberate — see `references/authoritative_sources.md`.
- **Vendor keys, the Zoho connector and the Tracerfy connector are absent from the build environment.** Every vendor path is coded and gated behind a `doctor.py` probe, and proven against recorded-shape fixtures with fictional digits. No path has been exercised against a live account in this build.
- **Foreign FL filings are not followed to their home registry** — 38 of 124 matched entities. A named gap, not a solved case.
- **TN has no entity-pierce route today** (OpenGovUS HTTP 500 on every query form, 2026-08-11). Knox — this skill's own canonical county — emits `UNEVALUATED — TN registry route down` and must not escalate to a paid vendor.

## Standing caveat

Every BLOCKED entry carries its zero-cost re-probe. Probe before assuming; do not code around a source that may have come back.

```
2026-08-11 — Tracerfy MCP — LIVE, 915 credits — re-probe check_balance (free) at every run
             start; a zero balance turns the backbone off silently and every downstream row
             degrades to NOT YET SCRUBBED
2026-08-11 — OpenGovUS TN mirror — HTTP 500 on every query form — TN has no entity-pierce
             route today; emit UNEVALUATED, never escalate to a paid vendor
2026-08-10 — Skip Sherpa — key BLOCKED, rotated key returns "Invalid API Key"; /api/business
             404s (not provisioned) — re-probe PUT /api/person {} (403 = dead)
2026-08-10 — Melissa Property Cloud — GE05/GE08 — re-probe
             GET usage.melissadata.net/v1/license?id=<key>; any YS## ⇒ run melissa.py selftest
2026-08-06 & 2026-08-10 — tnbear.tn.gov — returns 000 from every route tried — no probe worth
             running; use the documented corroboration-tier fallbacks
2026-08-10 — sosnc.gov — Cloudflare AND terms prohibit automated search — NO_ROUTE; ask Mitch
             before OpenSOSData or the bulk subscription
2026-08-10 — all consumer aggregators — 403 or paywalled; a 200 from Spokeo/BeenVerified is
             not success — do not retry, never solve a CAPTCHA
2026-08-06 — OpenCorporates — 0 US matches, all UK — affirmatively dead for US
2026-07-10 — Sunbiz cordata.zip — vintage on disk; if today − vintage > 45 days, warn and
             offer the delta pull (--deltas-since)
```
