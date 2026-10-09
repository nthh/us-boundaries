# AGENTS.md

Each child directory is a self-describing Portolan catalog: read its `AGENTS.md` and `catalog.json`
first. Pick the partition from the key (state for PAD-US, the first two digits of the HUC code for
WBD) and read one file; filter on the `bbox` struct before touching geometry. `manifest.json` in
each dataset lists sha256 and bytes for every file.
