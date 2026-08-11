# Dead ends — what not to build

Read this **before adding any new source.** This is not symptom → cause → fix; it is a record
of things already tried and found affirmatively dead, with the ids and failure strings
attached so nobody rediscovers them at cost. Working-but-broken things live in
`references/traps.md`.

**Standing principle:** every entry is a **dated observation with a zero-cost re-probe
attached**, not a permanent prohibition. Probe before assuming; do not code around a source
that may have come back. The `## Standing caveat` block in `SKILL.md` carries the probes.

---

## Do not build on these at all

**OpenCorporates** — 0 US matches, all UK, 2026-08-06. Affirmatively dead for US work.
`ryanclinton/opencorporates-search` (`x0a1Q4g0MLc7h15Im`) is backed by the same dead data.

**Any libphonenumber-based actor, for mobile classification** — structurally impossible in the
US because of number portability. Every one returns `FIXED_LINE_OR_MOBILE`. This is not a
quality problem that a better actor solves; it is the wrong instrument.

**Direct HTTP to any consumer aggregator** — TruePeopleSearch, FastPeopleSearch, Whitepages,
Radaris, Nuwber, ThatsThem, CyberBackgroundChecks, SearchPeopleFree, Spokeo, BeenVerified.
Measured 2026-08-10: **no curl path exists.** Failure signatures are in
`references/source_ledger.md` and are **not uniform** — Spokeo and BeenVerified return 200 on
an open homepage with everything behind a paid login, so a naive status check reads them as
working.

**And the skill must never solve a CAPTCHA.** Not as a fallback, not once, not "just to
check."

**`sosnc.gov`** — Cloudflare-challenged **and** its terms prohibit automated search. Both
reasons independently sufficient.

**`tnbear.tn.gov`** — returns 000 from this machine, from the in-app browser, and from Apify's
infrastructure (2026-08-06 and 2026-08-10). No route tried has reached it.

---

## Do not retry these actors

Recorded with ids and failure strings.

| Actor | Id | Failure |
|---|---|---|
| `crawlerbros/radaris-people-search` | `TyXXhaE5ZodHg2Xt3` | exitCode 91 `"No matches found."` — three runs, 2026-08-04/05 |
| `brilliant_gum/skip-trace-people-search` | `afqlNfFewhpztVYEv` | 0 items on name, phone **and** address axes; 71–87 s/run |
| `khadinakbar/skip-trace-property-owner` | `GQG7ArCQldQTLKiQT` | `lookup_status: "not_found"`, all fields null — on a real owner-occupied address |
| `intelscrape/truepeoplesearch-scraper` | `EQWGhgaq5ac5tAvYk` | 0 results; Apify rating 1.0 from 1 review |
| `intelscrape/skip-trace-pro` | `LWeXXveX7WeSJ7z48` | `phoneCount: 0, bestPhone: null` on every record |
| `bovi/skip-trace-people-finder` | — | 0 on controls |
| `seibs.co/business-registry-intel` | `F9JdNPfza3vTeuMfJ` | exitCode 1 in 30 s, twice; claims 50 states, parses 13, **no TN** |
| `great_pistachio/us-business-search` | `QqAzLkYTEUdUoXfSd` | 0 for FL; **works for NY but company-name only** — an officer-name query silently returns nothing |
| `whetstonetools/secretary-of-state-business-search` | `qXk703Eo2kBGmx5Bp` | 28 states, **no TN**; FL 24% usable-person yield |
| `datacach/phoneinfoga-phone-number-osint-scanner` | `z4E6tmPrTZML4Gpbo` | `carrier` empty without a Numverify key; the OVH leg is FR/BE/GB/ES/CH only |
| `real-estate-api/skip-trace-owner` | — | description promises APN input; **the schema is the opposite direction — addresses in, APN out** |
| `monty15/north-carolina-sos-business-search` | — | failed all three attempts; managed-browser transport died ~37 s regardless of memory, HTTP transport at 3 s; schema has `registered_agent_name` but **no registered-agent address**. See `state_routes.md` before budgeting on it |
| `sian.agency/property-skip-tracing` | — | works, but **$0.01 + $0.75 per address that hits** — ~100× everything else. Listed so nobody rediscovers it as "purpose-built" |

**Bizapedia and CorporationWiki for TN** — anti-bot interstitial / no TN coverage.

---

## Do not build these steps

**A situs-address contact axis.** Owner-occupied means situs already equals mailing; absentee
means whoever answers is a tenant. Measured yield: **5 of 6,930 contact rows.**

**A deed-pull step that pretends private trusts are solved.** There is no deed-pull
implementation anywhere in the corpus and this build does not add one. The honest output is
disposition `TRUST-NEEDS-DEED`.

**A "pierced" label on a foreign FL filing.** 38 of 124 matched entities were foreign filings
and nothing follows a foreign entity to its home registry. That is a **named gap**, not a
solved case.

**An escalation path from a registry outage to a paid identity query.** That is doctrine 2. A
dead registry produces `UNEVALUATED — <ST> registry route down`, full stop.

**List *generation*.** Tracerfy's `execute_lead_list` and its 25 strategy presets
(`vacant_land`, `probate_inherited`, `tired_landlord`, …) are a **sourcing** tool that answers
"which properties should I target" — the opposite direction from "who owns this one". Firing
it inside a rundown spends credits on parcels nobody asked about. It is named in `SKILL.md`
`## Not this skill` and has a should-NOT-trigger eval:
*"Build me a list of vacant land owners in Pecos County"* → the Tracerfy lead-list tools
directly, not this skill.

---

## Do not expect these to do what they look like they do

**Placecraft over MCP** cannot pierce entities — deep trace is web-UI-only — and its import
accepts lat/lon only, not APNs.

**Melissa** — code the client, but do not build on it until a probe returns a `YS##` code. It
returned `GE05`/`GE08` on 2026-08-11.

**Skip Sherpa** — code the client, but do not spend until a key passes the live probe. It
returned `Invalid API Key` on 2026-08-11.

**A management portal** proves management, not ownership — and its absence does not disprove
ownership. Willow Glen was owned by deed since 2019-06-19 and absent from the portal.

---

## Do not do these things to the deliverable

- Do not **extend or reference the plugin skill `owner-skiptrace`.** Naming it in the
  description and the first line of the body is the only permitted contact — that is a routing
  lever, not a dependency. Its install path is a per-session UUID directory that will not exist
  next session.
- Do not **publish any output to a public artifact or repository.**
- Do not **create Zoho `Leads` records** or write narrative to a Zoho Contact `Description`
  field.
