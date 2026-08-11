# State routes — `sos_route.py` returns `(route, disposition, reason)`

Read this before any Secretary-of-State work.

**`sos_route.py --probe <ST>` runs a known-answer liveness check before any work in that
state.** On failure it emits

```
UNEVALUATED — <ST> registry route down (<code>, probed <ts>)
```

and **never falls through to a paid vendor** — that would violate doctrine 2. A state with no
route is a coverage disposition, never a silent zero (acceptance test 21).

---

## FL — Sunbiz bulk (primary)

**Route:** the free SFTP bulk quarterly. See `references/veil_piercing.md` §8–§12 for
mechanics, offsets and the two free inverse indexes.

**Stragglers:** `search.sunbiz.org` per-entity, capped at **10 per run**.
Use `get_page_text` — **`read_page` returns empty on this site.** The earlier Apify 403 was
only ever a missing session.

Officer/agent reverse search:
`search.sunbiz.org/Inquiry/CorporationSearch/ByOfficerAndRegisteredAgentName`

**Gate the browser leg behind a `doctor` check that the browser tool resolves.** If it does
not, emit `UNEVALUATED — browser route unavailable` and continue.

**Disposition on no match:** `NO-SOS-MATCH`, or `possible post-snapshot formation` where the
county record shows a recent conveyance and `cordata_vintage` predates it.

---

## TN — OpenGovUS mirror ⛔ DOWN

**Route (when up):**

```
https://opengovus.com/tennessee-business?name=<NAME>        # ?name=  NOT  ?q=
detail  /tennessee-business/<control#>
delay   0.8 s
UA      browser UA required (403 without one)
row regex   /tennessee-business/(\d{6,12})"[^>]*>([^<]{3,120})</a>
```

Detail labels: `Control Number`, `Filing Name`, **`Principle Address`** *(sic — the state's
own misspelling; match it literally)*, `Mail Address`, `County`, `Filing Type`, `Status`,
`Formed Date`, `Agent Name`, `Agent Address`.

`pick()` ladder: exact-normalized → unique-prefix → `prefix-ambiguous`. **Never a loose
guess.**

**Ceiling even when up:** the snapshot ends ~2015-16, so **15 of 44 entities (34%) returned no
match**, mostly post-snapshot formations. That is acceptable — long-held family land sits in
old entities.

**⛔ MEASURED 2026-08-11: every query form returns HTTP 500.** `?name=SCHAAD`, `?q=`,
`?name=HOLSTON+HILLS`, and the detail URL `/tennessee-business/000625089` all 500. Landing
pages return 200, so a naive status check reads the route as healthy.

`tnbear.tn.gov` returns 000 from this machine, from the in-app browser, and from Apify's
infrastructure. `whetstonetools` has no TN.

**So Knox — this skill's own canonical county — currently has zero entity-pierce route.**

**Disposition:** `UNEVALUATED — TN registry route down`. Must not call a paid vendor, and must
not emit `PIERCED but no reachable human` (which would imply we looked and found nothing).

**Documented free fallbacks, corroboration-tier only:**
`company-detail.com/company-<slug>-<DOSID>` and litigation-snippet search.

---

## TX — Socrata `9cir-efmm`

**Route:** `data.texas.gov` dataset `9cir-efmm`, free.

**Caveat that must ship with every result:** it carries the **formation-era address, not the
current one**.

`ROAD RUNNER TX LP` is absent from the dataset entirely. **Absence is not evidence the entity
does not exist.**

**Dead:** TX Comptroller franchise search (`mycpa.cpa.state.tx.us/coa/…`) is JS-driven and
returns the search page, not results. TX SOSDirect requires a login.

---

## NC — `NO_ROUTE`

**Reason string, verbatim:**

```
sosnc.gov is Cloudflare-challenged AND its terms prohibit automated search
— ASK Mitch before OpenSOSData or the $2,750 bulk subscription
```

`monty15/north-carolina-sos-business-search` is the only NC-capable actor
(~$0.0055/result ≈ $10 for ~1,500 entities) and **failed on all three attempts** — the
managed-browser transport died at ~37 s regardless of memory, the HTTP transport at 3 s. Its
schema has `registered_agent_name` but **no registered-agent address**. **Do not budget on it
without a 20-entity known-answer gate.**

Before paying for the bulk subscription — $2,000 per state fiscal year + $750 setup, CSV over
FTP, weekly, *"no technical support is offered"*, 919-814-5400 — note that **the FTP hostname
and column layout are unverified: the data dictionary lives on the FTP and is released only
after subscribing.** **Ask NC SoS whether registered-agent address is a discrete column BEFORE
paying.**

OpenSOSData's 10 free lookups require signup. Claude cannot create the account —
`## Blocked on Mitch`.

**Disposition:** `NO-ROUTE-STATE`.

---

## NY — assessment roll + clustering, plus one working entity hop

**Primary:** the assessment roll (see `references/county_access.md`) plus **shared-mailing
clustering** — `PO BOX 630 Brewerton` collapsed a 4-party assemblage to 2.

**An entity hop that worked 2026-08-04:** `company-detail.com/company-<slug>-<DOSID>` returns
the NY DOS CEO name **and full home address**, the DOS process address, and the principal
executive office (`FIETTA REALTY CORP`, DOS #154702). No auth, WebFetch-friendly — after
CorporateWiki and Justia both 403'd.

`great_pistachio/us-business-search` (`QqAzLkYTEUdUoXfSd`) also works for NY but is **company-name
search only** — an officer-name query silently returns nothing.

**Secondary:** litigation records name principals (`Kopp v Fietta Realty Corp.`, 2006).
`law.justia.com` 403s WebFetch, but **the search-result snippet carries the party name**.

**Also NY-specific and free:** NYS DHCR manufactured-home-park registrations (`sxi2-m23m`)
return the park owner/operator name, address **and phone**. See
`references/source_ledger.md`.

---

## SC — `NO_ROUTE`

No working route identified. **Disposition:** `NO-ROUTE-STATE`.

---

## MI — `NO_ROUTE`

`mibusinessregistry.lara.state.mi.us` is browser-only behind a self-clearing Cloudflare
interstitial and has **no officer or registered-agent search** — so even a successful browser
session does not answer this skill's question.

Also: `pta.waynecounty.com` is the **delinquent-tax portal only** — a valid address returns
nothing. BS&A defeats `read_page` / `get_page_text`; drive it with screenshots.

**Disposition:** `NO-ROUTE-STATE`.

---

## Route table

| State | Route | Disposition on failure | Reason |
|---|---|---|---|
| FL | Sunbiz SFTP bulk (+ ≤10 browser stragglers) | `NO-SOS-MATCH` | primary route, free, works |
| TN | OpenGovUS mirror | `UNEVALUATED — TN registry route down` | **HTTP 500 on every query form, 2026-08-11**; tnbear dead; no paid escalation |
| TX | Socrata `9cir-efmm` | `NO-SOS-MATCH` | works, but formation-era address only; absence ≠ nonexistence |
| NC | `NO_ROUTE` | `NO-ROUTE-STATE` | Cloudflare **and** terms prohibit automated search; bulk subscription is a Mitch decision |
| NY | assessment roll + `company-detail.com` DOSID hop | `NO-SOS-MATCH` | works; officer-name search unavailable |
| SC | `NO_ROUTE` | `NO-ROUTE-STATE` | no route identified |
| MI | `NO_ROUTE` | `NO-ROUTE-STATE` | browser-only, and no officer/RA search exists |

**Any state not listed:** `UNEVALUATED — no working registry route for <ST> as of <date>`.
Never a silent zero, and never an escalation to a paid identity query.
