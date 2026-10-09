#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb==1.5.6", "pyarrow==21.0.0", "pillow==11.3.0"]
# ///
"""Build spatially sorted, partitioned GeoParquet releases of PAD-US 4.1 and WBD, in Portolan layout.

Two public-domain US boundary sets, rebuilt so a reader can range-read a small area:

  padus  PAD-US 4.1 Combined, from the pinned Source Cooperative `cboettig/padus` combined.parquet,
         one GeoParquet per `State_Nm` value (hive key `state`).
  wbd    WBD HUC2 through HUC16, from USGS's pinned national File Geodatabase (2026-09-02),
         one GeoParquet per two-digit HUC2 region (hive key `huc2`) for each level.

Every output file is Hilbert-sorted on feature bbox centres within its partition (features that
span a large share of the partition go last, in their own row groups), split into row groups by an
uncompressed byte budget (2 MiB by default, and at most 100,000 rows, under Portolan's 150,000
cap), carries a GeoParquet 1.1 `bbox` covering struct with Parquet min/max statistics, and is
zstd-compressed. Each file is checked against Portolan's row-order rule before it is written.

Why 2 MiB: on the Utah partition a bbox read over the buffered Central Wasatch selects 7 of 18 row
groups (8.3 MB of 24.7 MB). Plain Hilbert at 8 MiB selects 3 of 5 (16.7 MB); at 1 MiB, 10 of 38 (7.0 MB), for
twice the requests and a footer twice as large. Row groups of 50 to 200 MB would make most state
files a single row group, which prunes nothing inside a state. The output directory is a Portolan catalog (STAC 1.1.0: catalog.json, one
collection per layer, one item per partition, README.md and AGENTS.md at every level,
versions.json per collection) plus a root manifest.json with sha256 and bytes for every file.

Nothing is uploaded. Inputs are pinned by sha256 (and, for downloads, by ETag and bytes); a
mismatch refuses the build unless --allow-unpinned-source is given, and the manifest then records
the actual digest. Tool versions are pinned in the script header (run with `uv run`), and the
loaded DuckDB spatial extension build is checked against SPATIAL_EXTENSION_VERSION.

Usage (full builds; add --only to build a subset), then the root catalog over both:

  uv run scripts/build_sorted_boundary_partitions.py padus --work /data/work --out out/padus-4-1-by-state
  uv run scripts/build_sorted_boundary_partitions.py wbd   --work /data/work --out out/wbd-2026-09-02
  uv run scripts/build_sorted_boundary_partitions.py root  --out out

Test slices:

  ... padus --only UT ...       (Utah)
  ... wbd --only 16 ...         (HUC2 region 16, Great Basin)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

DUCKDB_VERSION = "1.5.6"
PYARROW_VERSION = "21.0.0"
PILLOW_VERSION = "11.3.0"
# The duckdb-spatial build that DuckDB 1.5.6 installs from its extension repository (it bundles
# GDAL, PROJ and GEOS). ST_Read (GDAL OpenFileGDB) and ST_Hilbert come from it.
SPATIAL_EXTENSION_VERSION = "04270fe"

SOURCES = {
    "padus": {
        "title": "PAD-US 4.1 Combined (Source Cooperative cboettig/padus)",
        "url": "https://data.source.coop/cboettig/padus/padus-4-1/combined.parquet",
        "bytes": 1_858_273_578,
        "etag": '"f1f0cad991ca44fdcf83af886b07c835-355"',
        "last_modified": "2026-06-18T07:02:55Z",
        "sha256": "2c85043d3f3d2b832b110d8e76ad002f15d50a10d586559ed683cbc2d9403582",
        "filename": "combined.parquet",
    },
    "wbd": {
        "title": "USGS Watershed Boundary Dataset, national File Geodatabase",
        "url": "https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/WBD/National/GDB/WBD_National_GDB.zip",
        "bytes": 2_780_922_634,
        "etag": '"de01022630310729e215f321f1c5a7e8-332"',
        "last_modified": "2026-09-02T02:59:56Z",
        "sha256": "e721273d26b655a7c71f82c1c4cdf7edb28c1e9bc37989fc56ac9164ed27ec82",
        "filename": "WBD_National_GDB.zip",
    },
}

PORTOLAN_SCHEMA = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
PARTITION_SCHEMA = "https://schemas.portolan-sdi.org/incubating/partition/v1.0.0/schema.json"
FILE_SCHEMA = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
TABLE_SCHEMA = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
PROJ_SCHEMA = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
WEBMAP_SCHEMA = "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json"
PARQUET_TYPE = "application/vnd.apache.parquet"
# The public home of this script and of the catalog's metadata history.
REPO_URL = "https://github.com/nthh/us-boundaries"
SCRIPT_URL = f"{REPO_URL}/blob/main/scripts/build_sorted_boundary_partitions.py"
CATALOG_URL = "https://source.coop/nthh/us-boundaries"

USGS_POLICY = "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"

# EPSG:4269 (NAD83 geographic) as PROJJSON, as PROJ 9 (bundled in duckdb-spatial) renders it. The
# WBD File Geodatabase declares NAD83 + NAVD88 height (compound); its geometries are 2D, so the
# horizontal CRS is the one that applies. PAD-US combined.parquet is OGC:CRS84 (no `crs` key).
EPSG_4269_PROJJSON = {
    "$schema": "https://proj.org/schemas/v0.5/projjson.schema.json",
    "type": "GeographicCRS",
    "name": "NAD83",
    "datum": {
        "type": "GeodeticReferenceFrame",
        "name": "North American Datum 1983",
        "ellipsoid": {
            "name": "GRS 1980",
            "semi_major_axis": 6378137,
            "inverse_flattening": 298.257222101,
        },
    },
    "coordinate_system": {
        "subtype": "ellipsoidal",
        "axis": [
            {
                "name": "Geodetic latitude",
                "abbreviation": "Lat",
                "direction": "north",
                "unit": "degree",
            },
            {
                "name": "Geodetic longitude",
                "abbreviation": "Lon",
                "direction": "east",
                "unit": "degree",
            },
        ],
    },
    "id": {"authority": "EPSG", "code": 4269},
}

GEOMETRY_TYPE_NAMES = {
    "POINT": "Point",
    "LINESTRING": "LineString",
    "POLYGON": "Polygon",
    "MULTIPOINT": "MultiPoint",
    "MULTILINESTRING": "MultiLineString",
    "MULTIPOLYGON": "MultiPolygon",
    "GEOMETRYCOLLECTION": "GeometryCollection",
}

STATE_NAMES = {
    "AK": "Alaska",
    "AL": "Alabama",
    "AR": "Arkansas",
    "AS": "American Samoa",
    "AZ": "Arizona",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DC": "District of Columbia",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "GU": "Guam",
    "HI": "Hawaii",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "MA": "Massachusetts",
    "MD": "Maryland",
    "ME": "Maine",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "MP": "Northern Mariana Islands",
    "MS": "Mississippi",
    "MT": "Montana",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "NE": "Nebraska",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NV": "Nevada",
    "NY": "New York",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UM": "US Minor Outlying Islands",
    "UNKF": "Unknown (marine and offshore)",
    "UT": "Utah",
    "VA": "Virginia",
    "VI": "US Virgin Islands",
    "VT": "Vermont",
    "WA": "Washington",
    "WI": "Wisconsin",
    "WV": "West Virginia",
    "WY": "Wyoming",
}

HUC2_NAMES = {
    "01": "New England",
    "02": "Mid Atlantic",
    "03": "South Atlantic-Gulf",
    "04": "Great Lakes",
    "05": "Ohio",
    "06": "Tennessee",
    "07": "Upper Mississippi",
    "08": "Lower Mississippi",
    "09": "Souris-Red-Rainy",
    "10": "Missouri",
    "11": "Arkansas-White-Red",
    "12": "Texas-Gulf",
    "13": "Rio Grande",
    "14": "Upper Colorado",
    "15": "Lower Colorado",
    "16": "Great Basin",
    "17": "Pacific Northwest",
    "18": "California",
    "19": "Alaska",
    "20": "Hawaii",
    "21": "Caribbean",
    "22": "South Pacific",
}

# USGS names for each hydrologic unit level. HU14 and HU16 have no official name.
HU_LEVEL_NAMES = {
    2: "regions",
    4: "subregions",
    6: "basins",
    8: "subbasins",
    10: "watersheds",
    12: "subwatersheds",
    14: "",
    16: "",
}

# Upstream WBD vector tiles (cboettig/usgs-wbd mirror) exist for these levels only.
WBD_PMTILES_BYTES = {8: 789_148_999, 10: 1_961_074_331, 12: 3_970_987_181}

# Levels USGS delineates only where a state chose to subdivide further.
PARTIAL_LEVELS = {14, 16}

PARTIAL_COVERAGE_NOTE = (
    "Coverage is partial: USGS delineates this level only where a state chose to subdivide "
    "further, so most of the country has no units here. A missing unit means it was never "
    "delineated, not that the area has none; use HUC12 for complete coverage."
)

# data.source.coop (behind Cloudflare) refuses Python's default urllib User-Agent with 403.
USER_AGENT = "folia-build-sorted-boundaries/1 (+https://github.com/nthh/folia)"


# ── inputs ──────────────────────────────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def obtain_source(
    kind: str, given: str | None, work: Path, allow_unpinned: bool
) -> tuple[Path, dict]:
    """Return a local path to the pinned input and the source record for the manifest."""
    pin = SOURCES[kind]
    record = {k: pin[k] for k in ("title", "url", "bytes", "etag", "last_modified", "sha256")}
    if given and not given.startswith(("http://", "https://")):
        path = Path(given).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"source does not exist: {path}")
    else:
        url = given or pin["url"]
        path = work / "inputs" / kind / pin["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": USER_AGENT}
        head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=headers))
        etag, length = head.headers.get("ETag"), int(head.headers.get("Content-Length", "-1"))
        if (etag, length) != (pin["etag"], pin["bytes"]) and not allow_unpinned:
            raise SystemExit(
                f"{url}: ETag {etag} / {length} bytes differ from the pin {pin['etag']} / "
                f"{pin['bytes']}; the source was republished. Re-pin deliberately or pass "
                "--allow-unpinned-source."
            )
        if not (path.is_file() and path.stat().st_size == length):
            print(f"downloading {url} ({length:,} bytes) -> {path}", file=sys.stderr)
            partial = path.with_suffix(path.suffix + ".part")
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request) as response, partial.open("wb") as out:
                shutil.copyfileobj(response, out, 16 * 1024 * 1024)
            os.replace(partial, path)
        record.update(url=url, etag=etag, bytes=length)
    actual = sha256_file(path)
    if actual != pin["sha256"] and not allow_unpinned:
        raise SystemExit(f"{path}: sha256 {actual} differs from the pin {pin['sha256']}")
    record.update(sha256=actual, bytes=path.stat().st_size)
    return path, record


def connect(work: Path, memory_limit: str, threads: int) -> duckdb.DuckDBPyConnection:
    import PIL

    found = (duckdb.__version__, pa.__version__, PIL.__version__)
    if found != (DUCKDB_VERSION, PYARROW_VERSION, PILLOW_VERSION):
        raise SystemExit(
            f"tool versions {found} differ from the pins "
            f"{(DUCKDB_VERSION, PYARROW_VERSION, PILLOW_VERSION)} (duckdb, pyarrow, pillow); run with uv run"
        )
    db = work / "build.duckdb"
    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    con.sql(f"SET memory_limit = '{memory_limit}'")
    con.sql(f"SET threads = {threads}")
    con.sql(f"SET temp_directory = '{work / 'duckdb-tmp'}'")
    con.sql("SET enable_geoparquet_conversion = false")  # keep source WKB bytes as BLOB
    con.sql("INSTALL spatial; LOAD spatial")
    (version,) = con.sql(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'spatial'"
    ).fetchone()
    if version != SPATIAL_EXTENSION_VERSION:
        raise SystemExit(
            f"duckdb spatial {version} differs from the pin {SPATIAL_EXTENSION_VERSION}"
        )
    return con


# ── one partition ───────────────────────────────────────────────────────────────────────────────


def portolan_ordering_ok(boxes: list, bounds: list[tuple[int, int]]) -> bool:
    """Portolan's GeoParquet row-order rule (formats.md; rashid PTL-DAT-006), evaluated before writing.

    Row level: the rows that have a box, cut into 10 equal chunks (when there are at least 200).
    Row-group level: the actual row groups (when there are at least 5). Each passes when fewer
    than 30% of consecutive boxes overlap on their interiors, or when boxes average under 30%
    of the overall extent.
    """

    def union(bs: list) -> tuple:
        return (
            min(b[0] for b in bs),
            min(b[1] for b in bs),
            max(b[2] for b in bs),
            max(b[3] for b in bs),
        )

    def area(b: tuple) -> float:
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    def passes(bs: list) -> bool:
        pairs = len(bs) - 1
        overlaps = sum(
            min(bs[i][2], bs[i + 1][2]) > max(bs[i][0], bs[i + 1][0])
            and min(bs[i][3], bs[i + 1][3]) > max(bs[i][1], bs[i + 1][1])
            for i in range(pairs)
        )
        if overlaps / pairs < 0.3:
            return True
        extent = area(union(bs))
        return extent == 0 or sum(area(b) for b in bs) / len(bs) / extent < 0.3

    present = [b for b in boxes if b is not None]
    if len(present) >= 200:
        step = -(-len(present) // 10)
        if not passes([union(present[i : i + step]) for i in range(0, len(present), step)]):
            return False
    groups = [[b for b in boxes[a:z] if b is not None] for a, z in bounds]
    groups = [union(g) for g in groups if g]
    return len(groups) < 5 or passes(groups)


def write_partition(
    con: duckdb.DuckDBPyConnection,
    select_sql: str,
    geom_col: str,
    tiebreak: str,
    target: Path,
    crs: dict | None,
    row_group_bytes: int,
    max_rows: int,
    zstd_level: int,
    large_fraction: float,
) -> dict:
    """Sort one partition along a Hilbert curve and write it as GeoParquet 1.1 with a bbox covering.

    `select_sql` yields the partition's rows with `geom_col` as WKB (BLOB). Returns the facts the
    STAC item, versions.json and manifest need.
    """
    con.sql(
        f"""CREATE OR REPLACE TEMP TABLE part AS
            SELECT s.*, ST_XMin(g) AS _xmin, ST_YMin(g) AS _ymin, ST_XMax(g) AS _xmax,
                   ST_YMax(g) AS _ymax, ST_GeometryType(g)::VARCHAR AS _gtype, ST_HasZ(g) AS _z
            FROM (SELECT *, ST_GeomFromWKB({geom_col}) AS g FROM ({select_sql})) s"""
    )
    rows, xmin, ymin, xmax, ymax = con.sql(
        "SELECT count(*), min(_xmin), min(_ymin), max(_xmax), max(_ymax) FROM part"
    ).fetchone()
    if rows == 0:
        raise SystemExit(f"{target}: partition is empty")
    types = sorted(
        GEOMETRY_TYPE_NAMES[t] + (" Z" if z else "")
        for (t, z) in con.sql(
            "SELECT DISTINCT _gtype, _z FROM part WHERE _gtype IS NOT NULL"
        ).fetchall()
    )
    empty = con.sql("SELECT count(*) FROM part WHERE _xmin IS NULL").fetchone()[0]
    box = f"{{'min_x': {xmin!r}, 'min_y': {ymin!r}, 'max_x': {xmax!r}, 'max_y': {ymax!r}}}::BOX_2D"
    ordered = con.sql(
        f"""SELECT * EXCLUDE (g, _xmin, _ymin, _xmax, _ymax, _gtype, _z),
                   struct_pack(xmin := _xmin, ymin := _ymin, xmax := _xmax, ymax := _ymax) AS bbox,
                   octet_length({geom_col}) AS _wkb_bytes,
                   greatest(_xmax - _xmin, _ymax - _ymin) AS _size
            FROM part
            ORDER BY ST_Hilbert((_xmin + _xmax) / 2, (_ymin + _ymax) / 2, {box}) NULLS LAST,
                     {tiebreak}"""
    )
    table = ordered.to_arrow_table()
    con.sql("DROP TABLE part")
    wkb = table.column("_wkb_bytes").to_pylist()
    size = table.column("_size").to_pylist()
    boxes = [
        None if b is None or b["xmin"] is None else (b["xmin"], b["ymin"], b["xmax"], b["ymax"])
        for b in table.column("bbox").to_pylist()
    ]
    table = table.drop_columns(["_wkb_bytes", "_size"])
    # Row-group boundaries from an uncompressed byte budget: each row costs its WKB bytes plus the
    # partition's mean attribute bytes.
    attr_bytes = (table.nbytes - table.column(geom_col).nbytes) / max(len(table), 1)

    def split(order: list[int], large: list[bool], budget: int) -> list[tuple[int, int]]:
        bounds, start, acc = [], 0, 0.0
        for pos, i in enumerate(order):
            cost = (wkb[i] or 0) + attr_bytes
            if pos > start and (
                acc + cost > budget or pos - start >= max_rows or large[i] != large[order[pos - 1]]
            ):
                bounds.append((start, pos))
                start, acc = pos, 0.0
            acc += cost
        bounds.append((start, len(order)))
        return bounds

    # Features whose bbox side exceeds `fraction` of the partition's larger side (a statewide
    # BLM unit, a national forest proclamation boundary, a statewide easement program) sort after
    # everything else, in their own row groups. Ordered by bbox centre alone they land in every
    # part of the file and stretch the boxes of the row groups around them, so no group can be
    # skipped and Portolan's row-order check (PTL-DAT-006) fails. A small file can also fail it
    # with only a handful of row groups, each covering a large share of the partition. So the
    # build tries the configured row-group budget and fraction first, then halves the fraction
    # (more features move to the tail), then halves the budget (more, smaller row groups), and
    # keeps the first layout that passes; most partitions pass at the first. The manifest records
    # the layout used.
    span = max(xmax - xmin, ymax - ymin)
    fractions = [large_fraction / 2**k for k in range(4)] if large_fraction > 0 else [0.0]
    attempts = []
    for budget in (row_group_bytes, row_group_bytes // 2, row_group_bytes // 4):
        for fraction in fractions:
            limit = fraction * span if fraction > 0 else math.inf
            large = [z is not None and z > limit for z in size]
            order = [i for i in range(len(size)) if not large[i]] + [
                i for i in range(len(size)) if large[i]
            ]
            bounds = split(order, large, budget)
            ok = portolan_ordering_ok([boxes[i] for i in order], bounds)
            attempts.append((fraction, budget, order, bounds, ok, sum(large)))
            if ok:
                break
        if ok:
            break
    fraction, budget, order, bounds, ordering_ok, large_rows = next(
        (a for a in attempts if a[4]), attempts[0]
    )
    table = table.take(order)

    column = {
        "encoding": "WKB",
        "geometry_types": types,
        "bbox": [xmin, ymin, xmax, ymax],
        "covering": {
            "bbox": {
                "xmin": ["bbox", "xmin"],
                "ymin": ["bbox", "ymin"],
                "xmax": ["bbox", "xmax"],
                "ymax": ["bbox", "ymax"],
            }
        },
    }
    if crs is not None:
        column["crs"] = crs
    geo = {"version": "1.1.0", "primary_column": geom_col, "columns": {geom_col: column}}
    schema = table.schema.with_metadata({b"geo": json.dumps(geo, separators=(",", ":")).encode()})
    table = table.replace_schema_metadata(schema.metadata)

    target.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(
        target,
        schema,
        compression="zstd",
        compression_level=zstd_level,
        write_statistics=True,
        write_page_index=True,
        data_page_size=1024 * 1024,
    ) as writer:
        for a, b in bounds:
            writer.write_table(table.slice(a, b - a), row_group_size=b - a)

    meta = pq.ParquetFile(target).metadata
    if meta.num_rows != rows or meta.num_row_groups != len(bounds):
        raise RuntimeError(f"{target}: wrote {meta.num_rows} rows / {meta.num_row_groups} groups")
    groups = []
    names = [meta.schema.column(i).path for i in range(meta.num_columns)]
    for r in range(meta.num_row_groups):
        rg = meta.row_group(r)
        stats = {n: rg.column(i).statistics for i, n in enumerate(names) if n.startswith("bbox.")}
        if any(s is None or not s.has_min_max for s in stats.values()):
            raise RuntimeError(f"{target}: row group {r} lacks bbox covering statistics")
        groups.append(
            {
                "rows": rg.num_rows,
                "uncompressed_bytes": rg.total_byte_size,
                "compressed_bytes": sum(
                    rg.column(i).total_compressed_size for i in range(rg.num_columns)
                ),
                "bbox": [
                    stats["bbox.xmin"].min,
                    stats["bbox.ymin"].min,
                    stats["bbox.xmax"].max,
                    stats["bbox.ymax"].max,
                ],
            }
        )
    return {
        "rows": rows,
        "large_feature_fraction": fraction,
        "row_group_bytes": budget,
        "large_feature_rows": large_rows,
        "portolan_ordering_check": ordering_ok,
        "empty_geometries": empty,
        "geometry_types": types,
        "bbox": [xmin, ymin, xmax, ymax],
        "row_groups": groups,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "schema": [(f.name, str(f.type)) for f in table.schema],
    }


# ── STAC / Portolan metadata ────────────────────────────────────────────────────────────────────


def multihash(sha256_hex: str) -> str:
    return "1220" + sha256_hex


def link(rel: str, href: str, typ: str, title: str | None = None) -> dict:
    out = {"rel": rel, "href": href, "type": typ}
    if title:
        out["title"] = title
    return out


def bbox_union(boxes: list[list[float]]) -> list[float]:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def wgs84_clamp(b: list[float]) -> list[float]:
    """STAC bboxes must sit inside [-180, 180] x [-90, 90]; a few source vertices sit at -180.00000000006."""
    return [max(-180.0, b[0]), max(-90.0, b[1]), min(180.0, b[2]), min(90.0, b[3])]


def bbox_polygon(b: list[float]) -> dict:
    w, s, e, n = b
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stac_column_type(arrow_type: str) -> str:
    return {
        "string": "varchar",
        "large_string": "varchar",
        "int64": "bigint",
        "int32": "integer",
        "double": "double",
        "binary": "geometry",
        "timestamp[ms]": "timestamp",
    }.get(arrow_type, arrow_type)


def write_thumbnail(
    con: duckdb.DuckDBPyConnection, files: list[Path], geom_col: str, target: Path, color: str
) -> dict:
    """Draw every feature's simplified outline, Web Mercator, 512 px on the long side."""
    from PIL import Image, ImageDraw  # pinned in the script header with the other tools

    paths = ", ".join(f"'{f}'" for f in files)
    w, s, e, n = con.sql(
        f"SELECT min(bbox.xmin), min(bbox.ymin), max(bbox.xmax), max(bbox.ymax) FROM read_parquet([{paths}])"
    ).fetchone()
    s, n = max(s, -85.0), min(n, 85.0)

    def merc(lat: float) -> float:
        lat = max(-85.0, min(85.0, lat))
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    x0, x1, y0, y1 = math.radians(w), math.radians(e), merc(s), merc(n)
    scale = 504 / max(x1 - x0, y1 - y0, 1e-9)
    width, height = max(8, int((x1 - x0) * scale) + 8), max(8, int((y1 - y0) * scale) + 8)
    tol = (e - w) / max(width, 1)  # about one pixel, in degrees
    image = Image.new("RGB", (width, height), "#f7f7f4")
    draw = ImageDraw.Draw(image)
    rgb = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    fill = tuple(int(c * 0.35 + 247 * 0.65) for c in rgb)
    rows = con.sql(
        f"""SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_GeomFromWKB({geom_col}), {tol!r}))
            FROM read_parquet([{paths}])
            WHERE greatest(bbox.xmax - bbox.xmin, bbox.ymax - bbox.ymin) > {tol!r}
            ORDER BY (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) DESC, bbox.xmin, bbox.ymin,
                     bbox.xmax, bbox.ymax, md5({geom_col})"""
    ).fetchall()

    def px(pt: list[float]) -> tuple[float, float]:
        return (4 + (math.radians(pt[0]) - x0) * scale, height - 4 - (merc(pt[1]) - y0) * scale)

    for (text,) in rows:
        if not text:
            continue
        geom = json.loads(text)
        polys = (
            geom["coordinates"]
            if geom["type"] == "MultiPolygon"
            else [geom["coordinates"]]
            if geom["type"] == "Polygon"
            else []
        )
        for poly in polys:
            ring = [px(pt) for pt in poly[0]]
            if len(ring) >= 3:
                draw.polygon(ring, fill=fill, outline=rgb)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)
    return {"bytes": target.stat().st_size, "sha256": sha256_file(target)}


