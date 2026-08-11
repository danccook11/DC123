# Veil piercing — entities, trusts, and the FL bulk registry

Read this before any entity, trust, LP, series-LLC or multi-hop work, and before touching
`sunbiz_pierce.py`. The record offsets in "Record layout" are the most load-bearing detail in
this skill: getting them wrong does not produce an error, it produces plausible garbage.

---

## 1. Model it as a directed evidence graph, not a scored list of names

Allowed edge types:

```
title-holder · member · managing-member · manager · general-partner · limited-partner
officer · director · trustee · personal-representative · registered-agent · parent
successor · unknown
```

**`registered-agent`, `director`, generic `officer` and `limited-partner` edges do not
establish control** and can never by themselves produce a `DOCUMENTED-CONTROLLER-RESOLVED`.
`octlib.CONTROL_EDGES` / `octlib.NONCONTROL_EDGES` encode this and `octlib.role_ok()`
enforces it; `delivery_gate.py` re-checks it on the finished workbook.

**Never recurse through a registered-agent entity.** That follows service companies
(CT Corporation, CSC), not ownership.

**Preserve every competing manager or member.** A score may *order review*. It may never
convert an unsupported role into a controller.

Every edge carries a date and a source. An undated edge is not evidence.

---

## 2. Entity selection — resolve by identifier, not by name

Match on **jurisdiction + entity number** whenever either is available from a deed, assessor
record, or prior filing.

If no entity number is available, require an **exact legal-name match plus at least two
independent discriminators** drawn from `{principal address, mailing address, formation
jurisdiction, formation date, deed party, prior filing}`, **with no competing candidate**.

A name-only or suffix-stripped match is `AMBIGUOUS-ENTITY-MATCH` and stops there.

**Do not prefer an active filing over an inactive one merely because it is active.** Dissolved,
merged and inactive entities routinely still hold title, and preferring `status == "A"` will
happily select a newer unrelated namesake over the inactive entity actually on the deed.
Search mergers, conversions, reinstatements, dissolution instruments and successor filings
before concluding an entity is gone.

`octlib.entity_ok()` implements this predicate.

---

## 3. Candidate ranking — review order only, never acceptance

Extract the registered agent (type byte `P`/`C`) and the officers. Score each *person*-typed
officer:

| Component | Points |
|---|---|
| base | 5 |
| filed address `addr_key` equals the parcel mailing `addr_key` | **+100** |
| title ∈ `CONTROL_TITLES` | +20 |
| non-commercial person RA, anchored | 90 |
| non-commercial person RA, not anchored | 10 |

**A person RA is not presumptively better than a commercial one; it is a lead, and its
promotion still requires a control-bearing edge.**

Keep the top 3, ranked, and **emit the unresolved frontier alongside them**.

```
CONTROL_TITLES = {MGR, MGRM, MEM, AMBR, P, PRES, CEO, MP, TRUS, TR, D, PD}
```

**This is a deliberate change from the shipped set, not a transcription.** The shipped set
contained `GRM`/`GR`/`RM`, which were artifacts of the stride bug in §7 and are correctly
dropped. `D` (9,571) and `PD` (3,943) are added on the corrected 60k-record frequency
evidence; no prior evidence file contains them.

Full corrected title census:

```
MGR 20457 · P 10091 · D 9571 · AMBR 8736 · MGRM 6052 · VP 4251 · PD 3943 · Pres 1627
S 1583 · Mana 1503 · CEO 1412 · VD 1281 · Dire 1174 · PRES 1091 · Auth 1073 · SD 1025
T 1001 · MBR 592 · Trea 493
```

---

## 4. Multi-hop

**38% of FL entities have a company-typed officer and are dead-ended today (19 parcels lost).**
This was the single largest gap in the prior code.

Real unfollowed hop-1 targets in the data:

```
13350 SEBASTIAN LLC            -> NN MARKETPLACE LLC
68V CREEKCHASE FL 2022 LLC     -> 68 VENTURES, LLC
68V NAVY CROSSING HOLDINGS LLC -> 68VENTURES
ALTA DRIVE PARTNERS LLC        -> Alterra IOS Venture II Master LP
```

Seed pass 2's target set with every `type == "company"` officer/RA name from pass 1 and
recurse to 3 hops with a visited set and a cycle guard.

