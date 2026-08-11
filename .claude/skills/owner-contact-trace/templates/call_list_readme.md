# Read Me — dialling gate and liability disclosure

This becomes the workbook's **`Read Me`** sheet, rendered as a two-column table
(`Item` | `Statement`) at the top of every call-list deliverable.

> **RECONSTRUCTED 2026-08-11** — the original 20-row disclosure block in
> `build_parcel_master.py:466-488` was not available in the build environment. This is
> written to the same purpose and extended with the `UNSCRUBBED` and litigator lines the
> current pipeline requires. **Review against the original before first delivery.**

| Item | Statement |
|---|---|
| **1. What this list is** | A research work product identifying, per parcel, the record owner as of a stated date, any documented human authority, and contact numbers with their source-reported line type. It is an input to a human outreach decision. |
| **2. What this list is not** | It is **not** a consumer report and **not an FCRA product**. It must never be used for tenant screening, employment, credit, insurance, or any other FCRA-permissible-purpose decision. Acquisition marketing is not an FCRA permissible purpose. |
| **3. Three separate conclusions** | Record ownership, documented authority, and phone attribution are three separate columns and three separate verdicts. A confirmed mobile on an unknown owner is still an unknown owner. Do not read across the row as a single claim. |
| **4. `TAX-ROLL-OWNER` is not `VERIFIED-OWNER`** | The assessor roll is a billing record, not a title record: it lags conveyances, keeps dissolved grantees, and omits vesting language. A row marked `TAX-ROLL-OWNER` has **not** been confirmed against a recorded deed. |
| **5. `RECORD-OWNER-RESOLVED / BENEFICIAL-CONTROL-UNKNOWN`** | The title-holding entity is identified but its current controller is not publicly establishable — typically a trust, land trust, nominee arrangement, series LLC, or an entity whose membership interests were sold without a deed recording. This is a completed row. It is not a failed one, and it must not be guessed. |
| **6. `UNEVALUATED` means we never looked** | It is a distinct verdict from "we looked and rejected it". Conflating the two is the easiest way for a coverage report to lie. Every input APN carries a disposition from the closed vocabulary. |
| **7. Dial-readiness is a per-ROW property** | **This workbook as a whole is never labelled dial-ready.** Read the `compliance_status` on each row. |
| **8. `NOT YET SCRUBBED — do not dial or text`** | Any row carrying this stamp has a number with **no DNC value** — it came from a source that does not return one, or the scrub was not run. Do not dial it and do not text it until it is scrubbed. |
| **9. DNC applies to texts as well as calls** | Not only voice. The `launchcontrol` export is a **texting** format and inherits every constraint on this sheet. |
| **10. `dnc: false` is not consent** | It means "not found on the lists checked, at that time". It is not permission, and it is not a defence. |
| **11. A DNC scrub goes stale** | Federal DNC access generally must be refreshed on a **31-day** cycle. A scrub older than that re-renders as `UNSCRUBBED` and the row returns to item 8. `dnc_checked_at` and `dnc_lists_checked` are on every row for exactly this reason. |
| **12. Base rate** | Assume **~two-thirds of found mobiles are DNC-registered** — measured 61.4% and ~65%. Florida's FTSA is stricter than the federal TCPA; assume other states are too until counsel confirms otherwise. |
| **13. Reassigned-number hazard** | Any number last seen more than **18 months** ago carries a reassigned-number warning. Recency outranks line type: a wireless number last seen 2016 is worse than a landline seen this year. |
| **14. `deceased` is a hard stop** | Rows flagged `REPORTED-DECEASED` are routed to estate and heir research and are **never dialled**. A vendor `deceased` boolean is a vendor report, not a death certificate — and an executor is an estate contact, not necessarily an owner. |
| **15. `[TCPA LITIGATOR]`** | Rows flagged as litigators are excluded from **every** import tab and from any automated channel. `litigator` is a vendor-reported risk indicator, not an authoritative legal fact. |
| **16. Line type is source-reported, never computed** | Only `tracerfy.phones[].type`, `sherpa.PhoneNumber.type` or `one-api "Phone-N Type"` may produce the word "mobile". US number portability makes any libphonenumber-derived classification structurally incapable. `line_type_source` is on every row with a line type; if it is blank, the line type is not trustworthy. |
| **17. A vendor's confidence is not a verdict** | `matchConfidence`, `matched: true` and a field literally named `property_owner: true` are recorded for audit and are **never** inputs to any acceptance decision. The address anchor is the verdict. |
| **18. `HOUSEHOLD-PHONE` and `SINGLE-SOURCE-PHONE` are not `PRIMARY MOBILE`** | They are operationally useful and are delivered on purpose — labelled as what they are. A single-source number has one upstream source behind it; two resellers of the same aggregator are one source wearing two hats. |
| **19. Suppressed owners are held back, not deleted** | Institutional, government and active-operator owners are suppressed **with a recorded matched pattern** and appear on the `Dropped (audit)` sheet with the reason. Nothing is removed silently. Check that sheet before concluding a parcel was missed. |
| **20. Internal do-not-call list and CRM opt-out** | An entity-specific opt-out is honoured for the required retention period, and **a CRM opt-out overrides any vendor result**. Check the CRM before dialling, not after. |
| **21. No prerecorded voice, no bulk automated texting** | Not without documented consent and a counsel-approved workflow. Call-recording consent rules apply if any call is recorded. A personal mobile used by a business owner is not a B2B number — do not reason around DNC on that basis. |
| **22. Data handling** | Minimum necessary. No raw source text appears in this workbook. Retention limits, access controls, deletion handling and consumer opt-out workflows apply under state privacy and data-broker law. **Never publish this workbook to a public artifact, repository, or shared link.** |
| **23. Scrub status of THIS run** | `{{n_scrubbed}}` numbers were scrubbed at `{{scrub_timestamp}}` against `{{dnc_lists_checked}}`. `{{n_unscrubbed}}` numbers carry no DNC value and are stamped `NOT YET SCRUBBED — do not dial or text`. |
| **24. Provenance** | Every phone carries `{source, retrieved_at, anchor_basis, identity_tier, confidence_basis}`. A $0 name parse and a source-reported carrier record are both present in this workbook and are distinguishable by those fields. Use them. |