def write_collection(
    con: duckdb.DuckDBPyConnection, out: Path, spec: dict, parts: list[dict], updated: str
) -> None:
    """Write one Portolan collection: collection.json, items, versions.json, README, AGENTS, style."""
    cid = spec["id"]
    cdir = out / cid
    thumb = write_thumbnail(
        con,
        [cdir / f"{spec['partition_key']}={p['value']}" / "data.parquet" for p in parts],
        spec["geom_col"],
        cdir / "thumbnail.png",
        spec["style_color"],
    )
    key = spec["partition_key"]
    crs_code = spec["crs_code"]
    schema = parts[0]["schema"]
    descriptions = spec.get("column_descriptions", {})
    columns = []
    for name, typ in schema:
        col = {"name": name, "type": stac_column_type(typ)}
        if name == "bbox":
            col["type"] = "struct(xmin double, ymin double, xmax double, ymax double)"
            col["description"] = "Per-feature bounding box, the GeoParquet 1.1 covering."
        elif name in descriptions:
            col["description"] = descriptions[name]
        columns.append(col)

    items, assets = [], {}
    for p in parts:
        item_id = f"{key}={p['value']}"
        rel = f"{item_id}/data.parquet"
        item = {
            "type": "Feature",
            "stac_version": "1.1.0",
            "stac_extensions": [FILE_SCHEMA, TABLE_SCHEMA, PROJ_SCHEMA],
            "id": item_id,
            "collection": cid,
            "geometry": bbox_polygon(wgs84_clamp(p["bbox"])),
            "bbox": wgs84_clamp(p["bbox"]),
            "properties": {
                "title": f"{spec['title']}: {p['label']}",
                "datetime": spec["datetime"],
                key: p["value"],
                "table:row_count": p["rows"],
                "table:primary_geometry": spec["geom_col"],
                "table:columns": columns,
            },
            "links": [
                link("root", "../../../catalog.json", "application/json"),
                link("parent", "../collection.json", "application/json"),
                link("collection", "../collection.json", "application/json"),
            ],
            "assets": {
                "data": {
                    "href": "./data.parquet",
                    "type": PARQUET_TYPE,
                    "title": f"{p['label']} (GeoParquet)",
                    "roles": ["data"],
                    "file:size": p["bytes"],
                    "file:checksum": multihash(p["sha256"]),
                    "proj:code": crs_code,
                }
            },
        }
        write_json(cdir / item_id / f"{item_id}.json", item)
        items.append(
            link(
                "item",
                f"./{item_id}/{item_id}.json",
                "application/geo+json",
                item["properties"]["title"],
            )
        )
        assets[rel] = {"sha256": p["sha256"], "size_bytes": p["bytes"], "href": rel}

    # Upstream vector tiles exist only for some layers (WBD HU8/10/12, PAD-US); without them the
    # collection has no style or visual asset, only the GeoParquet items and the thumbnail.
    tiles = spec["pmtiles"]
    style = tiles and {
        "version": 8,
        "name": spec["title"],
        "sources": {"data": {"type": "vector", "url": f"pmtiles://{spec['pmtiles']['href']}"}},
        "layers": [
            {
                "id": f"{cid}-fill",
                "type": "fill",
                "source": "data",
                "source-layer": spec["pmtiles"]["layer"],
                "paint": {"fill-color": spec["style_color"], "fill-opacity": 0.35},
            },
            {
                "id": f"{cid}-line",
                "type": "line",
                "source": "data",
                "source-layer": spec["pmtiles"]["layer"],
                "paint": {"line-color": spec["style_color"], "line-width": 0.6},
            },
        ],
    }
    if style:
        write_json(cdir / "styles" / "default.json", style)
        style_bytes = (cdir / "styles" / "default.json").read_bytes()

    collection = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [
            PORTOLAN_SCHEMA,
            PARTITION_SCHEMA,
            FILE_SCHEMA,
            TABLE_SCHEMA,
            PROJ_SCHEMA,
            *([WEBMAP_SCHEMA] if tiles else []),
        ],
        "id": cid,
        "title": spec["title"],
        "description": spec["description"],
        "license": "other",
        "keywords": spec["keywords"],
        "providers": spec["providers"],
        "extent": {
            "spatial": {"bbox": [wgs84_clamp(bbox_union([p["bbox"] for p in parts]))]},
            "temporal": {"interval": [[spec["datetime"], None]]},
        },
        "table:columns": columns,
        "table:primary_geometry": spec["geom_col"],
        "table:row_count": sum(p["rows"] for p in parts),
        "partition:scheme": "hive",
        "partition:strategy": "attribute",
        "partition:keys": [
            {"name": key, "type": "string", "description": spec["partition_description"]}
        ],
        "partition:file_count": len(parts),
        "partition:glob": f"{spec['base_url'].rstrip('/')}/{cid}/{key}=*/*.parquet"
        if spec["base_url"]
        else f"./{key}=*/*.parquet",
        "assets": {
            **({"visual": {
                "href": tiles["href"],
                "type": "application/vnd.pmtiles",
                "title": tiles["title"],
                "roles": ["visual"],
                "file:size": tiles["bytes"],
            }} if tiles else {}),
            "thumbnail": {
                "href": "./thumbnail.png",
                "type": "image/png",
                "title": "Preview: outlines in the default style colour, Web Mercator, no basemap",
                "roles": ["thumbnail"],
                "file:size": thumb["bytes"],
                "file:checksum": multihash(thumb["sha256"]),
            },
            **({"style-default": {
                "href": "./styles/default.json",
                "type": "application/vnd.mapbox.style+json",
                "title": "Outlines over a light fill",
                "roles": ["style", "default"],
                "file:size": len(style_bytes),
                "file:checksum": multihash(hashlib.sha256(style_bytes).hexdigest()),
            }} if style else {}),
        },
        "links": [
            link("root", "../../catalog.json", "application/json"),
            link("parent", "../catalog.json", "application/json"),
            *items,
            *([{
                **link(
                    "pmtiles",
                    tiles["href"],
                    "application/vnd.pmtiles",
                    "Web map tiles (upstream)",
                ),
                "pmtiles:layers": [tiles["layer"]],
            }] if tiles else []),
            link("via", spec["via"], "text/html", "Original source"),
            link("license", USGS_POLICY, "text/html", "USGS: public domain, credit requested"),
            link("agents", "./AGENTS.md", "text/markdown", "Guidance for AI agents"),
            link("describedby", "./README.md", "text/markdown", "Human-readable documentation"),
        ],
        "updated": updated,
    }
    write_json(cdir / "collection.json", collection)
    write_json(
        cdir / "versions.json",
        {
            "spec_version": "1.0.0",
            "current_version": "1.0.0",
            "versions": [
                {
                    "version": "1.0.0",
                    "created": updated,
                    "breaking": False,
                    "message": spec["version_message"],
                    "assets": assets,
                    "changes": sorted(assets),
                }
            ],
        },
    )
    (cdir / "README.md").write_text(spec["readme"](parts), encoding="utf-8")
    (cdir / "AGENTS.md").write_text(spec["agents"](parts), encoding="utf-8")


