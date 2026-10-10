# PAD-US 4.1 Combined, by state

The Protected Areas Database of the United States 4.1 (USGS Gap Analysis Project, 2025,
https://doi.org/10.5066/P96WBCHS), Combined layer (fee, easement, designation, proclamation and
marine records), split into one spatially sorted GeoParquet file per `State_Nm` value.

- License: public domain (US Government work). Please cite USGS GAP as the producer.
- Provenance: layer `PADUS4_1Combined_Proclamation_Marine_Fee_Designation_Easement` of USGS's
  `PADUS4_1Geodatabase.zip` (1,523,434,496 bytes, ScienceBase item https://www.sciencebase.gov/catalog/item/652d4fc5d34e44db0e2ee45e). ScienceBase
  serves it only through its web app and publishes no checksum, so it was downloaded by hand and
  is pinned by its unzipped geodatabase: 110 files, 2,058,509,215 bytes,
  tree sha256 `fb402c9cee022e4dd2a4feca1c991f28f421d290428682d2bc8c9f83e437c242` (sha256 over sorted `path<TAB>sha256` lines).
- Transform: GDAL 3.13.1 (PROJ 9.8.1) reprojects from USGS Albers
  (ESRI:102039, NAD83) to OGC:CRS84 and linearises the curved boundaries some records carry:
  `ogr2ogr -f Parquet combined-crs84.parquet PADUS4_1Geodatabase.gdb PADUS4_1Combined_Proclamation_Marine_Fee_Designation_Easement -t_srs OGC:CRS84 -nlt CONVERT_TO_LINEAR -nlt PROMOTE_TO_MULTI -lco GEOMETRY_NAME=SHAPE -preserve_fid -lco FID=OBJECTID -lco WRITE_COVERING_BBOX=NO -lco COMPRESSION=ZSTD`. Attributes are unchanged; rows are reordered and a `bbox`
  column is added. `SHAPE_Length` and `SHAPE_Area` are the geodatabase's values, in Albers metres.
- CRS: OGC:CRS84 (longitude, latitude). NAD83 to WGS84 uses PROJ's default operation, good to
  about a metre.
- Build: [`scripts/build_sorted_boundary_partitions.py`](https://github.com/nthh/us-boundaries/blob/main/scripts/build_sorted_boundary_partitions.py) `padus` (DuckDB 1.5.6, spatial
  04270fe, pyarrow 21.0.0); the catalog's `manifest.json` records
  the inputs, tools and every output digest.

## Layout

Each partition is one GeoParquet 1.1 file, `combined/state=<value>/data.parquet`, beside its
STAC item `combined/state=<value>/state=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold.

`UNKF` holds records PAD-US assigns to no state (mostly marine and offshore areas).

| `state` | Name | Rows | Row groups | Bytes |
|---|---|---:|---:|---:|
| `AK` | Alaska | 2,082 | 102 | 309,225,699 |
| `AL` | Alabama | 2,555 | 10 | 15,436,330 |
| `AR` | Arkansas | 2,114 | 13 | 8,825,800 |
| `AS` | American Samoa | 26 | 2 | 249,101 |
| `AZ` | Arizona | 2,955 | 16 | 26,134,812 |
| `CA` | California | 33,939 | 76 | 114,014,525 |
| `CO` | Colorado | 18,276 | 39 | 54,933,387 |
| `CT` | Connecticut | 19,129 | 18 | 23,022,757 |
| `DC` | District of Columbia | 378 | 2 | 1,334,370 |
| `DE` | Delaware | 6,782 | 8 | 10,847,087 |
| `FL` | Florida | 10,577 | 53 | 80,407,554 |
| `GA` | Georgia | 7,484 | 13 | 18,834,242 |
| `GU` | Guam | 27 | 2 | 316,755 |
| `HI` | Hawaii | 1,144 | 6 | 6,871,365 |
| `IA` | Iowa | 6,880 | 8 | 8,892,204 |
| `ID` | Idaho | 10,945 | 33 | 47,381,521 |
| `IL` | Illinois | 14,794 | 19 | 23,469,716 |
| `IN` | Indiana | 4,750 | 10 | 5,319,579 |
| `KS` | Kansas | 2,162 | 3 | 3,806,551 |
| `KY` | Kentucky | 3,728 | 15 | 21,123,958 |
| `LA` | Louisiana | 2,958 | 13 | 8,826,424 |
| `MA` | Massachusetts | 48,892 | 43 | 52,960,216 |
| `MD` | Maryland | 61,414 | 49 | 58,116,414 |
| `ME` | Maine | 12,942 | 25 | 33,831,274 |
| `MI` | Michigan | 13,990 | 15 | 18,922,873 |
| `MN` | Minnesota | 17,185 | 21 | 27,665,262 |
| `MO` | Missouri | 5,807 | 8 | 8,872,984 |
| `MP` | Northern Mariana Islands | 22 | 1 | 267,824 |
| `MS` | Mississippi | 1,984 | 10 | 6,571,030 |
| `MT` | Montana | 5,529 | 45 | 34,280,096 |
| `NC` | North Carolina | 14,657 | 56 | 81,119,675 |
| `ND` | North Dakota | 8,396 | 12 | 13,558,649 |
| `NE` | Nebraska | 2,915 | 4 | 4,614,144 |
| `NH` | New Hampshire | 17,023 | 15 | 17,850,454 |
| `NJ` | New Jersey | 31,030 | 43 | 49,136,006 |
| `NM` | New Mexico | 2,389 | 24 | 17,004,712 |
| `NV` | Nevada | 2,774 | 23 | 32,789,524 |
| `NY` | New York | 20,314 | 29 | 39,795,042 |
| `OH` | Ohio | 10,191 | 11 | 13,480,519 |
| `OK` | Oklahoma | 2,109 | 13 | 8,448,436 |
| `OR` | Oregon | 8,674 | 42 | 57,197,965 |
| `PA` | Pennsylvania | 59,964 | 74 | 90,351,029 |
| `PR` | Puerto Rico | 665 | 3 | 3,079,957 |
| `RI` | Rhode Island | 5,682 | 5 | 5,787,805 |
| `SC` | South Carolina | 4,124 | 12 | 16,159,312 |
| `SD` | South Dakota | 9,485 | 14 | 14,280,303 |
| `TN` | Tennessee | 3,662 | 23 | 29,146,617 |
| `TX` | Texas | 24,900 | 33 | 43,505,244 |
| `UM` | US Minor Outlying Islands | 13 | 1 | 121,601 |
| `UNKF` | Unknown (marine and offshore) | 579 | 7 | 9,331,210 |
| `UT` | Utah | 7,609 | 18 | 24,679,882 |
| `VA` | Virginia | 21,268 | 44 | 70,996,318 |
| `VI` | US Virgin Islands | 87 | 1 | 745,194 |
| `VT` | Vermont | 20,006 | 22 | 25,032,167 |
| `WA` | Washington | 11,725 | 33 | 43,306,630 |
| `WI` | Wisconsin | 21,646 | 21 | 27,192,046 |
| `WV` | West Virginia | 2,654 | 11 | 6,693,571 |
| `WY` | Wyoming | 20,995 | 17 | 17,178,666 |

## Query

```sql
INSTALL spatial; LOAD spatial;
SELECT Unit_Nm, Mang_Name, GAP_Sts, Pub_Access
FROM read_parquet('<base>/combined/state=UT/data.parquet')
WHERE bbox.xmin < -111.42 AND bbox.xmax > -111.97 AND bbox.ymin < 41.03 AND bbox.ymax > 40.465;
```
