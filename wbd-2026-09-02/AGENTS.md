# AGENTS.md

Collections `hu2`, `hu4`, `hu6`, `hu8`, `hu10`, `hu12`, `hu14`, `hu16`. A unit's HUC2 partition is the first two digits of its code, so
a code lookup needs exactly one file. Read `manifest.json` for sha256 and bytes of every file.

For `hu14` and `hu16`: Coverage is partial: USGS delineates this level only where a state chose to subdivide further, so most of the country has no units here. A missing unit means it was never delineated, not that the area has none; use HUC12 for complete coverage.
