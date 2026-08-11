# OWNER RUNDOWN — template

The nine section headers below are **literal** and are grepped by
`evals/output_quality_evals.json` and by `validate_skill.py`. Do not reword them.

`CONFLICT:`, `AMBIGUOUS:` and `BENEFICIAL-CONTROL-UNKNOWN:` are literal tokens that appear
inline wherever they apply.

**The heading is `BEST NUMBER`, never `PRIMARY MOBILE`.** The words "PRIMARY MOBILE" may only
be printed when `phone_attribution_status == VERIFIED-PHONE` **and**
`line_type_status == VERIFIED-MOBILE`. Otherwise the number prints under its actual status —
`SINGLE-SOURCE-PHONE` or `HOUSEHOLD-PHONE`. A single-source number is still operationally
useful; deliver it, labelled as what it is.

**Two plausible principals → print both as rank 1 and rank 2. Never pick.**

---

## PROPERTY

- **Situs:** {{situs_address}}, {{situs_city}} {{situs_state}} {{situs_zip}}
- **Map:** https://www.google.com/maps/search/?api=1&query={{situs_address_urlencoded}}
- **APN:** {{apn_raw}} (`{{apn_norm}}`) · **County:** {{county}}, {{state}} · **FIPS:** {{fips}}
- **Acreage:** {{acres}} · **Land use:** {{landuse}}

## OWNER OF RECORD (AS OF {{as_of_date}}, PER {{deed|tax roll}})

- **Owner:** {{owner_of_record}}
- **Owner class:** {{owner_class}} / {{entity_type}}
- **Mailing:** {{owner_mailing_address}}, {{mail_city}} {{mail_state}} {{mail_zip}}
- **`ownership_status`:** {{VERIFIED-OWNER | TAX-ROLL-OWNER | OWNERSHIP-CONFLICT | RECORD-OWNER-RESOLVED | UNKNOWN}}
- **Basis:** {{deed instrument_no + recording_date | assessor roll only}}
- **Corroborating sources:** {{sources}}
- `CONFLICT: {{candidate_a}} (per {{source_a}}) vs {{candidate_b}} (per {{source_b}})` — *omit
  this line entirely when there is no conflict; when present, all paid identity work is
  stopped.*

## ENTITY CHAIN

- **Hops followed:** {{n}} of 3 *(an operational limit, not a confidence statement)*
- {{hop_1_entity}} — `sos_doc {{doc}}` · {{status}} · {{filing_type}} · formed {{state_of_formation}}
- {{hop_2_entity}} — `sos_doc {{doc}}` · …
- **UNRESOLVED FRONTIER:** {{entity names the chain stopped at}} — *always printed when the
  chain did not terminate in a natural person. Omitting it implies the chain ended.*
- **`cordata_vintage`:** {{vintage}} {{warn if today − vintage > 45 days}}
- `BENEFICIAL-CONTROL-UNKNOWN: {{reason}}` — *entity-interest transfer, nominee arrangement,
  land trust, or series LLC where public records cannot establish current control.*

## REGISTERED AGENT (AGENT — NOT THE OWNER)

- **Agent:** {{ra_name}} ({{P|C}}) · {{ra_address}}
- **Commercial agent:** {{yes → recorded and skipped, never contacted | no}}
- *A registered-agent edge never establishes control. This section exists so the agent is
  recorded, not so it is called.*

## RESOLVED HUMAN + ROLE EVIDENCE

**Rank 1 — {{person_name}}**

- **Role:** {{title}} via edge `{{edge_type}}`
- **Role evidence:** {{which instrument or filing names them, in what capacity, dated}}
- **`role_status`:** {{VERIFIED-AUTHORITY | PROBABLE-AUTHORITY | AUTHORIZED-CONTACT | BENEFICIAL-CONTROL-UNKNOWN | UNKNOWN}}
- **`identity_tier`:** {{1|2|3}} · **Anchor:** {{anchor_basis}} · **`anchored`:** {{Y|N|UNKNOWN}}
- **Address:** {{person_addr}}

**Rank 2 — {{person_name_2}}** *(printed whenever `ambiguity: true`)*

- `AMBIGUOUS: rank 1 and rank 2 are within 20 points / both anchored / both carry a control
  title — both are emitted and neither is selected.`

## BEST NUMBER

- **Number:** {{phone}} — printed under `{{phone_attribution_status}}`
- **`phone_attribution_status`:** {{VERIFIED-PHONE | SINGLE-SOURCE-PHONE | HOUSEHOLD-PHONE | CONTRADICTED | UNKNOWN}}
- **`line_type_status`:** {{VERIFIED-MOBILE | REPORTED-MOBILE | LANDLINE | UNKNOWN}}
- **`line_type_source`:** {{tracerfy.phones[].type | sherpa.PhoneNumber.type | one-api.Phone-N Type}}
- **Carrier:** {{carrier}} · **Last seen:** {{last_seen}} {{reassigned-number warning if >18mo}}
- **DNC:** {{true|false|UNSCRUBBED}} · **`dnc_checked_at`:** {{ts}} · **lists:** {{dnc_lists_checked}}
- **Litigator:** {{Y|N|UNKNOWN}} · **Deceased:** {{Y|N|UNKNOWN}}
- **`compliance_status`:** {{OUTREACH-ELIGIBLE | DNC-BLOCKED | UNSCRUBBED | LITIGATOR | DECEASED-HOLD}}
- **Reverse-phone verdict:** {{CONFIRMED | CONFIRMED-nonmobile | LIKELY | RELATIVE-ONLY | CONTRADICTED | DEAD | (none — prints as "band (unverified line type)")}}

