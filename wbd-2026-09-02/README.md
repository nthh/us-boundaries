# USGS Watershed Boundary Dataset (2026-09-02), by HUC2 region

A Portolan catalog with one collection per level (`hu2`, `hu4`, `hu6`, `hu8`, `hu10`, `hu12`, `hu14`, `hu16`), each split by two-digit
HUC2 region, Hilbert sorted, with a GeoParquet bbox covering. Built from USGS's national File
Geodatabase as republished on 2026-09-02. Public domain (USGS). See each collection's README.

For `hu14` and `hu16`: Coverage is partial: USGS delineates this level only where a state chose to subdivide further, so most of the country has no units here. A missing unit means it was never delineated, not that the area has none; use HUC12 for complete coverage.
