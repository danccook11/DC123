# Doctrine — the 18 guardrails, with the evidence

These are the same 18 items numbered in `SKILL.md`'s `## Non-negotiable guardrails`. There
is no second list. Each section here carries the imperative, the measurement behind it, the
failure it prevents, and what to do instead.

---

## 0. The governing rule: three conclusions, never one

*Adopted from the 2026-08-11 GPT-5.6 Sol adversarial review, whose central correction was
that record ownership, documented authority and phone attribution are three separate
conclusions that must never be collapsed.*

The skill produces three separately-labelled conclusions:

1. **Record owner as of a stated date**
2. **Documented human authority or contact role**
3. **Phone attribution and line type**

Never collapse these into a single claim that a human "owns" or "controls" the property.
Public records reliably establish the *record owner*. They frequently cannot establish the
current beneficial controller of a trust, land trust, nominee arrangement, series LLC, or an
entity whose membership interests were sold without a deed ever recording — the
ClearTrail/Parkview split is exactly that case.

Where the evidence establishes the title-holding entity but not its controller, emit
`RECORD-OWNER-RESOLVED / BENEFICIAL-CONTROL-UNKNOWN`.

**A completed row may be unresolved; it may never be guessed.** Forcing all three into one
"resolved human" is precisely the confident-error this skill exists to prevent.

---

## 1. Never let a bare APN be the identity source

**Evidence.** 690 parcels were submitted APN-only. Of 84 returned "hits", **51 came back on
a different parcel** and **49 owner names contradicted the county record**. Vendors fuzzy-match
APNs against their own property database, not against the county's. Separately, **94.8% of
those parcels already had an owner name sitting on local disk** — the spend bought nothing
that was not already free.

**Narrow exception, added 2026-08-11.** Tracerfy `parcel_lookup(apn, county, state)` may be
fired as a *corroboration* axis, because its return carries the person's own mailing address
and can therefore be anchored. Knox `090 07403` returned `10205 Coward Mill Rd`,
byte-identical to the county's `FULL_MAIL_ADDRESS`.

**The exception is strictly one-directional.** A paid APN or reverse-address search may
**corroborate** a candidate a government record already named. It may never **create** one.
An APN-keyed result that does not anchor is discarded — never promoted, never printed.

**And anchoring is not title.** An anchored APN hit can still be a spouse, adult child,
household member, tenant, trustee candidate, or the manager who receives the mail. Anchoring
proves association with the address. It does not prove ownership.

---

## 2. Never ask a vendor who owns a parcel

**Evidence.** `A A AUTO PARTS INC` and `CSX TRANSPORTATION` returned the same human.
`RLR INVESTMENTS LLC` returned Publix's CEO.

**A vendor field literally named `property_owner: true` is still a vendor claim.** Measured
2026-08-11: Tracerfy `trace_lookup` on `735 S US Highway 285, Fort Stockton TX` returned
`Juan Rivas`, `property_owner: true`, mailing `PO Box 712, Fort Stockton` — while Pecos CAD's
TY2026 roll says the owner is `PARKVIEW MHP REAL ESTATE LLC` mailing to
`1400 Belleville St, Richmond VA`. Rivas is a resident of the park, not its owner.

The flag is marketing. The anchor is the verdict. This is acceptance test 22, and a build
that prints Juan Rivas as the owner of that parcel has failed regardless of every other test
passing.

Identity comes from government records. Vendors sell reach only.

---

## 3. The address anchor is the verdict — a vendor's "CONFIRMED" is not

A returned person is accepted only if their `currentAddress` ties to the parcel mailing
address, or to the pierced principal's own filed address.

**Evidence.** Ungated, one common name returned **115 phones across 20 states**. In one batch,
**489 of 508 phones belonged to the wrong person, at average confidence 85**.

Both anchor bases are valid and both must be indexed — see `references/traps.md`, "the join
bug that wastes the pierce."

---

## 4. `matchConfidence` / `matched: true` is never a gate

**Evidence.** BatchData's control on 1600 Pennsylvania Ave NW confidently returned
"Jerome Marquis Lewis" with 5 phones.

Vendor confidence values are recorded for audit as `vendor_owner_claim` and similar fields.
They are never an input to any predicate in `octlib.py`.

---

## 5. Join on BOTH normalized owner name AND normalized mailing address

**Evidence.** Name-only joins silently lost ~180 parcels — `ACUFF GARY H & ANN D` versus
`ACUFF GARY HERBERT & ACUFF ANN DENISE` is the canonical pair (acceptance test 8). Recovery
was free. The address join then became the single largest contributor: **4,564 of 6,930
contact rows**.

Two axes, never conflated: `owner_cluster_id` (same legal owner) and `rel_cluster_id`
(same mailing address = one relationship, many owners).

---

## 6. A registered agent is not the owner