def write_catalog(out: Path, cat: dict, collections: list[dict], updated: str) -> None:
    write_json(
        out / "catalog.json",
        {
            "type": "Catalog",
            "stac_version": "1.1.0",
            "stac_extensions": [PORTOLAN_SCHEMA],
            "id": cat["id"],
            "title": cat["title"],
            "description": cat["description"],
            "links": [
                link("root", "../catalog.json", "application/json"),
                link("parent", "../catalog.json", "application/json"),
                *[
                    link("child", f"./{c['id']}/collection.json", "application/json", c["title"])
                    for c in collections
                ],
                link("agents", "./AGENTS.md", "text/markdown", "Guidance for AI agents"),
                link("describedby", "./README.md", "text/markdown", "Human-readable documentation"),
            ],
            "updated": updated,
        },
    )
    (out / "README.md").write_text(cat["readme"], encoding="utf-8")
    (out / "AGENTS.md").write_text(cat["agents"], encoding="utf-8")


def write_manifest(out: Path, doc: dict) -> dict:
    files = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            rel = path.relative_to(out).as_posix()
            files[rel] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    doc["files"] = files
    data = [v for k, v in files.items() if k.endswith(".parquet")]
    doc["totals"] = {"parquet_files": len(data), "parquet_bytes": sum(v["bytes"] for v in data)}
    write_json(out / "manifest.json", doc)
    return doc


