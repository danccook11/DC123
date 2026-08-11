# Authoritative sources — the records a professional uses that this corpus never touched

Every run so far has been **assessor + registry + vendor**. That is a two-legged stool, and it
is why trusts, estates and entity-interest transfers keep coming back `UNRESOLVED`.

The "when it earns its cost" column is load-bearing: **these are not all worth firing on every
parcel.** Doctrine 17 says authoritative before inferential — it does not say pull every record
every time.

---

## Build status — read this before using the table

**None of the sources below are implemented in this build.** Stage 1a is coded to the contract
(it emits the deed fields when supplied and `DEED-UNAVAILABLE (<county>, <date>)` when not),
but no recorder, probate, DBA, mortgage, docket, permit, licensing, EDGAR, 990 or CASS/RDI
route exists in this skill's code.

Consequences that are already true and already labelled:

- every assessor-only row is `TAX-ROLL-OWNER`, never `VERIFIED-OWNER`
- every private trust stops at `TRUST-NEEDS-DEED`
- `strong_address_match()` requires `not_cmra_or_agent_hub`, and with no CASS/RDI source that
  flag is `UNKNOWN` outside Florida — so it **fails closed** rather than guessing from the
  string

This is the largest functional gap in the skill and it is deliberate. It is the roadmap, not
a claim.

---

## The table

| Source | Resolves | When it earns its cost |
|---|---|---|
| **County recorder / clerk — vesting deed + subsequent instruments** | the actual title chain, grantee, vesting language, `as-of` date | **Always** on single-property runs; on batches for entity/trust/estate/conflict/recent-sale/high-value rows. **This is stage 1a** |
| **Recorded document *images*** (not the index) | signatures and **signer capacity** — "John Smith, Managing Member" — which the index omits | Whenever the registry gives officers but no control edge; often the only proof of who can sign |
| **Probate dockets** | executor / personal representative, heirs, devisees | Record owner or candidate is deceased, an estate is named, or mail comes back |
| **Assumed-name / DBA filings** | the operator behind a park's public name | Owner name ≠ the name on the sign — routine in MHP work |
| **Mortgages / deeds of trust / UCC** | borrower and guarantor names and addresses, signers | Large or opaque assets; in TX and other non-disclosure states the DoT loan amount is also the only price signal. **Never infer ownership from lending alone** |
| **Litigation + bankruptcy dockets** | managers, ownership percentages, receivers | Opaque entities, partner disputes, foreclosure, receivership, dissolved owners. Precedent: `Kopp v Fietta Realty Corp.` named the principal |
| **Planning / permit / code-enforcement / utility-board records** | the *authorized representative* who filed | The entity recently developed, expanded, subdivided or remediated — applications carry a live human and a phone |
| **State MHP / mobile-home-park licensing, health-dept permits, rent registries, utility CCNs** | current operator + contact | Any MHP or RV park. **Operator ≠ owner — segregate.** Precedent already in the ledger: NYS DHCR `sxi2-m23m` returned a park owner's *phone* |
| **SEC EDGAR** | responsible subsidiary / asset-management contact | Public-company or REIT-affiliated owners. Identify the asset-management function, not a random executive |
| **IRS Form 990 + state charity registries** | officers of churches, foundations, associations | Better than blanket-suppressing every nonprofit owner — 990s carry named officers and addresses |
| **Historical / superseded registry filings** | the officer who *signed at acquisition*, mergers, manager changes | Current officer lists routinely omit the person who actually bought the property |
| **USPS CASS / RDI / CMRA classification** | residential-vs-business, and whether an address is a mail drop | **Before** treating any address as residential — this replaces guessing from the string, and it preserves the apartment/suite identifiers `addr_key` currently throws away |
| **County owner-name + mailing-address portfolio search** | the owner's other parcels, name variants, assemblages | After identity resolution, **always** — it is free and it finds the assemblage. (The FL statewide cadastral cross-check in `county_access.md` is the one piece of this that *is* implemented.) |
| **Licensed title / skip platforms** (DataTree, CLEAR, TLOxp, Accurint) | the hard residual files | High-value unresolved only, and **only after confirming licensing, contract scope, source restrictions and permissible purpose.** This is a `## Blocked on Mitch` item, never self-serve |
| **A human** — title-company contact, ordering the document, direct mail, or a carefully identified gatekeeper call | the answer | Ambiguous high-value deals. Preferable to a fourth probabilistic vendor query, and often cheaper |

---

## Two notes that keep getting lost

**The recorder is not optional on a single-property run.** Contacting a prior owner is the
most expensive error this skill can make, and it is invisible without the recorder. A
recorder-vs-assessor conflict **stops all paid identity work** and emits `OWNERSHIP-CONFLICT`
(acceptance test 25) — it does not get resolved by preferring one source.

**The last row is a real option, not a fallback joke.** A title-company contact or a single
well-identified phone call is frequently cheaper and more certain than a fourth probabilistic
vendor query, and it is the correct move on an ambiguous high-value deal.