**Evidence.** `ELLISON ROAD, LLC` — registered agent Arnold H Slott, manager the
`CHARLES W. BOSTWICK TRUST`. Contacting the agent reaches a service company.

Commercial agents (CT Corporation, CSC, Registered Agents Inc, LegalZoom, and any
`P.A.` / `PLLC` / `LLP` / law-firm marker) are **recorded and skipped, never contacted**.
**57% of FL registered agents are commercial dead ends** before you spend anything —
`octlib.is_commercial_agent()` catches them for free.

A `registered-agent` edge can never by itself establish control. See
`references/veil_piercing.md`.

---

## 7. Line type must come from the source record, never computed

US mobile number portability makes libphonenumber **structurally incapable** of answering
this question — every Apify libphonenumber-class validator returns `FIXED_LINE_OR_MOBILE`.

Only these may produce the word "mobile":

- **Tracerfy `phones[].type ∈ {Mobile}`** (with `carrier`)
- Skip Sherpa `PhoneNumber.type ∈ {mobile}`
- `one-api/skip-trace` `Phone-N Type ∈ {Wireless}`
- a carrier/HLR API (Telnyx $0.007, Twilio $0.008)

`octlib.LINE_TYPE_SOURCE_ALLOWLIST` enforces this and `delivery_gate.py` re-checks it. Any
value originating from a libphonenumber actor (`numberType`, `FIXED_LINE_OR_MOBILE`) is a
hard reject that raises (acceptance test 5).

---

## 8. Recency outranks line type

A Wireless number last seen 2016 is worse than a landline seen this year — the FCC
reassigned-number hazard is real and dialling a reassigned number is the compliance
exposure, not just a wasted call.

**Evidence.** 415 primaries in the Knox list were more than 4 years stale.

`octlib.phone_sort_key()` puts `recency_band` first: 0 if last seen ≥ now−18 months, 1 if
≥ now−48 months, else 2. **"now" is computed, never hardcoded** — the source builder froze it
at `2026*12 + 7`.

---

## 9. Only `mail_class == residential` may be reverse-address searched

**Evidence.** Querying an LLC's office (`200 N Laura St, Jacksonville`) returned building
tenants including a law-firm email. 36 entity mailing addresses returned 4 "hits", all
sharing one toll-free scraper artifact (`+1-855-723-2747`).

---

## 10. A residential-looking address hosting ≥15 registry filings is an agent desk, not a home

**Evidence.** `150 SE 2nd Ave` = 1,381 FL entities. `7901 4TH ST N` = 70,796.

`AGENT_DESK_MIN = 15`. Person-level equivalent: more than ~20 active entities with ~0
own-name entities is a filing agent, not a principal (`VEDRANI,NATHAN` — 160 active FL
entities).

**Scope caveat.** The address-frequency index is built from the FL bulk file, so the count
exists **only for Florida**. For a TN/NC/TX/NY parcel the agent-desk gate is `UNEVALUATED`,
not `residential` — a missing count must never read as a clean pass (acceptance test 9).

---

## 11. Geography is a disambiguation signal, never a universal identity gate

The parcel county controls which assessor and recorder you search. It does **not** constrain
the owner entity's formation state, principal county, registered-agent county, or a human
principal's residence. **Absentee ownership is the norm in this business**, and a hard county
gate would reject the true out-of-county entity in favour of a false local name match.

Reject a registry candidate only when its jurisdiction, entity number, legal name, addresses,
dates or filing history **conflict** with the property evidence. Follow foreign filings to
their stated formation jurisdiction.

**Applied that way the signal still does its work.** It killed all 18 confident TN false
positives — three `HOLSTON *` LLCs resolving to a Nashville entity whose *agent* merely
happened to be surnamed Holston. That is a name collision with no corroborating
discriminator, not a geography violation (acceptance test 7). Likewise `DAVID BALDAUF` at
confidence 100 in New Hampshire and a 70-year-old Harold Cromwell in Kansas City are rejected
on conflict, not on distance (acceptance test 6).

---

## 12. Situs is not a contact axis

Owner-occupied → situs already equals mailing, so it adds nothing. Absentee → whoever answers
is a tenant.

**Measured yield: 5 of 6,930 contact rows.** Do not build a situs-address contact axis.

---

## 13. Never ingest a listing-supplied parcel ID or owner

**Evidence.** A **$9,450,000 LOI** went out on parcel IDs belonging to two unrelated entities,
covering 49.05 acres rather than the 135 advertised.

Resolve from the county layer. The client's own sheet can also be wrong about the owner —
`Schmidt Family Trust` versus `Gabor Donald J Jr`.

---

## 14. Check the CRM first

**Evidence.** ClearTrail was already a Zoho account with 5 direct dials and a prior deal. The
whole trace was unnecessary.

Stage 0a is advisory. **Stage 0b is the authoritative dedupe** and matches on billing street
plus phone, never a name substring. A CRM hit suppresses duplicate **spend** only — it is
never evidence that the account still owns the parcel, or that its contacts still control the
entity. Ownership validation continues regardless.

