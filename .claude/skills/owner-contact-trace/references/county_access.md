# County access — endpoints, field maps, per-county traps

Read this before touching any county layer. The machine-readable form of every section below
is `config/counties/*.json`; this file is the prose the configs are derived from, and it
carries the traps the JSON can only summarize.

`county_fetch.py --county tn_knox --apn "090 07403"` emits the census row.

Each config carries `{layer_url, alt_layer_url, proxy, headers, http_method,
parcel_id_field, parcel_id_aliases, owner_fields, mail_fields, situs_fields, extra_fields,
csz_mode, throttle_s, verified, traps[]}`.

---

## Florida — 13 verified counties

| County | Parcel layer | Parcel id | Owner | Mailing |
|---|---|---|---|---|
| **Duval** | `maps.coj.net/coj/rest/services/CityBiz/Parcels/MapServer/0` | `RE` (SPACE not dash, e.g. `019608 0050`; also `RE_NOSPACE`) | `LNAMEOWNER`, `LNAME2` | `MAILADDR1/2/3`, `MAILCITY`, `MAILSTATE`, `MAILZIP` |
| **Escambia** | `gismaps.myescambia.com/arcgis/rest/services/Individual_Layers/parcels/MapServer/0` | `REFNUM` | `OWNER` | `MAILADDRESS1/2`, `MAILCITY`, `MAILSTATE`, `MAILZIP` |
| **Indian River** | `gisportal.ircgov.com/server3/rest/services/IRCPA/Parcels_MS/MapServer/0` | `PP_PIN` | `OWNER_NAME`, `OWN_LNAME` | `OWN_ADDR1/2/3`, `OWN_CITY`, `OWN_STATE`, `OWN_ZIP` |
| **Lake** | `gis.lakecountyfl.gov/lakegis/rest/services/OpenData/OpenData1/MapServer/12` | `ParcelNumber` | `OwnerName` | `OwnerAddress`, `OwnerCity`, `OwnerState`, `OwnerZip` |
| **Lee** | `services2.arcgis.com/LvWGAAhHwbCJ2GMP/.../Lee_County_Parcels/FeatureServer/0` | `STRAP` | `O_NAME`, `O_OTHERS` | `O_CAREOF`, `O_ADDR1/2`, `O_CITY`, `O_STATE`, `O_ZIP` |
| **Leon** | `intervector.leoncountyfl.gov/intervector/rest/services/MapServices/TLC_OverlayParNALPublic_D_WM/MapServer/0` | `TAXID` | `OWNER1/2` | `ADDR1/2/3`, `ZIP1` — **`ADDR2` packs `"CITY ST ZIP"`, parse it** |
| **Pinellas** | `egis.pinellas.gov/gis/rest/services/PublicWebGIS/Parcels/MapServer/1` | `PARCELID` / `STRAP` | `OWNER1/2` | `OWNADD_1/2`, `OWNCITY`, `OWNSTATE`, `OWNZIP` |
| **Seminole** | `utility.arcgis.com/usrsvcs/servers/9b9c9fd45bdc4c39a2bd518da39d1e1c/rest/services/InformationKiosk/MapServer/1` | `ParcelNumber` | `OwnerName` | `OwnerAddress`, `Address2`, `MailingCity`, `Zip` — **GET ONLY, POST 400s** |
| **St. Johns** | `www.gis.sjcfl.us/portal_sjcgis/rest/services/Parcel/MapServer/0` | `PIN` / `STRAP` | `PRP_NAME` | `OWN_ADDR_1/2`, `OWN_CITY`, `OWN_STATE`, `OWN_ZIPCOD` |
| **Volusia** | `maps2.vcgov.org/arcgis/rest/services/MapIT/MapServer/120` | `PARID` / `ALT_ID` | `OWNER1/2` | `MAILADDR1/2/3`, `MAILCITY`, `MAILSTATE`, `MAILZIP` |
| **Orange** | `ocgis4.ocfl.net/.../MapServer/56` | `PARCEL` | `NAME1/2` | **NONE on this layer — use the OCPA fix below** |
| **Collier** | `services2.arcgis.com/SlIq32SqARUHIhSx/.../Parcels/FeatureServer/42` | `FOLIO` | `NAME1/2` | **NONE (owner name only)** |
| **Monroe** | `mcgis4.monroecounty-fl.gov/arcgis/rest/services/Parcels/MapServer/0` | `RECHAR` | **NONE** | **NONE** |

