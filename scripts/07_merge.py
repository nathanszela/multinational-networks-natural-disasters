"""
07_merge.py
Build the final dyadic panel by joining all Silver datasets.

Base source: FATS only (OECD AMNE dropped).

Layer 0 - Base panel (FATS):
  Pre-filter FATS to whitelisted NACE codes only (section letters A-S +
  B-S_X_O + G-S_X_O) to prevent double-counting in the pivot.
  Pivot long -> wide on variable (ENT, EMP, TUR).
  Geographic aggregate host countries filtered out before any joins.
  Key: (year, home_country, host_country, industry, nace_section)
  industry     = NACE Rev.2 section letter or whitelisted aggregate (B-S_X_O, G-S_X_O)
  nace_section = plain section letter when industry is A-S; NaN for aggregates (TiVA join key)

Layer 1 - EM-DAT disaster shocks (host country):
  left-join [year, host_country]
  Adds: n_earthquake, n_volcanic_activity, n_mass_movement_dry, n_mass_movement_wet,
        n_impact, n_flood, n_storm, n_wildfire, n_drought, n_extreme_temperature,
        n_animal_incident, n_epidemic, n_infestation,
        sev_sudden_physical, sev_seasonal_physical, sev_climatic_slow,
        total_missing_affected

Layer 2 - EM-DAT historical exposure (host):
  left-join [year, host_country]
  Adds: hist_sev_static_host, hist_sev_dynamic_host,
        hist_cnt_sudden_static_host, hist_cnt_sudden_dynamic_host,
        hist_cnt_seasonal_static_host, hist_cnt_seasonal_dynamic_host,
        hist_cnt_slow_static_host, hist_cnt_slow_dynamic_host,
        hist_cnt_total_static_host, hist_cnt_total_dynamic_host

Layer 3 - EM-DAT historical exposure (home):
  left-join [year, home_country]
  Adds: hist_sev_static_home, hist_sev_dynamic_home,
        hist_cnt_sudden_static_home, hist_cnt_sudden_dynamic_home,
        hist_cnt_seasonal_static_home, hist_cnt_seasonal_dynamic_home,
        hist_cnt_slow_static_home, hist_cnt_slow_dynamic_home,
        hist_cnt_total_static_home, hist_cnt_total_dynamic_home

Layer 4 - CEPII bilateral gravity (static):
  left-join [home_country, host_country]
  Handles both pre-06 (iso_o/iso_d) and post-06 (home_country/host_country) naming.
  Adds: distw, contig, colony, comlang_off

Layer 5 - WDI GDP and population:
  left-join [year, host_country] -> gdp_pc_host, pop_host
  left-join [year, home_country] -> gdp_pc_home, pop_home

Layer 6 - WGI Government Effectiveness:
  left-join [year, host_country] -> ge_host
  left-join [year, home_country] -> ge_home

Layer 7 - TiVA GVC position index:
  left-join [year, host_country, nace_section] -> gvc_position
  Only section-letter NACE rows match; aggregate rows get NaN.

Output: data/Silver/panel_final.parquet
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = os.path.join(ROOT, "data", "Silver")
OUT    = os.path.join(SILVER, "panel_final.parquet")

print("=== FINAL PANEL MERGE ===\n")

# ── Load all Silver files ──────────────────────────────────────────────────────
print("Loading Silver datasets...")
df_fats  = pd.read_parquet(os.path.join(SILVER, "fats_clean.parquet"))
df_emdat = pd.read_parquet(os.path.join(SILVER, "emdat_clean.parquet"))
df_hist  = pd.read_parquet(os.path.join(SILVER, "emdat_hist_exposure.parquet"))
df_wdi   = pd.read_parquet(os.path.join(SILVER, "wdi_clean.parquet"))
df_wgi   = pd.read_parquet(os.path.join(SILVER, "wgi_clean.parquet"))
df_tiva  = pd.read_parquet(os.path.join(SILVER, "tiva_clean.parquet"))
df_cepii = pd.read_parquet(os.path.join(SILVER, "cepii_clean.parquet"))
df_geo   = pd.read_parquet(os.path.join(SILVER, "geo_static.parquet"))

print(f"  FATS:        {df_fats.shape}")
print(f"  EM-DAT:      {df_emdat.shape}")
print(f"  EM-DAT hist: {df_hist.shape}")
print(f"  WDI:         {df_wdi.shape}")
print(f"  WGI:         {df_wgi.shape}")
print(f"  TiVA:        {df_tiva.shape}")
print(f"  CEPII:       {df_cepii.shape}")
print(f"  Geo static:  {df_geo.shape}")

# ── LAYER 0: Build base panel (FATS only) ─────────────────────────────────────
print("\n--- Layer 0: Building base panel (FATS only) ---")

df_fats_base = df_fats[["year", "home_country", "host_country",
                          "nace_r2_section", "variable", "value",
                          "home_region"]].copy()
df_fats_base = df_fats_base.rename(columns={"nace_r2_section": "industry"})

# ── Pre-filter: keep only whitelisted NACE codes to prevent double-counting ───
# 01_clean_fats.py already applies this keep-whitelist so under normal operation
# this filter drops 0 rows. It is defensive against any future change to 01 that
# re-introduces sub-section codes (e.g. C10-C12 alongside C).
NACE_WHITELIST = set("ABCDEFGHIJKLMNOPQRS") | {"B-S_X_O", "G-S_X_O"}
before_nace = len(df_fats_base)
df_fats_base = df_fats_base[df_fats_base["industry"].isin(NACE_WHITELIST)].copy()
n_nace_dropped = before_nace - len(df_fats_base)
if n_nace_dropped > 0:
    print(f"  WARNING: Dropped {n_nace_dropped:,} rows with non-whitelisted NACE codes "
          f"(sub-section aggregates / division codes). Check 01_clean_fats.py output.")
else:
    print("  OK: all NACE codes are whitelisted (no sub-section codes in base).")

# Ensure consistent string dtypes
for col in ["home_country", "host_country", "industry", "variable", "home_region"]:
    df_fats_base[col] = df_fats_base[col].astype(str)
df_fats_base["year"] = df_fats_base["year"].astype(int)

print(f"  FATS long (whitelisted): {df_fats_base.shape}")
print(f"  Variables: {sorted(df_fats_base['variable'].unique())}")
print(f"  Industry codes: {sorted(df_fats_base['industry'].unique())}")

# Guard: verify no duplicate (year, home, host, industry, variable) rows before pivot.
# With the NACE whitelist filter above each combination should be unique.
# aggfunc with min_count=1 ensures a sum of purely NaN values stays NaN (not 0.0),
# preserving Eurostat confidentiality suppression. Without min_count=1 a single-row
# group with NaN would silently become 0.0, contaminating ENT/EMP/TUR with false zeros.
dup_check = df_fats_base.duplicated(
    subset=["year", "home_country", "host_country", "industry", "variable"]
).sum()
if dup_check > 0:
    print(f"  WARNING: {dup_check:,} duplicate (year/home/host/industry/variable) rows "
          f"found — check 01_clean_fats.py NACE normalisation for mixed granularity!")
else:
    print("  OK: no duplicate rows before pivot.")

# Pivot long -> wide: one column per variable (ENT, EMP, TUR)
# NOTE: nace_section is derived AFTER the pivot so aggregate codes (nace_section=None)
# are NOT dropped by pandas groupby/pivot NaN-key behaviour.
# aggfunc=lambda x: x.sum(min_count=1) preserves NaN when Eurostat suppressed the value
# (confidentiality: ENT==1 or ENT==2). aggfunc="sum" would convert those to 0.0.
df_wide = df_fats_base.pivot_table(
    index=["year", "home_country", "host_country", "industry"],
    columns="variable",
    values="value",
    aggfunc=lambda x: x.sum(min_count=1),
    dropna=True,   # drop rows where ALL ENT/EMP/TUR are NaN (fully-suppressed, no usable data)
).reset_index()
df_wide.columns.name = None

# Ensure all three variable columns exist
for col in ["ENT", "EMP", "TUR"]:
    if col not in df_wide.columns:
        df_wide[col] = np.nan
df_wide = df_wide.rename(columns={"ENT": "ent", "EMP": "emp", "TUR": "tur"})

# Shell company / tax haven fix: ent > 0 but emp exactly 0 → treat as missing.
# emp==0 with ent>0 indicates an SPV/holding with no operational workforce, not
# a genuine zero. NaN preserves the suppression signal; 0 would contaminate
# emp/ent intensity ratios downstream.
shell_mask = (df_wide["ent"] > 0) & (df_wide["emp"] == 0.0)
n_shell = shell_mask.sum()
if n_shell > 0:
    df_wide.loc[shell_mask, "emp"] = np.nan
    print(f"  Shell company fix: {n_shell:,} rows with ent>0 and emp=0 → emp set to NaN")
else:
    print("  Shell company fix: no rows with ent>0 and emp=0 found.")

# Re-attach home_region via a lookup (not in pivot index to avoid row multiplication).
# home_country → home_region is a static 1-to-1 mapping defined in 01_clean_fats.py.
home_region_map = (
    df_fats_base[["home_country", "home_region"]]
    .drop_duplicates(subset="home_country")
    .set_index("home_country")["home_region"]
)
df_wide["home_region"] = df_wide["home_country"].map(home_region_map)

# Derive nace_section for TiVA join: single-letter sections only (A-S)
# Aggregate codes (e.g. "B-S_X_O") get NaN — TiVA join yields NaN for those rows
VALID_SECTIONS = set("ABCDEFGHIJKLMNOPQRS")
df_wide["nace_section"] = df_wide["industry"].apply(
    lambda x: x if (isinstance(x, str) and len(x) == 1 and x in VALID_SECTIONS) else None
)

# ── Geographic aggregate filter (before any joins for cleanliness) ────────────
GEO_AGGREGATES = {
    # Eurostat EU/euro-area zones
    "EU25", "EU27_2007", "EU27_2020", "EU28", "EA13",
    # Extra-EU counterpart zones
    "EXT_EU25", "EXT_EU27_2007", "EXT_EU27_2020", "EXT_EU28",
    "EXT_EU_NAL", "EXT_EA13",
    # Other Eurostat aggregates
    "OCE_PLR", "OFFSHO", "WORLD",
    # Continental aggregates (3-letter but not ISO country codes)
    "AFR", "AME", "ASI", "EUR",
    # Dissolved territories
    "AN",   # Netherlands Antilles (dissolved 2010)
}
before_geo = len(df_wide)
df_wide = df_wide[~df_wide["host_country"].isin(GEO_AGGREGATES)].copy()
n_geo_dropped = before_geo - len(df_wide)
if n_geo_dropped > 0:
    print(f"  WARNING: Dropped {n_geo_dropped:,} geographic-aggregate rows from base panel. "
          f"fats_clean.parquet contains aggregate host codes — re-run 01_clean_fats.py "
          f"if this is unexpected.")
else:
    print(f"  OK: 0 geographic-aggregate rows in base panel.")

print(f"  Wide base panel: {df_wide.shape}")
print(f"  Home countries: {df_wide['home_country'].nunique()}")
print(f"  Host countries: {df_wide['host_country'].nunique()}")
print(f"  Years: {sorted(df_wide['year'].unique())}")
print(f"  Missing ent: {df_wide['ent'].isna().sum():,}  "
      f"emp: {df_wide['emp'].isna().sum():,}  "
      f"tur: {df_wide['tur'].isna().sum():,}")

# ── LAYER 1: EM-DAT disaster shocks (host) ────────────────────────────────────
print("\n--- Layer 1: EM-DAT disaster shocks (host) ---")
df_emdat["year"] = df_emdat["year"].astype(int)
df_emdat_join = df_emdat.rename(columns={"country_iso3": "host_country"})

before = len(df_wide)
df_wide = df_wide.merge(df_emdat_join, on=["year", "host_country"], how="left")
assert len(df_wide) == before, (
    f"Layer 1 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate (year, country_iso3) keys in emdat_clean.parquet?"
)

EMDAT_COUNT_COLS = [
    "n_earthquake", "n_volcanic_activity", "n_mass_movement_dry", "n_mass_movement_wet",
    "n_impact", "n_flood", "n_storm", "n_wildfire", "n_drought",
    "n_extreme_temperature", "n_animal_incident", "n_epidemic", "n_infestation",
]
EMDAT_SEV_COLS = ["sev_sudden_physical", "sev_seasonal_physical", "sev_climatic_slow"]
disaster_shock_cols = [
    c for c in EMDAT_COUNT_COLS + EMDAT_SEV_COLS + ["total_missing_affected"]
    if c in df_wide.columns
]
if disaster_shock_cols:
    matched = df_wide[disaster_shock_cols[0]].notna().sum()
    print(f"  Matched rows (non-NaN first disaster col): {matched:,} / {len(df_wide):,}")
    print(f"  Disaster columns added ({len(disaster_shock_cols)}): {disaster_shock_cols}")

# ── LAYER 2: EM-DAT historical exposure (host) ────────────────────────────────
print("\n--- Layer 2: EM-DAT historical exposure (host) ---")
df_hist["year"] = df_hist["year"].astype(int)
hist_host = df_hist.rename(columns={
    "country_iso3":              "host_country",
    "hist_sev_static":           "hist_sev_static_host",
    "hist_sev_dynamic":          "hist_sev_dynamic_host",
    "hist_cnt_sudden_static":    "hist_cnt_sudden_static_host",
    "hist_cnt_sudden_dynamic":   "hist_cnt_sudden_dynamic_host",
    "hist_cnt_seasonal_static":  "hist_cnt_seasonal_static_host",
    "hist_cnt_seasonal_dynamic": "hist_cnt_seasonal_dynamic_host",
    "hist_cnt_slow_static":      "hist_cnt_slow_static_host",
    "hist_cnt_slow_dynamic":     "hist_cnt_slow_dynamic_host",
    "hist_cnt_total_static":     "hist_cnt_total_static_host",
    "hist_cnt_total_dynamic":    "hist_cnt_total_dynamic_host",
})
before = len(df_wide)
df_wide = df_wide.merge(hist_host, on=["year", "host_country"], how="left")
assert len(df_wide) == before, (
    f"Layer 2 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate (year, country_iso3) keys in emdat_hist_exposure.parquet?"
)
print(f"  hist_sev_static_host matched:          "
      f"{df_wide['hist_sev_static_host'].notna().sum():,} / {len(df_wide):,}")
print(f"  hist_sev_dynamic_host matched:         "
      f"{df_wide['hist_sev_dynamic_host'].notna().sum():,} / {len(df_wide):,}")
print(f"  hist_cnt_sudden_static_host (sum):     "
      f"{df_wide['hist_cnt_sudden_static_host'].sum():,}")

# ── LAYER 3: EM-DAT historical exposure (home) ────────────────────────────────
print("\n--- Layer 3: EM-DAT historical exposure (home) ---")
# Rename from df_hist (original column names), not from the Layer-2 copy
hist_home = df_hist.rename(columns={
    "country_iso3":              "home_country",
    "hist_sev_static":           "hist_sev_static_home",
    "hist_sev_dynamic":          "hist_sev_dynamic_home",
    "hist_cnt_sudden_static":    "hist_cnt_sudden_static_home",
    "hist_cnt_sudden_dynamic":   "hist_cnt_sudden_dynamic_home",
    "hist_cnt_seasonal_static":  "hist_cnt_seasonal_static_home",
    "hist_cnt_seasonal_dynamic": "hist_cnt_seasonal_dynamic_home",
    "hist_cnt_slow_static":      "hist_cnt_slow_static_home",
    "hist_cnt_slow_dynamic":     "hist_cnt_slow_dynamic_home",
    "hist_cnt_total_static":     "hist_cnt_total_static_home",
    "hist_cnt_total_dynamic":    "hist_cnt_total_dynamic_home",
})
before = len(df_wide)
df_wide = df_wide.merge(hist_home, on=["year", "home_country"], how="left")
assert len(df_wide) == before, (
    f"Layer 3 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate (year, country_iso3) keys in emdat_hist_exposure.parquet?"
)
print(f"  hist_sev_static_home matched:          "
      f"{df_wide['hist_sev_static_home'].notna().sum():,} / {len(df_wide):,}")
print(f"  hist_sev_dynamic_home matched:         "
      f"{df_wide['hist_sev_dynamic_home'].notna().sum():,} / {len(df_wide):,}")
print(f"  hist_cnt_sudden_static_home (sum):     "
      f"{df_wide['hist_cnt_sudden_static_home'].sum():,}")

# ── LAYER 4: CEPII bilateral gravity ─────────────────────────────────────────
print("\n--- Layer 4: CEPII bilateral gravity ---")

# Defensive: handle both pre-06 (iso_o/iso_d) and post-06 (home_country/host_country)
if "iso_o" in df_cepii.columns or "iso_d" in df_cepii.columns:
    print("  INFO: Renaming iso_o/iso_d -> home_country/host_country "
          "(06_standardise_countries.py may not have been run yet).")
    df_cepii = df_cepii.rename(columns={"iso_o": "home_country", "iso_d": "host_country"})

# Explicitly select only the gravity columns needed
GRAVITY_COLS = ["home_country", "host_country", "distw", "contig", "colony", "comlang_off"]
df_cepii_join = df_cepii[[c for c in GRAVITY_COLS if c in df_cepii.columns]].copy()

before = len(df_wide)
df_wide = df_wide.merge(df_cepii_join, on=["home_country", "host_country"], how="left")
assert len(df_wide) == before, (
    f"Layer 4 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate (home_country, host_country) pairs in cepii_clean.parquet?"
)
print(f"  distw matched:  {df_wide['distw'].notna().sum():,} / {len(df_wide):,}")
print(f"  contig matched: {df_wide['contig'].notna().sum():,} / {len(df_wide):,}")

# ── LAYER 5: WDI GDP and population ───────────────────────────────────────────
print("\n--- Layer 5: WDI GDP and population ---")
df_wdi["year"] = df_wdi["year"].astype(int)
wdi_keep = ["country_code", "year", "gdp_pc_const2015_usd", "population"]

wdi_host = df_wdi[wdi_keep].rename(columns={
    "country_code":       "host_country",
    "gdp_pc_const2015_usd": "gdp_pc_host",
    "population":         "pop_host",
})
before = len(df_wide)
df_wide = df_wide.merge(wdi_host, on=["year", "host_country"], how="left")
assert len(df_wide) == before, f"Layer 5a row count changed: {before:,} -> {len(df_wide):,}."
print(f"  gdp_pc_host matched: {df_wide['gdp_pc_host'].notna().sum():,} / {len(df_wide):,}")

wdi_home = df_wdi[wdi_keep].rename(columns={
    "country_code":       "home_country",
    "gdp_pc_const2015_usd": "gdp_pc_home",
    "population":         "pop_home",
})
before = len(df_wide)
df_wide = df_wide.merge(wdi_home, on=["year", "home_country"], how="left")
assert len(df_wide) == before, f"Layer 5b row count changed: {before:,} -> {len(df_wide):,}."
print(f"  gdp_pc_home matched: {df_wide['gdp_pc_home'].notna().sum():,} / {len(df_wide):,}")

# ── LAYER 6: WGI Government Effectiveness ─────────────────────────────────────
print("\n--- Layer 6: WGI Government Effectiveness ---")
df_wgi["year"] = df_wgi["year"].astype(int)

wgi_host = df_wgi.rename(columns={"country_code": "host_country", "ge_estimate": "ge_host"})
before = len(df_wide)
df_wide = df_wide.merge(wgi_host, on=["year", "host_country"], how="left")
assert len(df_wide) == before, f"Layer 6a row count changed: {before:,} -> {len(df_wide):,}."
print(f"  ge_host matched: {df_wide['ge_host'].notna().sum():,} / {len(df_wide):,}")

wgi_home = df_wgi.rename(columns={"country_code": "home_country", "ge_estimate": "ge_home"})
before = len(df_wide)
df_wide = df_wide.merge(wgi_home, on=["year", "home_country"], how="left")
assert len(df_wide) == before, f"Layer 6b row count changed: {before:,} -> {len(df_wide):,}."
print(f"  ge_home matched: {df_wide['ge_home'].notna().sum():,} / {len(df_wide):,}")

# ── LAYER 7: TiVA GVC position index ──────────────────────────────────────────
print("\n--- Layer 7: TiVA GVC position index ---")
df_tiva["year"] = df_tiva["year"].astype(int)

# Select only gvc_position — raw components (gvc_fwd_int, gvc_bwd_fva) are dropped.
tiva_join = (
    df_tiva[["country", "section", "year", "gvc_position"]]
    .rename(columns={"country": "host_country", "section": "nace_section"})
    .copy()
)
before = len(df_wide)
df_wide = df_wide.merge(tiva_join, on=["year", "host_country", "nace_section"], how="left")
assert len(df_wide) == before, (
    f"Layer 7 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate (country, section, year) keys in tiva_clean.parquet?"
)
print(f"  gvc_position matched: {df_wide['gvc_position'].notna().sum():,} / {len(df_wide):,}")
print(f"  (NaN expected for aggregate NACE codes and non-TiVA host countries)")

# ── LAYER 8: Static geographic controls (host) ────────────────────────────────
print("\n--- Layer 8: Static geo controls (host) ---")
geo_host = df_geo.rename(columns={
    "country_code":    "host_country",
    "surface_area_km2": "surface_area_host",
    "landlocked":      "landlocked_host",
})
before = len(df_wide)
df_wide = df_wide.merge(geo_host, on="host_country", how="left")
assert len(df_wide) == before, (
    f"Layer 8 row count changed: {before:,} -> {len(df_wide):,}. "
    "Duplicate country_code in geo_static.parquet?"
)
print(f"  surface_area_host matched: {df_wide['surface_area_host'].notna().sum():,} / {len(df_wide):,}")
print(f"  landlocked_host matched:   {df_wide['landlocked_host'].notna().sum():,} / {len(df_wide):,}")
print(f"  landlocked_host = 1:       {(df_wide['landlocked_host'] == 1).sum():,} rows")

# ── Summary ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("FINAL PANEL SUMMARY")
print("=" * 70)
print(f"Shape: {df_wide.shape}")
print(f"Columns ({len(df_wide.columns)}): {list(df_wide.columns)}")

print(f"\nKey columns (head 5):")
key_cols = [
    "year", "home_country", "home_region", "host_country", "industry", "nace_section",
    "ent", "emp", "tur",
    # EM-DAT shocks (sample)
    "n_earthquake", "n_flood", "n_storm",
    "sev_sudden_physical", "sev_seasonal_physical", "sev_climatic_slow",
    "total_missing_affected",
    # Historical exposure (log-severity + group counts)
    "hist_sev_static_host", "hist_sev_dynamic_host",
    "hist_cnt_sudden_static_host", "hist_cnt_seasonal_static_host",
    "hist_cnt_slow_static_host", "hist_cnt_total_static_host",
    "hist_sev_static_home", "hist_sev_dynamic_home",
    "hist_cnt_sudden_static_home", "hist_cnt_total_static_home",
    # Gravity
    "distw", "contig", "colony", "comlang_off",
    # WDI / WGI
    "gdp_pc_host", "pop_host", "gdp_pc_home", "pop_home",
    "ge_host", "ge_home",
    # TiVA
    "gvc_position",
]
key_cols_avail = [c for c in key_cols if c in df_wide.columns]
print(df_wide[key_cols_avail].head(5).to_string())

print(f"\nMissing values (key variables):")
for c in key_cols_avail:
    pct = df_wide[c].isna().mean() * 100
    print(f"  {c:<40} {pct:5.1f}% missing")

print(f"\nYear range: {df_wide['year'].min()} - {df_wide['year'].max()}")
print(f"Home countries ({df_wide['home_country'].nunique()}): "
      f"{sorted(df_wide['home_country'].unique())}")

# Duplicate check
dupes = df_wide.duplicated(
    subset=["year", "home_country", "host_country", "industry"]
).sum()
print(f"\nDuplicate rows (on year/home/host/industry key): {dupes}")

# ── Save ───────────────────────────────────────────────────────────────────────
df_wide.to_parquet(OUT, index=False)
print(f"\nSaved: {OUT}")
print(f"File size: {os.path.getsize(OUT)/1024/1024:.1f} MB")
