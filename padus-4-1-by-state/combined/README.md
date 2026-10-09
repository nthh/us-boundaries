# PAD-US 4.1 Combined, by state

The Protected Areas Database of the United States 4.1 (USGS Gap Analysis Project, 2025,
https://doi.org/10.5066/P96WBCHS), Combined layer (fee, easement, designation, proclamation and
marine records), split into one spatially sorted GeoParquet file per `State_Nm` value.

- License: public domain (US Government work). Please cite USGS GAP as the producer.
- Provenance: built byte-for-byte from `combined.parquet` in Source Cooperative `cboettig/padus`
  (`padus-4-1/`, 1,858,273,578 bytes, ETag `"f1f0cad991ca44fdcf83af886b07c835-355"`, sha256 `2c85043d3f3d2b832b110d8e76ad002f15d50a10d586559ed683cbc2d9403582`),
  which converts the USGS release. Attributes and geometry WKB are unchanged; the source `bbox`
  column is recomputed from the geometry, and rows are reordered.
- CRS: OGC:CRS84 (longitude, latitude), as in the source.
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
| `AK` | Alaska | 2,082 | 102 | 309,299,337 |
| `AL` | Alabama | 2,555 | 10 | 15,432,948 |
| `AR` | Arkansas | 2,114 | 13 | 8,830,308 |
| `AS` | American Samoa | 26 | 2 | 249,027 |
| `AZ` | Arizona | 2,955 | 16 | 26,256,801 |
| `CA` | California | 33,939 | 76 | 113,984,373 |
| `CO` | Colorado | 18,276 | 39 | 54,928,643 |
| `CT` | Connecticut | 19,129 | 18 | 23,029,839 |
| `DC` | District of Columbia | 378 | 2 | 1,342,560 |
| `DE` | Delaware | 6,782 | 8 | 10,850,779 |
| `FL` | Florida | 10,577 | 53 | 80,334,878 |
| `GA` | Georgia | 7,484 | 13 | 18,822,672 |
| `GU` | Guam | 27 | 2 | 312,191 |
| `HI` | Hawaii | 1,144 | 6 | 6,896,201 |
| `IA` | Iowa | 6,880 | 8 | 8,897,219 |
| `ID` | Idaho | 10,945 | 33 | 47,125,947 |
| `IL` | Illinois | 14,794 | 19 | 23,462,768 |
| `IN` | Indiana | 4,750 | 10 | 5,316,440 |
| `KS` | Kansas | 2,162 | 3 | 3,807,315 |
| `KY` | Kentucky | 3,728 | 15 | 21,166,273 |
| `LA` | Louisiana | 2,958 | 13 | 8,848,914 |
| `MA` | Massachusetts | 48,892 | 43 | 52,970,394 |
| `MD` | Maryland | 61,414 | 50 | 58,105,583 |
| `ME` | Maine | 12,942 | 25 | 33,963,298 |
| `MI` | Michigan | 13,990 | 15 | 18,927,240 |
| `MN` | Minnesota | 17,185 | 21 | 27,656,861 |
| `MO` | Missouri | 5,807 | 8 | 8,868,193 |
| `MP` | Northern Mariana Islands | 22 | 1 | 274,387 |
| `MS` | Mississippi | 1,984 | 10 | 6,592,810 |
| `MT` | Montana | 5,529 | 45 | 34,284,383 |
| `NC` | North Carolina | 14,657 | 56 | 81,048,688 |
| `ND` | North Dakota | 8,396 | 12 | 13,541,748 |
| `NE` | Nebraska | 2,915 | 4 | 4,617,141 |
| `NH` | New Hampshire | 17,023 | 15 | 17,916,604 |
| `NJ` | New Jersey | 31,030 | 43 | 49,152,367 |
| `NM` | New Mexico | 2,389 | 24 | 16,980,295 |
| `NV` | Nevada | 2,774 | 23 | 32,786,766 |
| `NY` | New York | 20,314 | 29 | 39,816,957 |
| `OH` | Ohio | 10,191 | 11 | 13,491,657 |
| `OK` | Oklahoma | 2,109 | 13 | 8,421,125 |
| `OR` | Oregon | 8,674 | 41 | 57,034,480 |
| `PA` | Pennsylvania | 59,964 | 74 | 90,400,190 |
| `PR` | Puerto Rico | 665 | 3 | 3,056,305 |
| `RI` | Rhode Island | 5,682 | 5 | 5,779,746 |
| `SC` | South Carolina | 4,124 | 12 | 16,149,429 |
| `SD` | South Dakota | 9,485 | 14 | 14,276,421 |
| `TN` | Tennessee | 3,662 | 23 | 29,125,169 |
| `TX` | Texas | 24,900 | 33 | 43,511,744 |
| `UM` | US Minor Outlying Islands | 13 | 1 | 121,629 |
| `UNKF` | Unknown (marine and offshore) | 579 | 7 | 9,326,717 |
| `UT` | Utah | 7,609 | 18 | 24,671,370 |
| `VA` | Virginia | 21,268 | 44 | 71,236,536 |
| `VI` | US Virgin Islands | 87 | 1 | 742,097 |
| `VT` | Vermont | 20,006 | 22 | 25,077,638 |
| `WA` | Washington | 11,725 | 33 | 43,542,012 |
| `WI` | Wisconsin | 21,646 | 21 | 27,158,052 |
| `WV` | West Virginia | 2,654 | 11 | 6,693,862 |
| `WY` | Wyoming | 20,995 | 17 | 17,036,323 |

## Query

```sql
INSTALL spatial; LOAD spatial;
SELECT Unit_Nm, Mang_Name, GAP_Sts, Pub_Access
FROM read_parquet('<base>/combined/state=UT/data.parquet')
WHERE bbox.xmin < -111.42 AND bbox.xmax > -111.97 AND bbox.ymin < 41.03 AND bbox.ymax > 40.465;
```
