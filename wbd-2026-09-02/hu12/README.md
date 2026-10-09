# WBD HUC12 subwatersheds (2026-09-02) by HUC2 region

USGS Watershed Boundary Dataset 12-digit hydrologic units (layer `WBDHU12`), from the
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

Each partition is one GeoParquet 1.1 file, `hu12/huc2=<value>/data.parquet`, beside its
STAC item `hu12/huc2=<value>/huc2=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold.

Partitioning by HUC2 rather than state: every unit has exactly one HUC2 (the first two digits of
`huc12`), regions nest, and a unit can touch several states (`states` is a list), so a state split
would duplicate or arbitrarily assign units.

| `huc2` | Name | Rows | Row groups | Bytes |
|---|---|---:|---:|---:|
| `01` | Region 01 New England | 2,050 | 35 | 44,347,944 |
| `02` | Region 02 Mid Atlantic | 3,095 | 36 | 44,925,439 |
| `03` | Region 03 South Atlantic-Gulf | 7,701 | 73 | 86,417,989 |
| `04` | Region 04 Great Lakes | 4,417 | 89 | 157,826,752 |
| `05` | Region 05 Ohio | 5,278 | 46 | 53,797,177 |
| `06` | Region 06 Tennessee | 1,075 | 12 | 12,981,892 |
| `07` | Region 07 Upper Mississippi | 5,731 | 48 | 57,976,275 |
| `08` | Region 08 Lower Mississippi | 2,641 | 22 | 25,273,437 |
| `09` | Region 09 Souris-Red-Rainy | 2,331 | 33 | 43,154,975 |
| `10` | Region 10 Missouri | 13,725 | 155 | 189,357,373 |
| `11` | Region 11 Arkansas-White-Red | 6,493 | 59 | 69,792,358 |
| `12` | Region 12 Texas-Gulf | 4,171 | 28 | 32,879,250 |
| `13` | Region 13 Rio Grande | 4,176 | 32 | 38,117,997 |
| `14` | Region 14 Upper Colorado | 3,179 | 30 | 35,914,169 |
| `15` | Region 15 Lower Colorado | 4,379 | 52 | 63,958,093 |
| `16` | Region 16 Great Basin | 3,200 | 37 | 45,459,923 |
| `17` | Region 17 Pacific Northwest | 8,933 | 180 | 298,571,514 |
| `18` | Region 18 California | 4,453 | 46 | 56,619,035 |
| `19` | Region 19 Alaska | 15,545 | 194 | 263,945,812 |
| `20` | Region 20 Hawaii | 209 | 3 | 2,910,761 |
| `21` | Region 21 Caribbean | 243 | 4 | 4,603,657 |
| `22` | Region 22 South Pacific | 43 | 1 | 967,682 |