**Build a random-access index; do not claim one streamed pass resolves multiple hops.** Hop-2
targets are unknowable until hop-1 records are parsed, and the entity that satisfies hop 2 may
have appeared *earlier* in the stream and already scrolled past. Either:

- **(a, recommended)** build a persistent `normalized_name → file_offset` index on the first
  pass, then seek per hop. The file is local and fixed-width, so this is cheap; or
- **(b)** run deterministic iterative passes, one per hop, **and say so**.

A full pass is ~90 s measured, so three passes is ~4.5 minutes. That is affordable and honest.

**"Three hops" is an operational limit, not a confidence statement — always emit the
unresolved frontier** (the entity names you stopped at) rather than implying the chain ended.

Hop-1 names come out of a 42-char field carrying the registrant's own spelling — `68VENTURES`
versus `68 VENTURES, LLC` — so route every hop name through `strip_suffix()` **and** the tight
form (acceptance test 18). Cost: $0.

---

## 5. Trusts — name parsing generates SEARCH LEADS ONLY, never a resolved trustee

No Secretary of State registers a trust. A person named inside `SMITH FAMILY TRUST` may be
the settlor, a beneficiary, a deceased grandparent, or nobody currently living.

**Promote someone to trustee only from** a vesting deed, trustee deed, certification or
memorandum of trust, recorded successor-trustee instrument, probate record, or equivalent
government source.

For **land trusts**, report these as **separate** fields:

- `record trustee / title holder`
- `disclosed beneficiary`
- `authorized contact`
- `beneficial controller`

Nominee agreements and unrecorded beneficiary assignments can make beneficial control
publicly unknowable. In that case emit `BENEFICIAL-CONTROL-UNKNOWN` and stop.

**Never assign HIGH confidence from residual name tokens.**

With that ceiling understood, the two mechanisms are:

**(a) Free name parse against the frozen lexicon — output tier `LEAD` only.**
`references/name_lexicon.json` is frozen and shipped. Batch mode *augments* it from the live
list; **single-property mode uses it as-is**, because a one-row dataset gives every token
support 0 and the $0 leg would silently vanish (acceptance test 11). Require `FIRST[w] >= 2`
support before promoting a token to a person. Handle `LAST FIRST MID`, `FIRST MID LAST`, and
the shared-surname idiom `BRIAN & CONNIE PIERCE LIVING TRUST → Brian Pierce + Connie Pierce`.

**Guardrail:** `octlib.is_company()` blocks person-parsing anything with a corporate suffix
and no trust marker, or you get `MARTIN MARIETTA MATERIALS INC → "Marietta Martin"` and
`CARTER MILL LLC → "Mill Carter"`. CARTER and MILL are both legitimate personal names — the
lexicon cannot save you here, only the suffix can.

**(b) Residual-token rule.** ≥2 residual tokens after stripping trust keywords →
`trust (named trustee)`, HIGH; else `trust (private)`, LOW, disposition `TRUST-NEEDS-DEED`.

**There is no deed-pull implementation anywhere in the corpus, and this build does not add
one.** `TRUST-NEEDS-DEED` is a named gap, not a solved case. NC registers neither family
trusts nor estates at all; the trustee is on the deed, and the assessor mailing address is
frequently already the trustee's.

**Eponymous entities are leads, not conclusions.** `PARKER PROPERTIES INC → Joe Parker` and
`SANDERS FARMS LLC → Summer Sanders` may reach `role_status: PROBABLE-AUTHORITY` **only when
a registry officer record independently names that person**. With the name inference alone
they cap at `LEAD` / `BENEFICIAL-CONTROL-UNKNOWN` (acceptance test 12). A surname in a company
name is not evidence of control.

---

## 6. Entity forms that break a naive officer walk

- **LPs** — follow the **general partner**. Limited partners are passive by definition and are
  never presumed controllers.
- **Manager-managed LLCs** — a `manager` / `managing-member` edge outranks any member-name
  inference.
- **Series LLCs** — take the **exact series name off the deed**. The parent LLC is not
  automatically the owner of every series asset; treat state by state. Search assumed-name/DBA
  filings and series designations without collapsing them into the parent.
- **Dissolved / merged entities** — inactive status does not terminate title. See §2.
- **Entity-interest transfers** — these leave the grantee unchanged and record no deed. Public
  records can establish the title-holding entity while its current equity control stays
  unknown. This is the ClearTrail/Parkview pattern: label it
  `RECORD-OWNER-RESOLVED / BENEFICIAL-CONTROL-UNKNOWN`, never "unresolved".