def partition_table(parts: list[dict], key: str) -> str:
    lines = [f"| `{key}` | Name | Rows | Row groups | Bytes |", "|---|---|---:|---:|---:|"]
    for p in parts:
        lines.append(
            f"| `{p['value']}` | {p['label']} | {p['rows']:,} | {len(p['row_groups'])} | {p['bytes']:,} |"
        )
    return "\n".join(lines)


def layout_text(key: str, coll: str) -> str:
    return f"""Each partition is one GeoParquet 1.1 file, `{coll}/{key}=<value>/data.parquet`, beside its
STAC item `{coll}/{key}=<value>/{key}=<value>.json`. Rows are sorted along a Hilbert curve
(feature bbox centres, partition extent), except that features spanning a large share of the
partition (a statewide unit, say) sort last in their own row groups. Row groups hold about 2 MiB
of uncompressed data (1 MiB or 512 KiB in a few small files, so each passes Portolan's row-order
check) and at most 100,000 rows. A `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`, declared
as the GeoParquet covering) has Parquet min/max statistics per row group, so a reader can skip row
groups from the footer alone. Compression is zstd. `versions.json` and the catalog's
`manifest.json` list the sha256 and bytes of every file; `manifest.json` also records each
partition's row-group budget and large-feature threshold."""


