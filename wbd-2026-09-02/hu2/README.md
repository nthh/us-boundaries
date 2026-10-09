# WBD HUC2 regions (2026-09-02) by HUC2 region

USGS Watershed Boundary Dataset 2-digit hydrologic units (layer `WBDHU2`), from the
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

Each partition is one GeoParquet 1.1 file, `hu2/huc2=<value>/data.parquet`, beside its
STAC item `hu2/huc2=<value>/huc2=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold.

Partitioning by HUC2 rather than state: every unit has exactly one HUC2 (the first two digits of
`huc2`), regions nest, and a unit can touch several states (`states` is a list), so a state split
would duplicate or arbitrarily assign units.

| `huc2` | Name | Rows | Row groups | Bytes |
|---|---|---:|---:|---:|
| `01` | Region 01 New England | 1 | 1 | 1,222,181 |
| `02` | Region 02 Mid Atlantic | 1 | 1 | 1,590,919 |
| `03` | Region 03 South Atlantic-Gulf | 1 | 1 | 1,840,266 |
| `04` | Region 04 Great Lakes | 1 | 1 | 8,247,362 |
| `05` | Region 05 Ohio | 1 | 1 | 1,764,154 |
| `06` | Region 06 Tennessee | 1 | 1 | 1,191,631 |
| `07` | Region 07 Upper Mississippi | 1 | 1 | 3,045,882 |
| `08` | Region 08 Lower Mississippi | 1 | 1 | 1,498,523 |
| `09` | Region 09 Souris-Red-Rainy | 1 | 1 | 2,901,255 |
| `10` | Region 10 Missouri | 1 | 1 | 3,359,408 |
| `11` | Region 11 Arkansas-White-Red | 1 | 1 | 2,347,949 |
| `12` | Region 12 Texas-Gulf | 1 | 1 | 716,564 |
| `13` | Region 13 Rio Grande | 1 | 1 | 2,501,689 |
| `14` | Region 14 Upper Colorado | 1 | 1 | 1,575,035 |
| `15` | Region 15 Lower Colorado | 1 | 1 | 2,206,093 |
| `16` | Region 16 Great Basin | 1 | 1 | 2,567,598 |
| `17` | Region 17 Pacific Northwest | 1 | 1 | 2,648,675 |
| `18` | Region 18 California | 1 | 1 | 1,777,976 |
| `19` | Region 19 Alaska | 1 | 1 | 5,024,030 |
| `20` | Region 20 Hawaii | 1 | 1 | 370,523 |
| `21` | Region 21 Caribbean | 1 | 1 | 209,167 |
| `22` | Region 22 South Pacific | 1 | 1 | 281,971 |