## ALTERNATES

| # | Number | Attribution | Line type | Carrier | Last seen | DNC | Notes |
|---|---|---|---|---|---|---|---|
| 1 | {{alt_1}} | {{status}} | {{type}} | {{carrier}} | {{last_seen}} | {{dnc}} | {{notes}} |
| 2 | {{alt_2}} | … | … | … | … | … | … |

- **Email:** {{email}}
- **Household / relatives:** {{household_others}} — *a household member is not the owner*
- **Relationship cluster:** `rel_cluster_id {{id}}` — {{n}} owners at this mailing address

## COMPLIANCE

- {{`DNC — mail or email only` when dnc == true}}
- {{`NOT YET SCRUBBED — do not dial or text` when no DNC value is present}}
- {{`[TCPA LITIGATOR]` when is_litigator == Y — excluded from every import tab}}
- {{`REPORTED-DECEASED — hard stop, routed to estate/heir research` when deceased == Y}}
- Not an FCRA product. Never for tenant screening, employment, credit or insurance.
- DNC applies to texts as well as calls. FL FTSA is stricter than the federal TCPA.

## NAMED GAPS

- {{`DEED-UNAVAILABLE ({{county}}, {{date}})` — no online recorder route}}
- {{`TRUST-NEEDS-DEED` — private trust, no registry lists trustees}}
- {{`UNEVALUATED — {{ST}} registry route down ({{code}}, probed {{ts}})`}}
- {{`agent-desk gate UNEVALUATED — address-frequency index is Florida-only`}}
- {{`foreign FL filing not followed to {{state}} — named gap`}}
- {{anything checked and rejected, stated as such — distinct from never looked}}

---

# Worked example (fully synthetic)

Every value below is invented. The parcel, owner, entity and numbers do not exist; phone
digits are in the reserved-fictional `555-01xx` range. It exists to show shape, not data.

## PROPERTY

- **Situs:** 4120 EXAMPLE MILL RD, DEMOVILLE TN 37999
- **Map:** https://www.google.com/maps/search/?api=1&query=4120+EXAMPLE+MILL+RD+DEMOVILLE+TN+37999
- **APN:** 099  01234 (`09901234`) · **County:** Demo, TN · **FIPS:** 47999
- **Acreage:** 41.2 · **Land use:** Agricultural

## OWNER OF RECORD (AS OF 2026-08-11, PER tax roll)

- **Owner:** EXAMPLE RIDGE HOLDINGS LLC
- **Owner class:** entity / llc
- **Mailing:** 88 SAMPLE ST, DEMOVILLE TN 37999
- **`ownership_status`:** TAX-ROLL-OWNER
- **Basis:** assessor roll only — no online recorder route for Demo County
- **Corroborating sources:** county GIS layer (retrieved 2026-08-11)

## ENTITY CHAIN

- **Hops followed:** 1 of 3
- EXAMPLE RIDGE HOLDINGS LLC — `sos_doc UNEVALUATED` · status UNKNOWN
- **UNRESOLVED FRONTIER:** EXAMPLE RIDGE HOLDINGS LLC
- **`cordata_vintage`:** n/a — TN, not a Sunbiz state
- `BENEFICIAL-CONTROL-UNKNOWN: TN registry route down (HTTP 500, probed 2026-08-11); no
  officer or member record obtainable.`

## REGISTERED AGENT (AGENT — NOT THE OWNER)

- **Agent:** UNEVALUATED
- **Commercial agent:** UNKNOWN

## RESOLVED HUMAN + ROLE EVIDENCE

**Rank 1 — (none)**

- **Role:** UNKNOWN
- **Role evidence:** none — no government record names a natural person
- **`role_status`:** UNKNOWN
- **`identity_tier`:** UNKNOWN · **Anchor:** UNKNOWN · **`anchored`:** UNKNOWN

## BEST NUMBER

- **Number:** (none — no named human, so no vendor call was made)
- **`phone_attribution_status`:** UNKNOWN
- **`line_type_status`:** UNKNOWN
- **`compliance_status`:** UNSCRUBBED

*Doctrine 2: with no named human, asking a vendor who owns this parcel is exactly the call
this skill does not make. The row completes as an explicit disposition, not a blank and not a
guess.*

## ALTERNATES

(none)

## COMPLIANCE

- Not an FCRA product. Never for tenant screening, employment, credit or insurance.

## NAMED GAPS

- `UNEVALUATED — TN registry route down (HTTP 500, probed 2026-08-11)`
- `DEED-UNAVAILABLE (Demo, 2026-08-11)`
- Parcel disposition: `UNEVALUATED` — we never resolved a human; we did not look-and-reject.