# ── PAD-US ──────────────────────────────────────────────────────────────────────────────────────


def build_padus(args: argparse.Namespace) -> None:
    out, work = prepare_dirs(args)
    src, source = obtain_source("padus", args.source, work, args.allow_unpinned_source)
    con = connect(work, args.memory_limit, args.threads)
    rel = f"read_parquet('{src}')"
    states = [s for (s,) in con.sql(f"SELECT DISTINCT State_Nm FROM {rel} ORDER BY 1").fetchall()]
    if None in states:
        raise SystemExit(
            "combined.parquet has rows with a NULL State_Nm; decide where they go first"
        )
    wanted = states if not args.only else [s for s in states if s in set(args.only.split(","))]
    total = con.sql(f"SELECT count(*) FROM {rel}").fetchone()[0]
    cid = "combined"
    parts = []
    for state in wanted:
        started = time.monotonic()
        facts = write_partition(
            con,
            f"SELECT * EXCLUDE (bbox) FROM {rel} WHERE State_Nm = '{state}'",
            "SHAPE",
            "_cng_fid",
            out / cid / f"state={state}" / "data.parquet",
            None,
            args.row_group_bytes,
            args.max_rows,
            args.zstd_level,
            args.large_feature_fraction,
        )
        facts.update(value=state, label=STATE_NAMES.get(state, state))
        parts.append(facts)
        print(
            f"state={state}: {facts['rows']:,} rows, {len(facts['row_groups'])} row groups, "
            f"budget {facts['row_group_bytes'] // 1024} KiB, large>{facts['large_feature_fraction']:g} ({facts['large_feature_rows']} rows), "
            f"portolan order {'ok' if facts['portolan_ordering_check'] else 'FAILS'}, "
            f"{facts['bytes']:,} bytes, {time.monotonic() - started:.1f}s",
            file=sys.stderr,
        )
    if not args.only and sum(p["rows"] for p in parts) != total:
        raise SystemExit("partition row counts do not add up to the source")

    updated = args.updated or now()
    pmtiles = {
        "href": "https://data.source.coop/cboettig/padus/padus-4-1/combined.pmtiles",
        "layer": "combined",
        "bytes": 3_636_293_548,
        "title": "PAD-US 4.1 Combined vector tiles (cboettig/padus)",
    }
    providers = [
        {
            "name": "U.S. Geological Survey, Gap Analysis Project",
            "url": "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview",
            "roles": ["producer", "licensor"],
        },
        {
            "name": "Carl Boettiger (Source Cooperative cboettig/padus, GeoParquet conversion)",
            "url": "https://source.coop/cboettig/padus",
            "roles": ["processor"],
        },
        {"name": args.host_name, "url": args.host_url, "roles": ["host"]},
    ]

    def readme(ps: list[dict]) -> str:
        return f"""# PAD-US 4.1 Combined, by state

The Protected Areas Database of the United States 4.1 (USGS Gap Analysis Project, 2025,
https://doi.org/10.5066/P96WBCHS), Combined layer (fee, easement, designation, proclamation and
marine records), split into one spatially sorted GeoParquet file per `State_Nm` value.

- License: public domain (US Government work). Please cite USGS GAP as the producer.
- Provenance: built byte-for-byte from `combined.parquet` in Source Cooperative `cboettig/padus`
  (`padus-4-1/`, {source["bytes"]:,} bytes, ETag `{source["etag"]}`, sha256 `{source["sha256"]}`),
  which converts the USGS release. Attributes and geometry WKB are unchanged; the source `bbox`
  column is recomputed from the geometry, and rows are reordered.
- CRS: OGC:CRS84 (longitude, latitude), as in the source.
- Build: [`scripts/build_sorted_boundary_partitions.py`]({SCRIPT_URL}) `padus` (DuckDB {DUCKDB_VERSION}, spatial
  {SPATIAL_EXTENSION_VERSION}, pyarrow {PYARROW_VERSION}); the catalog's `manifest.json` records
  the inputs, tools and every output digest.

## Layout

{layout_text("state", cid)}

`UNKF` holds records PAD-US assigns to no state (mostly marine and offshore areas).

{partition_table(ps, "state")}

## Query

```sql
INSTALL spatial; LOAD spatial;
SELECT Unit_Nm, Mang_Name, GAP_Sts, Pub_Access
FROM read_parquet('<base>/combined/state=UT/data.parquet')
WHERE bbox.xmin < -111.42 AND bbox.xmax > -111.97 AND bbox.ymin < 41.03 AND bbox.ymax > 40.465;
```
"""

    def agents(ps: list[dict]) -> str:
        return f"""# AGENTS.md: PAD-US 4.1 Combined, by state

- One file per state: `combined/state=<ST>/data.parquet` (two-letter USPS code, plus `UNKF`).
  Pick files by state, or walk the STAC items and keep those whose `bbox` meets your area.
- Filter on the `bbox` struct first (`bbox.xmin < E AND bbox.xmax > W AND bbox.ymin < N AND
  bbox.ymax > S`); readers skip row groups from its statistics. Then test the `SHAPE` geometry.
- `SHAPE` is WKB in OGC:CRS84. `State_Nm` repeats the partition value inside each file.
- Records overlap: one parcel can appear as fee, easement and designation rows. Do not sum
  `GIS_Acres` across categories without deduplicating (see `Category`, `FeatClass`).
- `GAP_Sts` 1 to 4 is conservation status; `Pub_Access` OA/RA/XA/UK is public access.
- A whole-country read is still about {sum(p["bytes"] for p in ps) / 1e9:.1f} GB in this slice set; use the
  partitions.
"""

    spec = dict(
        id=cid,
        title="PAD-US 4.1 Combined by state",
        description="PAD-US 4.1 Combined protected-area records (USGS GAP), one Hilbert-sorted GeoParquet per state with a bbox covering, built from Source Cooperative cboettig/padus combined.parquet.",
        keywords=["protected-areas", "public-lands", "pad-us", "usgs", "boundaries"],
        providers=providers,
        geom_col="SHAPE",
        crs_code="OGC:CRS84",
        datetime="2025-03-31T00:00:00Z",
        partition_key="state",
        partition_description="State_Nm: two-letter state or territory code, UNKF for records with no state.",
        base_url=args.base_url,
        pmtiles=pmtiles,
        style_color="#2f7d32",
        via="https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download",
        version_message=f"Initial build from combined.parquet sha256 {source['sha256']}",
        column_descriptions={
            "_cng_fid": "Feature id from the cboettig/padus conversion; stable sort tiebreak.",
            "State_Nm": "State or territory code; equals the partition value.",
            "SHAPE": "Feature geometry, WKB, OGC:CRS84.",
        },
        readme=readme,
        agents=agents,
    )
    write_collection(con, out, spec, parts, updated)
    cat = dict(
        id="padus-4-1-by-state",
        title="PAD-US 4.1, partitioned by state",
        description="Spatially sorted, state-partitioned GeoParquet of PAD-US 4.1 Combined for range reads over small areas.",
        readme="""# PAD-US 4.1, partitioned by state

A Portolan catalog with one collection, `combined`: PAD-US 4.1 Combined split by state, Hilbert
sorted, with a GeoParquet bbox covering. It complements, and does not replace,
`cboettig/padus/padus-4-1/combined.parquet` (the whole country in one 1.86 GB file) and
`combined.pmtiles` (display). Public domain (USGS GAP). See `combined/README.md`.
""",
        agents="""# AGENTS.md

Start at `combined/AGENTS.md`. Read `manifest.json` for sha256 and bytes of every file.
""",
    )
    write_catalog(out, cat, [spec], updated)
    finish(out, work, args, "padus", [source], {cid: parts})


