# Tests

```sh
python3 tests/make_fixtures.py --verify     # generate fixtures into <cache_root>/fixtures
python3 -m pytest tests/ -q                 # 71 tests, offline
python3 scripts/validate_skill.py           # 15 structural checks
python3 evals/convert.py --check            # evals.json is not stale
```

## No test may spend vendor money

`conftest.py` blocks `socket.socket` and `socket.create_connection` for the whole session, so
an accidental network call raises instead of quietly billing. The only live call permitted
anywhere in this skill's test surface is a **zero-cost auth probe** — BatchData `POST {}`
(400 live / 401 dead), Sherpa `PUT /api/person {}` (403 dead), Melissa rejected keys ($0) —
and only behind `--probe`, which the suite never invokes.

## Fixture PII stays out of the repo

Fixtures are generated into `<cache_root>/fixtures/` (0700) by `make_fixtures.py`. Tests
`pytest.skip("fixtures absent — run tests/make_fixtures.py")` rather than fail when it has
not been run.

Two classes of fixture:

- **Public corporate filings, verbatim.** `NHG HOLDINGS LLC` doc `L06000038390` and
  `NILES BOLTON ASSOCIATES` doc `F94000002850`, with their agents, officers and addresses.
  These are public Florida corporate filings and the master spec permits them in-repo.
- **Everything else: structurally exact, values invented.** A recorded Tracerfy payload keeps
  its field names, ranking, line types, carriers and `dnc`/`tcpa`/`deceased`/`litigator`
  flags — but the person is synthetic and the digits are reserved-fictional `555-01xx`.

**This does not weaken the assertions.** Every test here asserts on *status and shape*:
that `Mobile` normalizes to `wireless`, that an identical mailing `addr_key` produces
`strong_address_match`, that Tracerfy alone yields `SINGLE-SOURCE-PHONE` rather than
`VERIFIED-PHONE`, that a `dnc: true` mobile is excluded from the launchcontrol Import tab.
None of those depend on which digits came back.

## Running the true controls

Drop the operator's recorded payloads into `<cache_root>/fixtures/real/` using the filenames
in `MANIFEST.json`. The `real_fixtures_dir` fixture picks them up; tests that need them skip
when it is absent. **Those files must never enter the repo.**

The two that matter most:

- **`tracerfy_trace_lookup_fortstockton.json`** — the negative control. A vendor field
  literally named `property_owner: true` on a person who is a resident of the park, not its
  owner, while the Pecos CAD roll names an out-of-state LLC. *A build that prints that person
  as the owner of that parcel has failed, regardless of every other test passing.*
- **`tracerfy_parcel_lookup.json`** — the Knox positive control. A perfect address anchor and
  a source-reported wireless line, which must still come out as `VERIFIED-MOBILE` +
  `SINGLE-SOURCE-PHONE` + `TAX-ROLL-OWNER` + `DNC-BLOCKED`, and must never be described as
  dial-ready.

## Test numbering

`test_acceptance.py` numbers its tests to match the master spec's 27 acceptance tests, so a
failure traces back to the measurement that motivated it. `test_octlib.py` covers the
normalizers and predicates that have no acceptance-test home.