---

## 7. Deceased owners and probate — a branch, not a flag

A `deceased` marker does not identify the successor owner.

Search the probate docket in the decedent's domicile **and** in the property county when they
differ. Distinguish `executor / personal representative`, `devisee`, `heir`,
`surviving joint tenant`, `life tenant`, `remainderman`.

**An executor is an estate contact, not necessarily an owner.**

Vendor-supplied `deceased` values render as `REPORTED-DECEASED` until corroborated by an
obituary, probate filing, or SSDI-equivalent record. Tracerfy's boolean is a vendor report,
not a death certificate.

---

## 8. Sunbiz bulk mechanics (FL, free, primary route)

| Item | Value |
|---|---|
| Host | `sftp.floridados.gov` |
| User | `Public` |
| Password | `PubAccess1845!` |
| File | `doc/Quarterly/Cor/cordata.zip` |
| Size | **1,819,049,954 bytes** |
| Members dated | 2026-07-10 |
| Downloaded | 2026-08-10 (already on disk at `<cache_root>/sunbiz/cordata.zip`) |
| Daily deltas | `doc/cor/YYYYMMDDc.txt` — use `--deltas-since` |
| Record layout definitions | `https://dos.sunbiz.org/data-definitions/cor.html` |

**The credential is published by the state on dos.fl.gov. It is a public-access credential,
not a secret, and it is recorded here literally and labelled as such.** The built skill reads
it from operator config (`config/credentials.example.yaml`), never inline in source. The
publishing page 403s to plain curl, so if the credential ever changes, use the Browser pane —
not WebFetch, not curl.

**macOS `curl` has no sftp protocol.** Drive `/usr/bin/sftp` under `/usr/bin/expect` —
`scripts/getcor.exp`.

**Stream with `unzip -p`, never extract.** The 18.5 GB expansion is prohibited anywhere,
iCloud or not.

**Timings, measured.** Download ~4 min. A full 10-member pass is **~90 s** in py3.9 (8.8 s per
1.85 GB member, 12.8M records). The inflated "~6 min" figure is why multi-hop was skipped in
the first place — it was never true.

**Do not re-download unless the quarterly has rolled.**

### Vintage management

`sunbiz_pierce.py` emits `cordata_vintage` (member mtime) into every ledger row and into the
workbook's Sources & Method sheet. If `today − vintage > 45 days`, warn and offer the delta
pull. Any `no Sunbiz match` where the county record shows a recent conveyance is labelled
**`possible post-snapshot formation`**, not a flat miss.

---

## 9. Record framing — measured 2026-08-11, and this correction is load-bearing

Records are **1440 data chars + CRLF = 1442 bytes on disk**.

```
head -1 cordata.txt | wc -c   ->  1442
od -c                          ->  shows \r\n
awk 'length($0)'               ->  1441      # because the \r is inside $0
```

The earlier "1440 + newline" measurement was taken after Python text-mode newline translation
ate the `\r`.

**Consequences if left wrong:**

1. `record_index * 1441` seeks slide one byte per record and destroy the file after record 1.
2. Binary reads split on `b"\n"` leave a trailing `\r`, so a `len(line) == 1440` check rejects
   **every** record.
3. `awk` one-liners put `\r` into the last field.

**Mandate:**

```python
line = raw.decode("latin-1").rstrip("\r\n")   # latin-1, NOT utf-8 — the registry
assert len(line) == 1440                      # contains non-UTF8 bytes
```

Ship a **CRLF-terminated** test fixture (acceptance test 10).

---

## 10. Record layout — use the 2026-08-11 measured offsets

The "fields drift past byte 500" claim in the shipped parser is **wrong**. The tail is
fixed-width: byte 587 is `P`/`C` in 120,000 of 120,000 records.

1-based inclusive:

| Bytes | Field |
|---|---|
| `1–12` | doc number |
| `13–204` | entity name |
| `205` | status `A`/`I` |
| `206–220` | filing type |
| `221–262` / `263–304` | principal addr 1 / 2 |
| `305–332` / `333–334` / `335–344` | principal city / state / zip |
| `347–388` / `389–430` | mailing addr 1 / 2 |
| **`431–458` / `459–460` / `461–470`** | **mailing city / state / zip** — *not parsed by the shipped code* |
| `473–480` | file date |
| `481–494` | FEI/EIN |
| `495` | more-than-six-officers `Y`/`N` |
| `504–505` | state of formation |
| `506–544` | three 13-byte annual-report blocks |
| **`545–586`** | **RA name** — type `P` → last(20) / first(14) / middle(8) |
| **`587`** | **RA type byte** (`P`/`C`) |
| `588–629` / `630–657` / `658–659` / **`660–668`** | RA addr / city / state / **zip (9 chars, NOT 10)** |
| **`669 + 128·k`, k=0..5** | **officers** — block = title(4) · type(1) · name(42) · addr(42) · city(28) · state(2) · zip(9) |
| `1437–1440` | filler |

**Fixing this yields +5,148 officers (+6%) on a 60k sample and 100% correct titles.** The
shipped parser produced 142 of 253 titles as `None`, plus junk like `VENI` and `TSD`.

### Reject rules

- Reject any parsed name containing `\d{4}` or an `[A-Z]{2}\d` run — that is a slid window
  (`'E   FL34293  VPASPAYE'`).
- Then run every surviving name through a **person-plausibility filter before paying**.
  Officer parsing is ~60% clean and produced `FEDERAL NAVY`, `FUNERAL SCI`,
  `MINERAL CONTINENTAL`, and initial-only tokens. **10 of 57 name queries were rejected
  pre-spend.**

---

## 11. Two free inverse indexes the bulk file gives that no scraper can

### `person → every entity they officer/agent`

`sunbiz_person_index.json`, 246 keys, schema `{"NORMALIZED NAME": [{entity, doc, status, title}]}`.

**Defect to fix:** it appends the same `(doc, person)` once per record hit — `CJB HOLDINGS`
shows `RA/GR/RA` for one doc. **Dedupe on `(doc, name, title)`.**

**Contradiction to resolve deliberately:** the keep-gate is `len(v) >= 1` while the comment
claims "only people tied to more than one entity". The code does not do what the comment says.
Pick one and say which. *This build keeps `len(v) >= 1`* — the single-entity rows are needed
for the own-name-portfolio test below — and corrects the comment.

Multi-entity people found: `LARS HAGSTROM` 5 · `CHRISTOPHER J BLUNTZER` 3 ·
`RICHARD E HAGSTROM` 3.

### `address → count of entities filing there`

Built from `norm_name(line[220:262])` (principal address line 1) across every record. Attached
as `fl_entities_at_this_address` (RA) and `fl_entities_at_principal_addr`.

`AGENT_DESK_MIN = 15`. Measured hubs:

```
7901 4TH ST N                 70,796
7901 4TH ST. N, STE. 300      53,988
150 SE 2ND AVE                 1,381
5728 MAJOR BLVD.                 959
7978 COOPER CREEK BLVD           523
401 East Las Olas Blvd.          491
```

Person-level rule: more than ~20 active entities with ~0 own-name entities is a filing agent,
not a principal (`VEDRANI,NATHAN` — 160 active FL entities).

### Ready-made classification vocabularies

**Address level:** `LIKELY RESIDENCE (n FL cos)` n≤3 · `COMMERCIAL suite (n)` ·
`small office / shared (6..23)` · `AGENT/OFFICE HUB (27..140 FL cos)`

**Person level:** `PROFESSIONAL AGENT (gatekeeper)` · `PRINCIPAL (own-name portfolio)` ·
`PRINCIPAL / small portfolio` · `MIXED - review`

### Scope caveat — state it explicitly

The address-frequency index is built from the **FL bulk file**, so
`fl_entities_at_this_address` exists **only for Florida**. For TN/NC/TX/NY parcels the
agent-desk gate is `UNEVALUATED`, not `residential`. **A missing count must never read as a
clean pass** (acceptance test 9). `octlib.mail_class()` enforces this.

---

## 12. Foreign filings are an unfollowed population, not a solved case

`filing_type` (bytes 206–220) distinguishes domestic `FLAL` / `DOMP` / `DOMLP` from foreign
`FORL` / `FORP` / `FORLP`. Bytes 504–505 carry the state of formation.

**38 of 124 matched entities were foreign filings and nothing follows a foreign entity to its
home registry.** The 17 ledger rows reading
`NOT PIERCED … possibly a foreign entity, dissolved, or a name variant` are exactly this
population.

**Named gap.** Do not treat a foreign FL filing as pierced.