---

## 15. Nothing is deleted silently, and a suppression must be executable

Institutional, government and active-operator owners are **suppressed with a recorded matched
pattern**. Conflicts stay visible as named gaps. `UNEVALUATED` ("we never looked") is a
distinct verdict from "we looked and rejected it."

**Evidence.** `pinellas.json` said in writing "screen out explicitly" for the Stauffer
Management Superfund site. The exclusion existed only as prose, and Stauffer shipped.

**A comment in a config is not a filter.** Every suppression is unit-tested against its own
config comments.

### Cull-reason vocabulary

`Railroad` · `Quarry/materials major` · `Transport/logistics major` · `Health system` ·
`Institutional trustee/bank` · `Church/civic (rarely sells)` · `Club/golf` ·
`Government/public`

### Seed institutional list (19)

Held back with a recorded pattern, never deleted. Mirrored in `octlib.SEED_INSTITUTIONAL`.

```
C S X TRANSPORTATION INC
SEABOARD COAST LINE RR CO
SEABOARD COASTLINE RR CO
FLORIDA EAST COAST RAILWAY CO
GEORGIA SOUTHERN & FLORIDA RAILWAY CO
FLORIDA ROCK INDUSTRIES INC
MARTIN MARIETTA MATERIALS INC
SMYRNA READY MIX CONCRETE LLC
CON WAY TRANSPORTATION SERVICES INC % MS MARGARET BONG
OVERNITE TRANSPORTATION CO
ST JOHNS RIVER TERMINAL COMPANY
TANDEM LEASING CORPORATION
ST LUKES ST VINCENTS HEALTHCARE INC
CITY NATIONAL BANK OF FLORIDA TRUSTEE
MILAM STEPHEN WESLEY TR % FIRST TENNESSEE BANK ATTN LINDA FLENNIKEN
HGC GETTYSVUE LLC
ASSN FOR PRESERVATION OF TENNESSEE ANTIQUITIES KNOXVILLE CHAPTER
VOLUNTEER LODGE 2 FRATERNAL ORDER OF POLICE
TENNESSEE STATE OF
```

A CSX pierce that yields a real human with three non-DNC phones must still not reach the
Call List sheet; `delivery_gate.py` blocks it (acceptance test 14).

---

## 16. Every emitted field carries provenance

`{source, retrieved_at, anchor_basis, identity_tier, confidence_basis}` — produced by
`octlib.provenance()` and required by `schemas/contact.schema.json`.

**A $0 name parse must never render like a verified mobile.** Identity tier and
`confidence_basis` are what keep a lexicon guess and a source-reported carrier record
distinguishable three steps downstream.

---

## 17. Authoritative before inferential — this outranks "free before paid"

The assessor roll is a **billing** record, not a title record. It lags conveyances, keeps
dissolved grantees, and omits vesting language.

**An assessor-only conclusion is `TAX-ROLL-OWNER`, never `VERIFIED-OWNER`.**

Where a deed is obtainable, pull it **even when it costs more than the vendor call it
precedes**. Contacting a prior owner is the most expensive error this skill can make, and it
is invisible without the recorder.

A recorder-vs-assessor conflict **stops all paid identity work** and emits
`OWNERSHIP-CONFLICT` (acceptance test 25). Where no online recorder route exists, emit
`DEED-UNAVAILABLE (<county>, <date>)` — a named gap, never a silent pass.

*Build status: no recorder route is implemented in this build. Stage 1a therefore emits
`DEED-UNAVAILABLE` for every county and every assessor-only row is labelled `TAX-ROLL-OWNER`.
See `SKILL.md` `## Blocked — NOT IMPLEMENTED` and `references/authoritative_sources.md`.*

---

## 18. Every truth-valued field supports `UNKNOWN`, and missing evidence is never coerced to `N`/`false`

A deceased check that never ran must not render as "not deceased". An address gate that was
never evaluated must not render as passed *or* failed.

`Y/N` booleans on `deceased`, `anchored`, `surname_match` and `geo_match` are the single
easiest way for this deliverable to lie. `octlib.tri()` returns `UNKNOWN` for anything
absent, every relevant schema enum includes `UNKNOWN`, and `delivery_gate.py` blocks a
workbook in which a never-run check appears as `N` (acceptance test 26).

---

## Two rules that fall out of the above and are easy to lose

- **Wireless status never increases ownership or role confidence.** Line type answers a
  different question. A `VERIFIED-MOBILE` on an `UNKNOWN` owner is still an unknown owner.
- **`surname5_prefix_match` is removed from every acceptance predicate.** It survives only as
  a ranking and lead signal. At five characters it confidently accepts the wrong Smith, and
  `sn_pierced` is partly circular anyway — you queried the vendor for a named candidate, then
  credited the vendor for returning that candidate's surname.