# ── WBD ─────────────────────────────────────────────────────────────────────────────────────────


def build_wbd(args: argparse.Namespace) -> None:
    out, work = prepare_dirs(args)
    src, source = obtain_source("wbd", args.source, work, args.allow_unpinned_source)
    gdb = work / "inputs" / "wbd" / "WBD_National_GDB.gdb"
    if src.suffix == ".zip":
        marker = gdb / ".unzipped-from"
        if not (marker.is_file() and marker.read_text() == source["sha256"]):
            print(f"unzipping {src} -> {gdb.parent}", file=sys.stderr)
            shutil.rmtree(gdb, ignore_errors=True)
            with zipfile.ZipFile(src) as z:
                z.extractall(gdb.parent)
            marker.write_text(source["sha256"])
    else:
        gdb = src
    con = connect(work, args.memory_limit, args.threads)
    levels = [int(x) for x in args.levels.split(",")]
    only = set(args.only.split(",")) if args.only else None
    updated = args.updated or now()
    specs, all_parts = [], {}
    for level in levels:
        code = f"huc{level}"
        layer = f"WBDHU{level}"
        cid = f"hu{level}"
        started = time.monotonic()
        con.sql(
            f"""CREATE OR REPLACE TABLE layer AS
                SELECT * EXCLUDE (shape, objectid), shape AS geometry
                FROM ST_Read('{gdb}', layer = '{layer}', keep_wkb = true)"""
        )
        n, bad, dup = con.sql(
            f"""SELECT count(*), count(*) FILTER (WHERE NOT regexp_full_match(coalesce({code}, ''), '[0-9]{{{level}}}')),
                       count(*) - count(DISTINCT {code}) FROM layer"""
        ).fetchone()
        if bad:
            raise SystemExit(f"{layer}: {bad} rows with a malformed {code}")
        print(
            f"{layer}: {n:,} rows read in {time.monotonic() - started:.1f}s, {dup} duplicate codes",
            file=sys.stderr,
        )
        regions = [
            r
            for (r,) in con.sql(
                f"SELECT DISTINCT substr({code}, 1, 2) FROM layer ORDER BY 1"
            ).fetchall()
        ]
        parts = []
        for huc2 in regions:
            if only and huc2 not in only:
                continue
            t0 = time.monotonic()
            facts = write_partition(
                con,
                f"SELECT * FROM layer WHERE substr({code}, 1, 2) = '{huc2}'",
                "geometry",
                f"{code}, tnmid",
                out / cid / f"huc2={huc2}" / "data.parquet",
                EPSG_4269_PROJJSON,
                args.row_group_bytes,
                args.max_rows,
                args.zstd_level,
                args.large_feature_fraction,
            )
            facts.update(
                value=huc2,
                label=f"Region {huc2} {HUC2_NAMES.get(huc2, '')}".strip(),
                duplicate_codes=dup,
            )
            parts.append(facts)
            print(
                f"{cid} huc2={huc2}: {facts['rows']:,} rows, {len(facts['row_groups'])} row groups, "
                f"budget {facts['row_group_bytes'] // 1024} KiB, large>{facts['large_feature_fraction']:g} ({facts['large_feature_rows']} rows), "
                f"portolan order {'ok' if facts['portolan_ordering_check'] else 'FAILS'}, "
                f"{facts['bytes']:,} bytes, {time.monotonic() - t0:.1f}s",
                file=sys.stderr,
            )
        if not only and sum(p["rows"] for p in parts) != n:
            raise SystemExit(f"{layer}: partition row counts do not add up")
        con.sql("DROP TABLE layer")
        all_parts[cid] = parts
        specs.append(wbd_spec(args, source, level, cid, code))
        write_collection(con, out, specs[-1], parts, updated)

    names = [f"HUC{level}" for level in levels]
    listed = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else names[0]
    cids = ", ".join(f"`hu{level}`" for level in levels)
    partial = [f"`hu{level}`" for level in levels if level in PARTIAL_LEVELS]
    partial_text = (
        f"\nFor {' and '.join(partial)}: {PARTIAL_COVERAGE_NOTE}\n" if partial else ""
    )
    cat = dict(
        id="wbd-2026-09-02-by-huc2",
        title=f"USGS WBD 2026-09-02, {listed} by HUC2 region",
        description="Spatially sorted, HUC2-partitioned GeoParquet of the USGS Watershed Boundary Dataset national release of 2026-09-02.",
        readme=f"""# USGS Watershed Boundary Dataset (2026-09-02), by HUC2 region

A Portolan catalog with one collection per level ({cids}), each split by two-digit
HUC2 region, Hilbert sorted, with a GeoParquet bbox covering. Built from USGS's national File
Geodatabase as republished on 2026-09-02. Public domain (USGS). See each collection's README.
{partial_text}""",
        agents=f"""# AGENTS.md

Collections {cids}. A unit's HUC2 partition is the first two digits of its code, so
a code lookup needs exactly one file. Read `manifest.json` for sha256 and bytes of every file.
{partial_text}""",
    )
    write_catalog(out, cat, specs, updated)
    finish(out, work, args, "wbd", [source], all_parts)


