# AGENTS.md: WBD HUC14 (2026-09-02) by HUC2 region

- `hu14/huc2=<first two digits of huc14>/data.parquet`. A code lookup reads one file.
- Filter on the `bbox` struct first; readers skip row groups from its statistics.
- `tohuc` (HUC12 only) gives the downstream unit; `states` is a comma-separated list.
- Geometry is WKB in EPSG:4269 (NAD83). Treat NAD83 and WGS84 as equal only at metre tolerance.

Coverage is partial: USGS delineates this level only where a state chose to subdivide further, so most of the country has no units here. A missing unit means it was never delineated, not that the area has none; use HUC12 for complete coverage.