### Orange FL mailing-address fix (found 2026-08-10)

The county OpenData parcel layer carries **no owner mailing fields**. Use OCPA's own layer:

```
https://vgispublic.ocpafl.org/server/rest/services/Webmap/PARCEL/MapServer/4
fields NAME1, NAME2, ADD1, ADD2, ADD3, ADD4, CITY, STATE, ZIP
```

Wired as the ALT source in `fl_lla_skiptrace/scripts/backfill_owners.py:50-56`.

---

## Knox TN (KGIS) — VERIFIED WORKING 2026-08-11

```
proxy  https://www.kgis.org/proxy/proxy.ashx?<urlencoded target>
target https://www.kgis.org/arcgis/rest/services/Maps/QueryTasks/MapServer/3/query
where  PARCELID LIKE '090  07403%'      # NOTE the DOUBLE SPACE
hdrs   Referer: https://www.kgis.org/kgismaps/Map.htm  + browser UA   (direct = 401)
fields PARCELID, OWNER, FULL_ADDRESS, FULL_MAIL_ADDRESS, FULL_MAIL_CITY_STATE_ZIP,
       CALCULATED_AREA, SYS_CALC_AREA, RECORDED_AREA, TAX_DISTRICT, LANDUSE,
       APPRAISED_TOTAL, SALE_DATE, PURCHASE_PRICE, SUBDIVISION_NAME
```

TN is a disclosure state — `PURCHASE_PRICE` / `SALE_DATE` are real, unlike TX.

- Human-readable: `parcelreports/ownercard.aspx?id=074%20%20029`;
  `PropertyMapAndDetailsReport`.
- Tax roll: `propertyinfo.knoxcountytn.gov/search/commonsearch.aspx?mode=realprop`
  (behind `Search/Disclaimer.aspx` on first hit).
- Throttle 0.25 s/page, 0.12 s/count-query.
- `Tennessee_Property_Boundaries_Public_Use` covers 86 of 95 counties — **Knox is absent.**

Knox packs **both owners into one `OWNER` string** (`FUGATE RONALD ALLEN & VIRGINIA M`) and
ships a **single combined** `FULL_MAIL_CITY_STATE_ZIP`. `owner_2` is therefore marked OPT for
this county, or Knox reports a permanent false gap.

---

## New York (NYS ITS)

```
https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/MapServer/1/query
fields SWIS, SWIS_SBL_ID, PRINT_KEY, SBL, PARCEL_ADDR, MUNI_NAME, CITYTOWN_NAME, LOC_ZIP,
       PRIMARY_OWNER, ADD_OWNER, ACRES, CALC_ACRES, PROP_CLASS, MAIL_ADDR, MAIL_CITY,
       MAIL_STATE, MAIL_ZIP, ROLL_YR
join   where=SWIS_SBL_ID IN (...)   # 26 digits = SWIS 6 + SBL 20
```

38 counties public; NYC = MapPluto.

---

## Union NC

```
polygons  gis.unioncountync.gov/server/rest/services/OperationalLayers/MapServer/215
centroids .../ParcelCentroids/MapServer/0        (carries ZoningAdmin)
live tax  .../Property_Tax_Live/Parcels/MapServer/0
owner = CURR_NAME1/2 + CURR_ADDR1/2 ; prior = JAN1_NAME* / JAN1_ADDR*
```

---

## Florida statewide assemblage cross-check — a free portfolio finder, run it in stage 1