def wbd_spec(args: argparse.Namespace, source: dict, level: int, cid: str, code: str) -> dict:
    title = " ".join(
        x for x in (f"WBD HUC{level}", HU_LEVEL_NAMES[level], "(2026-09-02) by HUC2 region") if x
    )
    coverage = f"\n{PARTIAL_COVERAGE_NOTE}\n" if level in PARTIAL_LEVELS else ""

    def readme(ps: list[dict]) -> str:
        return f"""# {title}

USGS Watershed Boundary Dataset {level}-digit hydrologic units (layer `WBDHU{level}`), from the
national File Geodatabase USGS republished on 2026-09-02, split into one spatially sorted
GeoParquet file per two-digit HUC2 region.
{coverage}
- License: public domain (US Government work). Please cite USGS as the producer.
- Provenance: `WBD_National_GDB.zip` from The National Map staged products
  ({source["bytes"]:,} bytes, ETag `{source["etag"]}`, sha256 `{source["sha256"]}`), read with
  GDAL's OpenFileGDB driver (inside duckdb-spatial {SPATIAL_EXTENSION_VERSION}). All attributes are kept
  except the geodatabase `objectid`; the geometry column `shape` is renamed `geometry`.
- CRS: EPSG:4269 (NAD83 longitude, latitude), as in the source (the source declares NAD83 +
  NAVD88 height; geometries are 2D).
- Build: [`scripts/build_sorted_boundary_partitions.py`]({SCRIPT_URL}) `wbd` (DuckDB {DUCKDB_VERSION}, pyarrow
  {PYARROW_VERSION}); the catalog's `manifest.json` records inputs, tools and every digest.

## Layout

{layout_text("huc2", cid)}

Partitioning by HUC2 rather than state: every unit has exactly one HUC2 (the first two digits of
`{code}`), regions nest, and a unit can touch several states (`states` is a list), so a state split
would duplicate or arbitrarily assign units.

{partition_table(ps, "huc2")}
"""

    def agents(ps: list[dict]) -> str:
        return f"""# AGENTS.md: {title}

- `{cid}/huc2=<first two digits of {code}>/data.parquet`. A code lookup reads one file.
- Filter on the `bbox` struct first; readers skip row groups from its statistics.
- `tohuc` (HUC12 only) gives the downstream unit; `states` is a comma-separated list.
- Geometry is WKB in EPSG:4269 (NAD83). Treat NAD83 and WGS84 as equal only at metre tolerance.
{coverage}"""

    return dict(
        id=cid,
        title=title,
        description=f"USGS WBD {level}-digit hydrologic units{f" ({HU_LEVEL_NAMES[level]})" if HU_LEVEL_NAMES[level] else ""}, 2026-09-02 national release, one Hilbert-sorted GeoParquet per HUC2 region with a bbox covering."
        + (f" {PARTIAL_COVERAGE_NOTE}" if level in PARTIAL_LEVELS else ""),
        keywords=["watersheds", "hydrology", "wbd", f"huc{level}", "usgs", "boundaries"],
        providers=[
            {
                "name": "U.S. Geological Survey",
                "url": "https://www.usgs.gov/national-hydrography/watershed-boundary-dataset",
                "roles": ["producer", "licensor"],
            },
            {"name": args.host_name, "url": args.host_url, "roles": ["host"]},
        ],
        geom_col="geometry",
        crs_code="EPSG:4269",
        datetime="2026-09-02T00:00:00Z",
        partition_key="huc2",
        partition_description=f"First two digits of {code}: the HUC2 region.",
        base_url=args.base_url,
        pmtiles={
            "href": f"https://s3-west.nrp-nautilus.io/public-usgs-wbd/wbd/hu{level}.pmtiles",
            "layer": f"hu{level}",
            "bytes": WBD_PMTILES_BYTES[level],
            "title": f"WBD HU{level} vector tiles (cboettig/usgs-wbd mirror, 2025-01-07 build)",
        }
        if level in WBD_PMTILES_BYTES
        else None,
        style_color="#1f5fa8",
        via="https://www.usgs.gov/national-hydrography/access-national-hydrography-products",
        version_message=f"Initial build from WBD_National_GDB.zip sha256 {source['sha256']}",
        column_descriptions={
            code: f"{level}-digit hydrologic unit code; its first two digits are the partition value.",
            "geometry": "Unit polygon, WKB, EPSG:4269.",
        },
        readme=readme,
        agents=agents,
    )


# ── shared ──────────────────────────────────────────────────────────────────────────────────────


def build_root(args: argparse.Namespace) -> None:
    """Write the us-boundaries root catalog over the dataset catalogs already built under --out."""
    out = args.out
    children = []
    for cat in sorted(out.glob("*/catalog.json")):
        doc = json.loads(cat.read_text())
        children.append((cat.parent.name, doc))
    if not children:
        raise SystemExit(f"no dataset catalogs under {out}")
    write_json(
        out / "catalog.json",
        {
            "type": "Catalog",
            "stac_version": "1.1.0",
            "stac_extensions": [PORTOLAN_SCHEMA],
            "id": "us-boundaries",
            "title": "US boundaries: protected areas and watersheds, spatially sorted GeoParquet",
            "description": "Public-domain US boundary datasets (PAD-US, WBD) rebuilt as partitioned, Hilbert-sorted GeoParquet with bbox coverings, so a reader can range-read a small area.",
            "links": [
                link("root", "./catalog.json", "application/json"),
                *[
                    link("child", f"./{name}/catalog.json", "application/json", doc["title"])
                    for name, doc in children
                ],
                link("agents", "./AGENTS.md", "text/markdown", "Guidance for AI agents"),
                link("describedby", "./README.md", "text/markdown", "Human-readable documentation"),
                link("related", REPO_URL, "text/html", "Build script and metadata history (GitHub)"),
            ],
            "updated": args.updated or now(),
        },
    )
    rows = "\n".join(
        f"| [`{name}/`](./{name}/README.md) | {doc['title']} |" for name, doc in children
    )
    builds = "\n".join(
        f"uv run scripts/build_sorted_boundary_partitions.py {json.loads((out / name / 'manifest.json').read_text())['kind']} "
        f"--work /tmp/work --out out/{name} --base-url https://data.source.coop/nthh/us-boundaries/{name}"
        for name, _ in children
    )
    (out / "README.md").write_text(
        f"""# US boundaries

Public-domain US boundary datasets, rebuilt as spatially sorted, partitioned GeoParquet so a reader
can fetch a small area with a few HTTP range requests instead of downloading a national file.

| Dataset | Contents |
|---|---|
{rows}

Each dataset is a [Portolan](https://www.portolan-sdi.org/) catalog (STAC 1.1.0) with one
collection per layer, one item per partition, `versions.json` per collection (semver, sha256 and
size of every file) and a `manifest.json` recording the pinned inputs, tool versions and every
output digest.

- Data: {CATALOG_URL} (files at `https://data.source.coop/nthh/us-boundaries/` and
  `s3://us-west-2.opendata.source.coop/nthh/us-boundaries/`).
- Metadata history and build script: {REPO_URL}. The repository holds everything in the catalog
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

## Rebuilding

Inputs are pinned by sha256, ETag and size; the build refuses a republished source unless told
otherwise. With [uv](https://docs.astral.sh/uv/):

```sh
{builds}
uv run scripts/build_sorted_boundary_partitions.py root --out out
```
""",
        encoding="utf-8",
    )
    (out / "AGENTS.md").write_text(
        """# AGENTS.md

Each child directory is a self-describing Portolan catalog: read its `AGENTS.md` and `catalog.json`
first. Pick the partition from the key (state for PAD-US, the first two digits of the HUC code for
WBD) and read one file; filter on the `bbox` struct before touching geometry. `manifest.json` in
each dataset lists sha256 and bytes for every file.
""",
        encoding="utf-8",
    )
    print(json.dumps({"out": str(out), "children": [name for name, _ in children]}))


