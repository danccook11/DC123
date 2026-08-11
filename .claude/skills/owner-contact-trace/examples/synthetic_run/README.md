# Synthetic run

Everything in this directory is invented. No parcel, owner, entity, address or number here
corresponds to a real person or property. It exists so the pipeline can be exercised
end to end with zero network access and zero spend.

`knox_layer_fixture.json` reproduces the SHAPE of a KGIS QueryTasks response exactly --
the double-space `PARCELID`, one `OWNER` string packing both owners, and a single combined
`FULL_MAIL_CITY_STATE_ZIP` -- because those three quirks are what the census code has to
survive. The values are fake.

Six rows, each chosen to exercise a different route:

| APN | Shape | Exercises |
|---|---|---|
| `090  07403` | individual, packed owner string, situs != mailing | ampersand split, combined-CSZ parse, absentee detection |
| `125  00801` | entity | registry-pierce route -- and TN has no route today, so `UNEVALUATED` |
| `077  01200` | private trust | free pierce at tier LEAD, then `TRUST-NEEDS-DEED` |
| `044  00100` | institutional (rail) | suppression with a recorded pattern, matched on the C/O mail line |
| `061  00920` | `CO TR` co-trustee | `CO` must not read as Company; C/O PO-box collapse |
| `099  00001` | blank owner | one free retry, then `NO-OWNER-NAME`, row drops out of the paid path |

Run it:

```sh
python3 ../../scripts/census.py --in parcels.csv --county tn_knox \
    --fixture knox_layer_fixture.json --out-dir /tmp/oct-demo --coverage
python3 ../../scripts/classify_owner.py --in /tmp/oct-demo/CENSUS.json --out-dir /tmp/oct-demo
```

Nothing here reaches the network and nothing here spends a credit.