```
https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer/0/query
```

**Verify a PID:**
`?where=PARCEL_ID='{PID}'&outFields=PARCEL_ID,CO_NO,JV,LND_VAL,OWN_NAME&returnGeometry=false&f=json`

**Ownership discovery:** `?where=OWN_NAME='{OWNER}' AND CO_NO={n}` returns the same owner's
adjoining parcels. **Run it whenever listed vs matched acreage differs >10%** — a prior run
understated acreage 4× on 3 of 5 parcels by resolving one parcel of an assemblage.

**Traps:** only `PARCEL_ID` is indexed (county-wide attribute queries 400/504);
**`CO_NO` uses DOR numbering, not alphabetical — Duval = 26**; `resultRecordCount` plus a
geometry envelope 400s. Try the ID both stripped and in county-native format.

---

# Per-county traps — symptom → cause → fix

## Knox TN

- **Symptom:** a `where` clause using `REPLACE()` returns HTTP 400.
  **Cause:** the KGIS layer does not accept `REPLACE()`.
  **Fix:** interleaved-wildcard `LIKE '0%4%5%…'` plus client-side normalized equality.
- **Symptom:** `PARCELID` lookups miss on an APN that visibly exists.
  **Cause:** Knox `PARCELID` embeds **double spaces** (`125  00801`, `090  07403`).
  **Fix:** preserve the double space in the `LIKE` pattern; normalize only for comparison.
- **Symptom:** 401 anonymously / 403 on POST / 404 where a POST was expected / 404, 400 or
  414 on a long geometry or a `%` in a GET.
  **Cause:** the KGIS REST endpoint requires the proxy plus a `Referer`; 403 specifically
  means a missing `Referer`.
  **Fix:** always go through `proxy.ashx` with the `Referer` and a browser UA; choose the
  method deliberately.
- **Symptom:** WebFetch returns 403 on kgis.org.
  **Cause:** host-level UA filtering.
  **Fix:** use `curl`.

## Pecos CAD (TX)

- **Symptom:** `GET /Home/Search` returns empty headers when 66 rows exist.
  **Cause:** the grid is a separate AJAX endpoint.
  **Fix:** `POST /Home/SearchTableV2`, form-encoded, with `filterData[searchObj]` set to a
  **JSON string** of
  `{"keyword":"","searchOption":"basic|advanced","sortBy":"Parcel Id","taxYear":"0","onlyShowNonZero":"false","page":"1","pageSize":"200","parcelId":"","propStrNum":"","propStrDir":"","propStr":"","propCity":"","propState":"","ownerName":"…"}`
  plus siblings `filterData[keyword|page|taxYear|rows|strSortBy|PropertyType]`, header
  `X-Requested-With: XMLHttpRequest`, browser UA. Returns `recordsTotal` + `items[]` =
  `PID | owner | LOC | MAIL | AC | MV | LEGAL`. Detail:
  `GET /Home/Details?parcelId=&ownershipId=&ownershipSequence=`. Sub-panels: `/Home/Lands`,
  `/Home/Buildings`, `/Home/Sales`, `/Home/PropertyRoll`, `/Home/PropertyValue`,
  `/Home/CollectionDetails`, `/Home/RecapAggregates`, `/Home/RecapDependents`,
  `/Home/GetMineralNotice`.
- **Symptom:** ownership history looks flat across years — reads as proof of a long hold.
  **Cause:** **`taxYear` is silently ignored on `SearchTableV2`.**
  **Fix:** use `/Home/PropertyRoll` (2022+ only) for any year-over-year claim.
- **Symptom:** `/Home/Sales` is empty for every parcel.
  **Cause:** TX is a non-disclosure state.
  **Fix:** the recorded **deed of trust** gives the loan amount → LTV bracket. That is the
  only price signal. Never infer ownership from lending alone. Pecos deeds:
  `kofilequicklinks.com/pecos` is free but **1884–1983 only**; 1983–present is paywalled
  (`texasfile.com`, county 186). County Clerk (432) 336-3503.

