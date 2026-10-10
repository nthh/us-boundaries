# US boundaries

Public-domain US boundary datasets, rebuilt as spatially sorted, partitioned GeoParquet so a reader
can fetch a small area with a few HTTP range requests instead of downloading a national file.

| Dataset | Contents |
|---|---|
| [`padus-4-1-by-state/`](./padus-4-1-by-state/README.md) | PAD-US 4.1, partitioned by state |
| [`wbd-2026-09-02/`](./wbd-2026-09-02/README.md) | USGS WBD 2026-09-02, HUC2, HUC4, HUC6, HUC8, HUC10, HUC12, HUC14 and HUC16 by HUC2 region |

Each dataset is a [Portolan](https://www.portolan-sdi.org/) catalog (STAC 1.1.0) with one
collection per layer, one item per partition, `versions.json` per collection (semver, sha256 and
size of every file) and a `manifest.json` recording the pinned inputs, tool versions and every
output digest.

- Data: https://source.coop/nthh/us-boundaries (files at `https://data.source.coop/nthh/us-boundaries/` and
  `s3://us-west-2.opendata.source.coop/nthh/us-boundaries/`).
- Metadata history and build script: https://github.com/nthh/us-boundaries. The repository holds everything in the catalog
  except the GeoParquet files; each release is a commit and a tag.
- License: the data are US Government works in the public domain (cite USGS GAP for PAD-US and
  USGS for WBD). The build script is Apache-2.0.

## Reading

```sql
-- DuckDB: PAD-US units in a box around the Central Wasatch, from the Utah partition only
SELECT Unit_Nm, Mang_Name, SHAPE
FROM 'https://data.source.coop/nthh/us-boundaries/padus-4-1-by-state/combined/state=UT/data.parquet'
WHERE bbox.xmax >= -111.85 AND bbox.xmin <= -111.55 AND bbox.ymax >= 40.45 AND bbox.ymin <= 40.75;
```

Filter on the `bbox` struct; its row-group statistics let readers skip everything outside the area.

The whole country is one wildcard over the partitions (Source Cooperative allows anonymous listing):

```sql
CREATE SECRET (TYPE s3, PROVIDER config, REGION 'us-west-2', URL_STYLE 'path');
SELECT huc12, name, geometry
FROM 's3://us-west-2.opendata.source.coop/nthh/us-boundaries/wbd-2026-09-02/hu12/*/data.parquet';
```

For a single national PAD-US file, [cboettig/padus](https://source.coop/cboettig/padus)
`combined.parquet` converts the same USGS release. For web maps, each WBD collection carries
PMTiles built from this release; PAD-US links cboettig/padus `combined.pmtiles`.

## Rebuilding

Inputs are pinned (WBD by sha256, ETag and size; PAD-US by a digest over its unzipped
geodatabase), and the build refuses a republished source unless told otherwise. ScienceBase has
no scriptable download for PAD-US: fetch `PADUS4_1Geodatabase.zip` from
https://www.sciencebase.gov/catalog/item/652d4fc5d34e44db0e2ee45e in a browser first. The build
also needs GDAL 3.13.1 and tippecanoe v2.79.0 on PATH. With
[uv](https://docs.astral.sh/uv/):

```sh
uv run scripts/build_sorted_boundary_partitions.py padus --source PADUS4_1Geodatabase.zip --work /tmp/work --out out/padus-4-1-by-state --base-url https://data.source.coop/nthh/us-boundaries/padus-4-1-by-state
uv run scripts/build_sorted_boundary_partitions.py wbd --work /tmp/work --out out/wbd-2026-09-02 --base-url https://data.source.coop/nthh/us-boundaries/wbd-2026-09-02
uv run scripts/build_sorted_boundary_partitions.py root --out out
```
