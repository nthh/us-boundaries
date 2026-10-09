# WBD HUC10 watersheds (2026-09-02) by HUC2 region

USGS Watershed Boundary Dataset 10-digit hydrologic units (layer `WBDHU10`), from the
national File Geodatabase USGS republished on 2026-09-02, split into one spatially sorted
GeoParquet file per two-digit HUC2 region.

- License: public domain (US Government work). Please cite USGS as the producer.
- Provenance: `WBD_National_GDB.zip` from The National Map staged products
  (2,780,922,634 bytes, ETag `"de01022630310729e215f321f1c5a7e8-332"`, sha256 `e721273d26b655a7c71f82c1c4cdf7edb28c1e9bc37989fc56ac9164ed27ec82`), read with
  GDAL's OpenFileGDB driver (inside duckdb-spatial 04270fe). All attributes are kept
  except the geodatabase `objectid`; the geometry column `shape` is renamed `geometry`.
- CRS: EPSG:4269 (NAD83 longitude, latitude), as in the source (the source declares NAD83 +
  NAVD88 height; geometries are 2D).
- Build: [`scripts/build_sorted_boundary_partitions.py`](https://github.com/nthh/us-boundaries/blob/main/scripts/build_sorted_boundary_partitions.py) `wbd` (DuckDB 1.5.6, pyarrow
  21.0.0); the catalog's `manifest.json` records inputs, tools and every digest.

## Layout

Each partition is one GeoParquet 1.1 file, `hu10/huc2=<value>/data.parquet`, beside its
STAC item `hu10/huc2=<value>/huc2=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold.

Partitioning by HUC2 rather than state: every unit has exactly one HUC2 (the first two digits of
`huc10`), regions nest, and a unit can touch several states (`states` is a list), so a state split
would duplicate or arbitrarily assign units.

| `huc2` | Name | Rows | Row groups | Bytes |
|---|---|---:|---:|---:|
| `01` | Region 01 New England | 414 | 17 | 22,305,005 |
| `02` | Region 02 Mid Atlantic | 638 | 18 | 24,216,830 |
| `03` | Region 03 South Atlantic-Gulf | 1,578 | 36 | 45,067,410 |
| `04` | Region 04 Great Lakes | 839 | 62 | 132,034,115 |
| `05` | Region 05 Ohio | 1,010 | 23 | 28,621,662 |
| `06` | Region 06 Tennessee | 217 | 6 | 7,130,027 |
| `07` | Region 07 Upper Mississippi | 1,155 | 24 | 31,741,808 |
| `08` | Region 08 Lower Mississippi | 524 | 11 | 13,813,968 |
| `09` | Region 09 Souris-Red-Rainy | 436 | 17 | 23,837,303 |
| `10` | Region 10 Missouri | 2,470 | 72 | 94,908,471 |
| `11` | Region 11 Arkansas-White-Red | 995 | 27 | 34,170,210 |
| `12` | Region 12 Texas-Gulf | 686 | 15 | 18,519,640 |
| `13` | Region 13 Rio Grande | 708 | 14 | 18,292,032 |
| `14` | Region 14 Upper Colorado | 524 | 13 | 17,313,413 |
| `15` | Region 15 Lower Colorado | 630 | 20 | 26,765,137 |
| `16` | Region 16 Great Basin | 653 | 20 | 27,209,078 |
| `17` | Region 17 Pacific Northwest | 1,679 | 91 | 233,903,697 |
| `18` | Region 18 California | 1,009 | 25 | 32,986,528 |
| `19` | Region 19 Alaska | 2,614 | 103 | 150,066,941 |
| `20` | Region 20 Hawaii | 63 | 2 | 2,107,434 |
| `21` | Region 21 Caribbean | 35 | 3 | 2,568,767 |
| `22` | Region 22 South Pacific | 34 | 1 | 919,032 |
