# AGENTS.md: PAD-US 4.1 Combined, by state

- One file per state: `combined/state=<ST>/data.parquet` (two-letter USPS code, plus `UNKF`).
  Pick files by state, or walk the STAC items and keep those whose `bbox` meets your area.
- Filter on the `bbox` struct first (`bbox.xmin < E AND bbox.xmax > W AND bbox.ymin < N AND
  bbox.ymax > S`); readers skip row groups from its statistics. Then test the `SHAPE` geometry.
- `SHAPE` is WKB in OGC:CRS84. `State_Nm` repeats the partition value inside each file.
- Records overlap: one parcel can appear as fee, easement and designation rows. Do not sum
  `GIS_Acres` across categories without deduplicating (see `Category`, `FeatClass`).
- `GAP_Sts` 1 to 4 is conservation status; `Pub_Access` OA/RA/XA/UK is public access.
- A whole-country read is still about 1.8 GB in this slice set; use the
  partitions.