def now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def prepare_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    out = args.out.resolve()
    if out.exists():
        raise SystemExit(f"output exists (builds are immutable; remove it first): {out}")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    args._final_out = out
    return staging, work


def finish(
    out: Path, work: Path, args: argparse.Namespace, kind: str, sources: list[dict], parts: dict
) -> None:
    manifest = {
        "format": "folia-partitioned-geoparquet",
        "version": 2,
        "kind": kind,
        "built": args.updated or now(),
        "build": {"script": SCRIPT_URL, "script_sha256": sha256_file(Path(__file__).resolve())},
        "sources": sources,
        "tools": {
            "duckdb": DUCKDB_VERSION,
            "duckdb_spatial": SPATIAL_EXTENSION_VERSION,
            "pyarrow": PYARROW_VERSION,
            "pillow": PILLOW_VERSION,
            "python": sys.version.split()[0],
        },
        "parameters": {
            "row_group_bytes": args.row_group_bytes,
            "max_rows_per_group": args.max_rows,
            "zstd_level": args.zstd_level,
            "sort": "features larger than a fraction of the partition last, then hilbert(bbox centre, partition extent), then id",
            "large_feature_fraction_start": args.large_feature_fraction,
            "geoparquet": "1.1.0, WKB, bbox covering",
            "only": args.only,
        },
        "collections": {
            cid: [
                {
                    k: p[k]
                    for k in (
                        "value",
                        "rows",
                        "bytes",
                        "sha256",
                        "bbox",
                        "geometry_types",
                        "empty_geometries",
                        "large_feature_fraction",
                        "row_group_bytes",
                        "large_feature_rows",
                        "portolan_ordering_check",
                    )
                }
                | {
                    "row_groups": len(p["row_groups"]),
                    "max_row_group_uncompressed": max(
                        g["uncompressed_bytes"] for g in p["row_groups"]
                    ),
                }
                for p in ps
            ]
            for cid, ps in parts.items()
        },
    }
    write_manifest(out, manifest)
    os.rename(out, args._final_out)
    shutil.rmtree(work / "duckdb-tmp", ignore_errors=True)
    (work / "build.duckdb").unlink(missing_ok=True)
    print(json.dumps({"out": str(args._final_out), **manifest["totals"]}))


def probe(args: argparse.Namespace) -> None:
    """Footer-only bbox pruning report: which row groups a covering-aware reader must fetch."""
    w, s, e, n = (float(v) for v in args.bbox.split(","))
    report = []
    for path in args.files:
        meta = pq.ParquetFile(path).metadata
        total_bytes = sum(
            meta.row_group(r).column(i).total_compressed_size
            for r in range(meta.num_row_groups)
            for i in range(meta.num_columns)
        )
        hit, hit_bytes, hit_uncompressed, hit_rows = [], 0, 0, 0
        for r in range(meta.num_row_groups):
            rg = meta.row_group(r)
            st = {
                rg.column(i).path_in_schema: rg.column(i).statistics for i in range(rg.num_columns)
            }
            if (
                st["bbox.xmin"].min <= e
                and st["bbox.xmax"].max >= w
                and st["bbox.ymin"].min <= n
                and st["bbox.ymax"].max >= s
            ):
                hit.append(r)
                hit_bytes += sum(rg.column(i).total_compressed_size for i in range(rg.num_columns))
                hit_uncompressed += rg.total_byte_size
                hit_rows += rg.num_rows
        report.append(
            {
                "file": str(path),
                "row_groups": meta.num_row_groups,
                "rows": meta.num_rows,
                "file_bytes": Path(path).stat().st_size,
                "column_chunk_bytes": total_bytes,
                "selected_row_groups": hit,
                "selected_rows": hit_rows,
                "selected_compressed_bytes": hit_bytes,
                "selected_uncompressed_bytes": hit_uncompressed,
            }
        )
    print(json.dumps(report, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="kind", required=True)
    pr = sub.add_parser(
        "probe", help="report the row groups a bbox read selects, from footers only"
    )
    pr.add_argument("--bbox", required=True, help="W,S,E,N")
    pr.add_argument("files", nargs="+", type=Path)
    rt = sub.add_parser("root", help="write the root catalog over dataset catalogs already built")
    rt.add_argument("--out", type=Path, required=True, help="directory holding the dataset catalogs")
    rt.add_argument("--updated", help="RFC 3339 time for STAC `updated` (default: now)")
    for kind in ("padus", "wbd"):
        p = sub.add_parser(kind)
        p.add_argument(
            "--out", type=Path, required=True, help="catalog root to create (must not exist)"
        )
        p.add_argument(
            "--work",
            type=Path,
            required=True,
            help="scratch dir: downloads, unzipped GDB, DuckDB spill",
        )
        p.add_argument(
            "--source", help="local copy or URL of the pinned input (default: the pinned URL)"
        )
        p.add_argument("--allow-unpinned-source", action="store_true")
        p.add_argument(
            "--only", help="comma-separated partition values to build (states, or HUC2 codes)"
        )
        p.add_argument("--row-group-bytes", type=int, default=2 * 1024 * 1024)
        p.add_argument("--max-rows", type=int, default=100_000)
        p.add_argument("--zstd-level", type=int, default=9)
        p.add_argument(
            "--large-feature-fraction",
            type=float,
            default=0.5,
            help="features larger than this share of the partition sort last; 0 disables",
        )
        p.add_argument("--memory-limit", default="8GB")
        p.add_argument("--threads", type=int, default=4)
        p.add_argument("--updated", help="RFC 3339 time for STAC `updated` (default: now)")
        p.add_argument(
            "--base-url", default="", help="public base URL of the catalog root, for partition:glob"
        )
        p.add_argument("--host-name", default="Source Cooperative nthh/us-boundaries")
        p.add_argument("--host-url", default="https://source.coop/nthh/us-boundaries")
        if kind == "wbd":
            p.add_argument("--levels", default="2,4,6,8,10,12,14,16")
    args = parser.parse_args()
    if args.kind == "probe":
        return probe(args)
    if args.kind == "root":
        return build_root(args)
    if args.max_rows > 150_000:
        parser.error("Portolan caps row groups at 150,000 rows")
    {"padus": build_padus, "wbd": build_wbd}[args.kind](args)


if __name__ == "__main__":
    main()
