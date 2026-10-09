# AGENTS.md: WBD HUC10 watersheds (2026-09-02) by HUC2 region

- `hu10/huc2=<first two digits of huc10>/data.parquet`. A code lookup reads one file.
- Filter on the `bbox` struct first; readers skip row groups from its statistics.
- `tohuc` (HUC12 only) gives the downstream unit; `states` is a comma-separated list.
- Geometry is WKB in EPSG:4269 (NAD83). Treat NAD83 and WGS84 as equal only at metre tolerance.
