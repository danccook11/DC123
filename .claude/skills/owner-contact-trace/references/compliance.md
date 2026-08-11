# Compliance and safety

Read this before any deliverable ships, and before any outreach decision.

**Not an FCRA product.** Never for tenant screening, employment, credit or insurance.

---

## 1. The base rate

Assume **~two-thirds of found mobiles are DNC-registered** — measured 61.4% and ~65% on
separate runs.

**DNC applies to texts as well as calls.** Florida's FTSA is stricter than the federal TCPA.

Skip Sherpa's `/api/dnc/status` 403s, but `dnc_statuses` arrives **inline** on `/api/person`,
so the $100/mo add-on was already unnecessary. With Sherpa dead and Tracerfy live, it is moot.
**Do not buy a separate DNC product.** Any DNC-scrub purchase is a `## Blocked on Mitch` item.

---

## 2. The three emit rules

DNC and deceased are **disclosure gates, not data gates** — but as of 2026-08-11 the scrub is
live, so the gate has teeth. Tracerfy returns `dnc`, `tcpa`, `deceased` and `litigator` inline
on every person, and `dnc_check` scrubs an arbitrary number (`national_dnc`, `state_dnc` +
`state_dnc_list`, `litigator`, `is_clean`).

**(a) A number carrying a DNC value emits with it.** `dnc == true` → the row prints
`DNC — mail or email only`, is excluded from any texting-platform import tab, and is never
presented as a call target.

*The Knox control makes the point:* all three of the owner's numbers, including the Verizon
mobile, came back `dnc: true`. A perfect address anchor and a source-reported wireless line
still does not make a dialable row.

**(b) A number lacking a DNC value emits stamped:**

```
NOT YET SCRUBBED — do not dial or text
```

That is the residual gap, and it is now a *choice* — scrubbing costs credits, so `--scrub` is
an explicit flag with its own line in the budget estimate.

**(c) `deceased == true` is a hard stop.** Routed to estate/heir research, never dialled. It
is no longer `UNVERIFIED` — Tracerfy supplies it. Where no source ran, it is `UNKNOWN`, never
`N` (doctrine 18).

**Never label a whole workbook dial-ready. Label rows.** The `Read Me` sheet carries this
block at the top and states which numbers on this run were scrubbed and which were not.

---

## 3. What vendor booleans do NOT cover

*Adopted from the 2026-08-11 GPT-5.6 Sol consult. The state matrix below is a
`## Blocked on Mitch` item — route it past counsel.*

### `dnc: false` is not consent
It means "not found on the lists checked, at that time." Never call a row dial-ready on that
basis alone.

### Treat acquisition solicitation as potentially covered telemarketing
Do not assume an offer to *buy* is exempt because it is not an offer to sell.

### Record per number: DNC source, which lists were checked, jurisdiction, timestamp
Federal DNC access generally must be refreshed on a **31-day** cycle. **A scrub older than
that is stale and re-renders as `UNSCRUBBED`** — `octlib.outreach_eligible()` enforces the
age check and fails closed when the age is unknown.

### Maintain an internal do-not-call list
Entity-specific opt-outs are honoured for the required retention period, and **a CRM opt-out
overrides any vendor result.**

### No prerecorded or artificial-voice calls, and no bulk or automated texting
…without documented consent and a counsel-approved workflow. **The `launchcontrol` export is a
*texting* format — it inherits this constraint.**

### State-by-state matrix — counsel-maintained, never hard-coded from vendor logic
Calling hours, frequency caps, registration and bond requirements, consent standards, private
rights of action. Florida's FTSA is stricter than the federal TCPA; assume others are too
until checked.

### A personal mobile used by a business owner is not a B2B number
Do not reason your way around DNC on that basis.

### Call-recording consent rules apply
…if any call is recorded.

### DPPA
Never use DMV-derived data without a documented permissible purpose.

### GLBA
No covered nonpublic financial information, or vendor data derived from it, without a valid
exception and contractual assurance.

### "Not an FCRA product" is not sufficient
Acquisition marketing is not an FCRA permissible purpose, so **prohibit consumer-report
products and FCRA-regulated data outright in this workflow** — not merely disclaim them.

### Require vendor representations
Covering lawful collection, resale rights, source categories, non-DPPA/non-GLBA restrictions,
security, deletion and audit rights. **Record them in the capability manifest's lineage
field** — the same field `phone_attributed()` reads for upstream independence.

### Licensing
Where the brokerage researches on behalf of a *client* rather than for its own account,
private-investigator / skip-trace licensing rules may attach. **Flag for Mitch before doing
client-directed rundowns at volume.**

### Data governance
Retention limits, access controls, deletion handling and consumer opt-out workflows under
applicable state privacy and data-broker laws.

### Terms-of-use and automated-access restrictions bind even on publicly viewable records
**No CAPTCHA bypass, no pretexting, no credential sharing, no circumvention of access
controls.**

### `litigator` and `deceased` are vendor-reported risk indicators, not authoritative legal facts
Render as `REPORTED-`. `is_litigator` renders as `[TCPA LITIGATOR]` and is excluded from any
import tab.

### Stale numbers
Anything last seen more than 18 months ago carries a **reassigned-number warning**.

---

## 4. PII and write locations

**Minimum necessary. No raw source text in deliverables.** The redaction scan must catch
`(NNN) NNN-NNNN` and `+1 (NNN) NNN-NNNN` — `octlib.PHONE_RE`.

| What | Where |
|---|---|
| Intermediates, caches, fixtures, the ledger, the streamed Sunbiz zip | `<cache_root>/` — resolved at runtime, **outside any synced tree** |
| Final workbook / card **only** | `<project>/output/` — and only **after both gates pass** |
| Vendor keys | `~/.<vendor>/key`, mode 0600 in a 0700 dir; **never printed, never in a synced tree** |

`cache_root` precedence: `$OWNER_TRACE_CACHE` → `~/Library/Caches/claude-owner-enrich` →
`$XDG_CACHE_HOME/claude-owner-enrich` → `~/.cache/claude-owner-enrich`.

Never `/private/tmp` (swept at 3 days). Never the session scratchpad (dies with the session; a
re-run in a new session cannot resume).

**Why:** `CENSUS.json`, `HUMANS.json` and `phone_verdicts.json` carry names, home addresses,
phones and deceased flags. The Bane incident — iCloud root, mode 644, replicated to Apple and
the Windows box, deleted 2026-08-07 — is the precedent. iCloud also corrupts partial writes.

**Never publish a call list to a public artifact or repository.** Mitch pulled the land board
off public Pages within an hour on 2026-07-31.

---

## 5. Zoho write constraints

Currently absent from all 18 guardrails, so they are recorded here:

- **Never create Zoho `Leads`** — permission-denied on this key.
- **Never write narrative to a Contact `Description` field** — not on this org's layout;
  account-level notes only.
- Buyer-side pipeline lives in the **`Target_Accounts`** linking module, and its picklist
  values have **drifted from metadata** — match the casing of existing rows.
- **Never call Placecraft `create_contact` after `import_parcels`** — import auto-creates one
  contact per owner.

---

## 6. Route past counsel

The **state-by-state outreach matrix** is the item to route past counsel before any volume
outreach. Until it exists, `octlib.outreach_eligible()` requires
`state_outreach_policy_allows_channel` to be explicitly `True` and fails closed otherwise —
which means no row reaches `OUTREACH-ELIGIBLE` on policy grounds alone. That is intentional:
the conservative default is the correct one until the matrix is written.