## Florida

- **Symptom:** Orange County FL returns what looks like an empty result set.
  **Cause:** the WAF 403s on any `<` or `>` in the URL *or* the body.
  **Fix:** use `BETWEEN` instead of comparison operators, and POST.
- **Symptom:** Seminole POST returns 400.
  **Cause:** the layer is GET-only.
  **Fix:** GET.
- **Symptom:** Escambia POST returns 400.
  **Cause:** unencoded spaces in the POST body.
  **Fix:** encode; `maxRecordCount` is 1,000.
- **Symptom:** Collier is unreachable.
  **Cause:** Fastly TLS fingerprinting; `ags2.colliercountyfl.gov` no longer resolves.
  **Fix:** none as of 2026-08-10 — emit a named gap.
- **Symptom:** Leon mailing city/state/zip are all blank.
  **Cause:** Leon packs `CITY ST ZIP` into `ADDR2`.
  **Fix:** `csz_mode: packed_in_addr2`, then `octlib.csz_split()`.
- **Symptom:** Indian River legacy hosts time out.
  **Cause:** dead hosts.
  **Fix:** use `gisportal/server3`.

## New York

- **Symptom:** a `PRINT_KEY` join returns parcels from the wrong municipality.
  **Cause:** `PRINT_KEY` is not unique across municipalities.
  **Fix:** join on `SWIS_SBL_ID`.
- **Symptom:** centroid coordinates come back as `0,0`.
  **Cause:** `returnCentroid=true` combined with `outSR`.
  **Fix:** request geometry and use shapely `representative_point()`, not `centroid`.

## Union NC

- **Symptom:** an anti-join on `ACCTNO` produces nonsense.
  **Cause:** `ACCTNO` is **not** the parcel key.
  **Fix:** anti-join before use; key on the parcel id.
- **Symptom:** `JAN1_*` looks like a convenient backfill for blank `CURR_*`.
  **Cause:** it is the **PRIOR** mailing address, not a backfill —
  `CURR_ADDR1 IS NULL AND JAN1_ADDR1 IS NOT NULL` returns **0** on the live layer, and 372
  targets have a `JAN1_*` that *differs* from `CURR_*`.
  **Fix:** treat it as a second anchor and a recent-move signal only.
- **Symptom:** address joins fail on visually identical strings.
  **Cause:** Union County writes `' '` for empty and **46.3% of address values carry trailing
  whitespace**.
  **Fix:** `.strip()` every raw assessor value.

## Everywhere

- **Symptom:** the mailing address looks like a situs address.
  **Cause:** a county layer exposing one field under the other's name.
  **Fix:** compare the situs field against the mailing field explicitly; never assume.
- **Symptom:** multipart parcel areas come out negative.
  **Cause:** Esri rings are orientation-based (CW outer, CCW hole) and the shipped
  `esri_feature_to_geojson()` treats `rings[1:]` as holes.
  **Fix:** test orientation, do not assume position.
- **Symptom:** a CAD street-number filter loses parcels that exist.
  **Cause:** number filters are unreliable across CADs.
  **Fix:** always re-query by owner name.
- **Symptom:** a parcel viewer screenshot names an owner the live county contradicts.
  **Cause:** stale viewer tiles (screenshots said `Kookje CC LLC`; live county says
  `PARK LOGISTICS INC`).
  **Fix:** the live layer wins.
- **Symptom:** the client's spreadsheet names an owner the county does not.
  **Cause:** the client's sheet can simply be wrong (`Schmidt Family Trust` vs
  `Gabor Donald J Jr`).
  **Fix:** doctrine 13 — resolve from the county layer.
- **Symptom:** owner and mailing columns are blank on rows the layer definitely has.
  **Cause:** the parcel-feature cache was keyed on county name only, with no field list.
  **Fix:** hash the requested field list into the cache key. Full detail in
  `references/traps.md`.
