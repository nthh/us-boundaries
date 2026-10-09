# WBD HUC14 (2026-09-02) by HUC2 region

USGS Watershed Boundary Dataset 14-digit hydrologic units (layer `WBDHU14`), from the
national File Geodatabase USGS republished on 2026-09-02, split into one spatially sorted
GeoParquet file per two-digit HUC2 region.

Coverage is partial: USGS delineates this level only where a state chose to subdivide further, so most of the country has no units here. A missing unit means it was never delineated, not that the area has none; use HUC12 for complete coverage.

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

Each partition is one GeoParquet 1.1 file, `hu14/huc2=<value>/data.parquet`, beside its
STAC item `hu14/huc2=<value>/huc2=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold.

Partitioning by HUC2 rather than state: every unit has exactly one HUC2 (the first two digits of
`huc14`), regions nest, and a unit can touch several states (`states` is a list), so a state split
would duplicate or arbitrarily assign units.

| `huc2` | Name | Rows | Row groups | Bytes |
|---|---|---:|---:|---:|
| `01` | Region 01 New England | 316 | 6 | 6,918,975 |
| `02` | Region 02 Mid Atlantic | 259 | 37 | 40,894,649 |
| `07` | Region 07 Upper Mississippi | 59 | 1 | 864,230 |
| `17` | Region 17 Pacific Northwest | 11 | 4 | 4,439,604 |
| `18` | Region 18 California | 114 | 4 | 4,816,005 |
| `19` | Region 19 Alaska | 7,390 | 52 | 62,417,009 |
