"""
09_create_extensive_sample.py
Extensive-margin estimation sample for PPML analysis.

Rationale: the standard estimation_sample.parquet (08_create_estimation_sample.py)
prunes all dyads where ENT is always 0 or suppressed (Step 6 dyad pruning).
This removes structurally inactive dyads — exactly the informative zeros needed
to study whether natural disaster risk deters MNE entry (extensive margin).

This script builds a Cartesian panel of ALL (home, host) pairs where both
countries are covered by WDI + WGI macro data and CEPII gravity, crossed with
12 panel years (2008-2019) for the B-S_X_O aggregate only.

B-S_X_O is the right level for the extensive margin because the entry decision
is naturally a country-pair question: does home MNE i have ANY affiliates in
host country j? At the section level (A-S), a firm might be absent in section C
but present in section G — the extensive margin question becomes ambiguous.

Controls are joined directly from Silver files (not from panel_final) so that
pairs absent from FATS get the correct control values without any imputation
artefacts from panel_final's FATS-based pivot.

FATS (ENT, EMP, TUR) are left-joined from panel_final.parquet:
- Pairs absent from FATS → structural zero → ENT=EMP=TUR=0.0
- Pairs in FATS with NaN ENT → confidentiality suppressed (ENT ∈ {1,2}) → keep NaN

Output flag: _fats_active
  True  = pair had ENT > 0 in at least one year in FATS (intensive margin present)
  False = pair never appeared in FATS with positive ENT (structural zero or always suppressed)

Input:  data/Silver/panel_final.parquet   (FATS ENT/EMP/TUR only)
        data/Silver/*.parquet              (controls, joined from Silver directly)
Output: data/Silver/estimation_sample_extensive.parquet

Cleaning steps (in order):
  1. Build valid (home, host) pairs: WDI ∩ WGI ∩ CEPII coverage
  2. Cartesian: valid_pairs × years 2008-2019 × {B-S_X_O}
  3. Join controls from Silver (EM-DAT, WDI, WGI, CEPII, historical exposure)
  4. Left join FATS ENT/EMP/TUR from panel_final
  5. Structural zeros: absent from FATS → ENT=EMP=TUR=0.0
  6. NaN → 0.0 for disaster/exposure columns (no EM-DAT entry = zero disasters)
  7. Drop internal investment (home_country == host_country)
  NO dyad pruning — structural zeros are intentionally retained.
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER   = os.path.join(ROOT, "data", "Silver")
IN_PANEL = os.path.join(SILVER, "panel_final.parquet")
OUT      = os.path.join(SILVER, "estimation_sample_extensive.parquet")

INDUSTRY = "B-S_X_O"
YEARS    = list(range(2008, 2020))

# Static home_region mapping (29 FATS reporters only; IS/LI/CH return no data)
HOME_REGION_MAP = {
    "AUT": "W. Europe", "BEL": "W. Europe", "DEU": "W. Europe",
    "FRA": "W. Europe", "LUX": "W. Europe", "NLD": "W. Europe",
    "DNK": "N. Europe", "EST": "N. Europe", "FIN": "N. Europe",
    "GBR": "N. Europe", "IRL": "N. Europe", "LTU": "N. Europe",
    "LVA": "N. Europe", "NOR": "N. Europe", "SWE": "N. Europe",
    "CYP": "S. Europe", "ESP": "S. Europe", "GRC": "S. Europe",
    "HRV": "S. Europe", "ITA": "S. Europe", "MLT": "S. Europe",
    "PRT": "S. Europe", "SVN": "S. Europe",
    "BGR": "E. Europe", "CZE": "E. Europe", "HUN": "E. Europe",
    "POL": "E. Europe", "ROU": "E. Europe", "SVK": "E. Europe",
}
HOME_COUNTRIES = sorted(HOME_REGION_MAP.keys())

print("=== EXTENSIVE MARGIN SAMPLE CONSTRUCTION ===\n")
print(f"Target: {INDUSTRY} × years {min(YEARS)}-{max(YEARS)}")
print(f"Home countries ({len(HOME_COUNTRIES)}): {HOME_COUNTRIES}\n")

# ── Load Silver files ──────────────────────────────────────────────────────────
print("Loading Silver files...")
df_panel = pd.read_parquet(IN_PANEL)
df_emdat = pd.read_parquet(os.path.join(SILVER, "emdat_clean.parquet"))
df_hist  = pd.read_parquet(os.path.join(SILVER, "emdat_hist_exposure.parquet"))
df_wdi   = pd.read_parquet(os.path.join(SILVER, "wdi_clean.parquet"))
df_wgi   = pd.read_parquet(os.path.join(SILVER, "wgi_clean.parquet"))
df_cepii = pd.read_parquet(os.path.join(SILVER, "cepii_clean.parquet"))
df_geo   = pd.read_parquet(os.path.join(SILVER, "geo_static.parquet"))

# Coerce year to int (WDI/WGI store as int16)
for _df in [df_emdat, df_hist, df_wdi, df_wgi]:
    _df["year"] = _df["year"].astype(int)
print(f"  panel_final: {df_panel.shape}")
print(f"  emdat_clean: {df_emdat.shape}")
print(f"  emdat_hist:  {df_hist.shape}")
print(f"  wdi_clean:   {df_wdi.shape}")
print(f"  wgi_clean:   {df_wgi.shape}")
print(f"  cepii_clean: {df_cepii.shape}")
print(f"  geo_static:  {df_geo.shape}")

# ── Step 1: Identify valid host countries ──────────────────────────────────────
print("\n--- Step 1: Valid host countries (WDI ∩ WGI coverage) ---")

wdi_panel = df_wdi[df_wdi["year"].isin(YEARS)]
wgi_panel = df_wgi[df_wgi["year"].isin(YEARS)]

# A host is valid if it has non-NaN gdp_pc AND pop for at least 1 panel year
valid_wdi_hosts = set(
    wdi_panel.dropna(subset=["gdp_pc_const2015_usd", "population"])["country_code"].unique()
)
# ... and non-NaN ge for at least 1 panel year
valid_wgi_hosts = set(
    wgi_panel.dropna(subset=["ge_estimate"])["country_code"].unique()
)
valid_macro_hosts = valid_wdi_hosts & valid_wgi_hosts
print(f"  Valid WDI hosts: {len(valid_wdi_hosts)}")
print(f"  Valid WGI hosts: {len(valid_wgi_hosts)}")
print(f"  Valid macro hosts (WDI ∩ WGI): {len(valid_macro_hosts)}")

# ── Step 2: Build valid (home, host) pairs from CEPII ─────────────────────────
print("\n--- Step 2: Valid (home, host) pairs from CEPII ---")

# Defensive: handle both pre-06 and post-06 naming
if "iso_o" in df_cepii.columns or "iso_d" in df_cepii.columns:
    print("  INFO: Renaming iso_o/iso_d (pre-06 naming).")
    df_cepii = df_cepii.rename(columns={"iso_o": "home_country", "iso_d": "host_country"})

# ROM → ROU: 06_standardise_countries.py does not convert CEPII's non-standard
# Romania code. Apply the correction here so ROU home-country rows are included.
df_cepii["home_country"] = df_cepii["home_country"].replace("ROM", "ROU")
df_cepii["host_country"] = df_cepii["host_country"].replace("ROM", "ROU")

GRAVITY_COLS = ["home_country", "host_country", "distw", "contig", "colony", "comlang_off"]
cepii_gravity = df_cepii[[c for c in GRAVITY_COLS if c in df_cepii.columns]].copy()

# Keep: our 29 home countries × valid macro hosts × non-NaN distw
cepii_valid = (
    cepii_gravity
    .dropna(subset=["distw"])
    .query("home_country in @HOME_COUNTRIES")
    .query("host_country in @valid_macro_hosts")
    .copy()
)
print(f"  Valid (home, host) pairs with distw: {len(cepii_valid):,}")
print(f"  Unique hosts in valid pairs: {cepii_valid['host_country'].nunique()}")

# ── Step 3: Cartesian base ─────────────────────────────────────────────────────
print("\n--- Step 3: Cartesian base (valid_pairs × years × B-S_X_O) ---")

years_df = pd.DataFrame({"year": YEARS})
base = (
    cepii_valid[["home_country", "host_country"]]
    .merge(years_df, how="cross")
    .assign(industry=INDUSTRY)
    .reset_index(drop=True)
)
print(f"  Cartesian base shape: {base.shape}")
print(f"  Expected rows: {len(cepii_valid)} pairs × {len(YEARS)} years = "
      f"{len(cepii_valid) * len(YEARS):,}")

# ── Step 4: Join controls from Silver files ────────────────────────────────────
print("\n--- Step 4: Joining controls ---")
_n_before = len(base)

# Layer 1 — EM-DAT disaster shocks (host)
emdat_join = df_emdat.rename(columns={"country_iso3": "host_country"})
base = base.merge(emdat_join, on=["year", "host_country"], how="left")
assert len(base) == _n_before, f"Layer 1 changed row count: {_n_before} -> {len(base)}"
matched_emdat = base["sev_sudden_physical"].notna().sum()
print(f"  EM-DAT shocks (host):    {matched_emdat:,} / {len(base):,} rows matched")

# Layer 2 — Historical exposure (host)
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
base = base.merge(hist_host, on=["year", "host_country"], how="left")
assert len(base) == _n_before, f"Layer 2 changed row count: {_n_before} -> {len(base)}"
print(f"  hist_sev_static_host:    "
      f"{base['hist_sev_static_host'].notna().sum():,} / {len(base):,} rows matched")

# Layer 3 — Historical exposure (home)
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
base = base.merge(hist_home, on=["year", "home_country"], how="left")
assert len(base) == _n_before, f"Layer 3 changed row count: {_n_before} -> {len(base)}"
print(f"  hist_sev_static_home:    "
      f"{base['hist_sev_static_home'].notna().sum():,} / {len(base):,} rows matched")

# Layer 4 — CEPII gravity (already filtered; merge on home+host to add distw etc.)
base = base.merge(cepii_gravity, on=["home_country", "host_country"], how="left")
assert len(base) == _n_before, f"Layer 4 changed row count: {_n_before} -> {len(base)}"
print(f"  distw:                   "
      f"{base['distw'].notna().sum():,} / {len(base):,} rows matched")

# Layer 5 — WDI GDP and population (host + home)
wdi_keep = ["country_code", "year", "gdp_pc_const2015_usd", "population"]

wdi_host = df_wdi[wdi_keep].rename(columns={
    "country_code":       "host_country",
    "gdp_pc_const2015_usd": "gdp_pc_host",
    "population":         "pop_host",
})
base = base.merge(wdi_host, on=["year", "host_country"], how="left")
assert len(base) == _n_before, f"Layer 5a changed row count: {_n_before} -> {len(base)}"

wdi_home = df_wdi[wdi_keep].rename(columns={
    "country_code":       "home_country",
    "gdp_pc_const2015_usd": "gdp_pc_home",
    "population":         "pop_home",
})
base = base.merge(wdi_home, on=["year", "home_country"], how="left")
assert len(base) == _n_before, f"Layer 5b changed row count: {_n_before} -> {len(base)}"
print(f"  gdp_pc_host:             "
      f"{base['gdp_pc_host'].notna().sum():,} / {len(base):,} rows matched")

# Layer 6 — WGI Government Effectiveness (host + home)
wgi_host = df_wgi.rename(columns={"country_code": "host_country", "ge_estimate": "ge_host"})
base = base.merge(wgi_host, on=["year", "host_country"], how="left")
assert len(base) == _n_before, f"Layer 6a changed row count: {_n_before} -> {len(base)}"

wgi_home = df_wgi.rename(columns={"country_code": "home_country", "ge_estimate": "ge_home"})
base = base.merge(wgi_home, on=["year", "home_country"], how="left")
assert len(base) == _n_before, f"Layer 6b changed row count: {_n_before} -> {len(base)}"
print(f"  ge_host:                 "
      f"{base['ge_host'].notna().sum():,} / {len(base):,} rows matched")

# Add home_region and nace_section (NaN for B-S_X_O — consistent with estimation_sample schema)
base["home_region"] = base["home_country"].map(HOME_REGION_MAP)
base["nace_section"] = np.nan
# gvc_position is always NaN for B-S_X_O (no TiVA match for aggregate codes)
base["gvc_position"] = np.nan

print(f"  home_region non-NaN:     {base['home_region'].notna().sum():,}")

# Layer 8 — Static geo controls (host)
geo_host = df_geo.rename(columns={
    "country_code":     "host_country",
    "surface_area_km2": "surface_area_host",
    "landlocked":       "landlocked_host",
})
base = base.merge(geo_host, on="host_country", how="left")
assert len(base) == _n_before, f"Geo join changed row count: {_n_before} -> {len(base)}"
print(f"  surface_area_host non-NaN: {base['surface_area_host'].notna().sum():,} / {len(base):,}")
print(f"  landlocked_host = 1:       {(base['landlocked_host'] == 1).sum():,} rows")

# ── Step 5: Left join FATS (ENT/EMP/TUR) from panel_final ─────────────────────
print("\n--- Step 5: Left join FATS ENT/EMP/TUR from panel_final ---")

panel_bsxo = (
    df_panel[df_panel["industry"] == INDUSTRY]
    [["year", "home_country", "host_country", "industry", "ent", "emp", "tur"]]
    .copy()
)
panel_bsxo["_in_fats"] = True

print(f"  panel_final B-S_X_O rows: {len(panel_bsxo):,}")

base = base.merge(
    panel_bsxo,
    on=["year", "home_country", "host_country", "industry"],
    how="left",
)
assert len(base) == _n_before, (
    f"FATS join changed row count: {_n_before} -> {len(base)}. "
    "Duplicate (year, home, host, B-S_X_O) in panel_final?"
)

# ── Step 6: Fill structural zeros ─────────────────────────────────────────────
print("\n--- Step 6: Fill structural zeros (absent from FATS → ENT=EMP=TUR=0) ---")

struct_zero_mask = base["_in_fats"].isna()
base.loc[struct_zero_mask, "ent"] = 0.0
base.loc[struct_zero_mask, "emp"] = 0.0
base.loc[struct_zero_mask, "tur"] = 0.0
base.drop(columns=["_in_fats"], inplace=True)

n_struct_zero = struct_zero_mask.sum()
n_fats_rows   = (~struct_zero_mask).sum()
print(f"  Structural zeros (absent from FATS): {n_struct_zero:,} rows")
print(f"  Rows from FATS:                      {n_fats_rows:,} rows")

# _fats_active: True if the (home, host) pair had ENT > 0 in at least 1 year
active_pairs_df = (
    panel_bsxo[panel_bsxo["ent"] > 0]
    [["home_country", "host_country"]]
    .drop_duplicates()
    .assign(_fats_active=True)
)
base = base.merge(active_pairs_df, on=["home_country", "host_country"], how="left")
base["_fats_active"] = ~base["_fats_active"].isna()

print(f"  _fats_active=True (ever had ENT>0):  {base['_fats_active'].sum():,} rows")
print(f"  _fats_active=False (structural zero): {(~base['_fats_active']).sum():,} rows")

# ── Step 7: NaN → 0 for disaster/exposure columns ─────────────────────────────
print("\n--- Step 7: NaN → 0 for disaster/exposure columns ---")
ZERO_PREFIXES = ("n_", "sev_", "hist_sev_", "hist_cnt_")
zero_cols = [c for c in base.columns if c.startswith(ZERO_PREFIXES)]
n_imputed = sum(base[c].isna().sum() for c in zero_cols)
for col in zero_cols:
    base[col] = base[col].fillna(0.0)
print(f"  {len(zero_cols)} disaster/exposure columns — {n_imputed:,} NaNs imputed to 0.0")

# ── Step 8: Drop internal investment ──────────────────────────────────────────
print("\n--- Step 8: Drop internal investment (home == host) ---")
before = len(base)
base = base[base["home_country"] != base["host_country"]].copy()
dropped = before - len(base)
print(f"  Dropped: {dropped:,} rows  →  {len(base):,} remaining")

# ── Lag economic macro controls (t-1) — mirrors 08_create_estimation_sample.py ─
# ge_host/home: replaced by t-1 values (predetermined w.r.t. contemporaneous shocks)
# ln_gdp_pc_host/home: log of t-1 GDP per capita (created here; raw gdp_pc_* dropped)
print("\n--- Lag macro controls (t-1): ge and ln_gdp_pc ---")
gdp_lag = (
    df_wdi[["country_code", "year", "gdp_pc_const2015_usd"]]
    .dropna(subset=["gdp_pc_const2015_usd"])
    .copy()
)
gdp_lag["year"] = gdp_lag["year"] + 1

ge_lag = (
    df_wgi[["country_code", "year", "ge_estimate"]]
    .dropna(subset=["ge_estimate"])
    .copy()
)
ge_lag["year"] = ge_lag["year"] + 1

for side, country_col, ge_col in [
    ("host", "host_country", "ge_host"),
    ("home", "home_country", "ge_home"),
]:
    base = base.merge(
        gdp_lag.rename(columns={"country_code": country_col, "gdp_pc_const2015_usd": "_gdp_lag"}),
        on=[country_col, "year"], how="left"
    )
    base[f"ln_gdp_pc_{side}"] = np.log(base["_gdp_lag"])
    base = base.drop(columns=["_gdp_lag", f"gdp_pc_{side}"])

    base = base.drop(columns=[ge_col]).merge(
        ge_lag.rename(columns={"country_code": country_col, "ge_estimate": ge_col}),
        on=[country_col, "year"], how="left"
    )
    print(f"  ln_gdp_pc_{side} NaN: {base[f'ln_gdp_pc_{side}'].isna().sum():,}")
    print(f"  {ge_col:<12} NaN: {base[ge_col].isna().sum():,}")

# ── Column ordering (consistent with estimation_sample.parquet schema) ─────────
col_order = [
    "year", "home_country", "home_region", "host_country", "industry", "nace_section",
    "ent", "emp", "tur",
    "_fats_active",
    # EM-DAT shocks
    "n_earthquake", "n_volcanic_activity", "n_mass_movement_dry", "n_mass_movement_wet",
    "n_impact", "n_flood", "n_storm", "n_wildfire", "n_drought",
    "n_extreme_temperature", "n_animal_incident", "n_epidemic", "n_infestation",
    "sev_sudden_physical", "sev_seasonal_physical", "sev_climatic_slow",
    "total_missing_affected",
    # Historical exposure
    "hist_sev_static_host", "hist_sev_dynamic_host",
    "hist_cnt_sudden_static_host", "hist_cnt_sudden_dynamic_host",
    "hist_cnt_seasonal_static_host", "hist_cnt_seasonal_dynamic_host",
    "hist_cnt_slow_static_host", "hist_cnt_slow_dynamic_host",
    "hist_cnt_total_static_host", "hist_cnt_total_dynamic_host",
    "hist_sev_static_home", "hist_sev_dynamic_home",
    "hist_cnt_sudden_static_home", "hist_cnt_sudden_dynamic_home",
    "hist_cnt_seasonal_static_home", "hist_cnt_seasonal_dynamic_home",
    "hist_cnt_slow_static_home", "hist_cnt_slow_dynamic_home",
    "hist_cnt_total_static_home", "hist_cnt_total_dynamic_home",
    # Macro controls (GDP: t-1 log; GE: t-1 level; pop: contemporaneous)
    "ln_gdp_pc_host", "pop_host", "ge_host",
    "ln_gdp_pc_home", "pop_home", "ge_home",
    # GVC (NaN for B-S_X_O)
    "gvc_position",
    # Gravity
    "distw", "contig", "colony", "comlang_off",
    # Static geo controls (host)
    "surface_area_host", "landlocked_host",
]
present_cols = [c for c in col_order if c in base.columns]
extra_cols   = [c for c in base.columns if c not in col_order]
if extra_cols:
    print(f"\n  WARNING: unexpected extra columns: {extra_cols}")
base = base[present_cols + extra_cols]

# ── Summary ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("EXTENSIVE MARGIN SAMPLE SUMMARY")
print("=" * 70)
print(f"Shape: {base.shape}")
print(f"\nENT distribution:")
print(f"  ENT = 0.0 (struct. zero or true zero):  {(base['ent'] == 0.0).sum():,}")
print(f"  ENT > 0   (active affiliates):           {(base['ent'] > 0).sum():,}")
print(f"  ENT = NaN (confidentiality suppressed):  {base['ent'].isna().sum():,}")

print(f"\nDyad activity (_fats_active):")
print(f"  _fats_active = True  (ever ENT>0 in FATS):    "
      f"{base['_fats_active'].sum():,} rows")
print(f"  _fats_active = False (structural/always zero): "
      f"{(~base['_fats_active']).sum():,} rows")

print(f"\nYear range: {base['year'].min()} - {base['year'].max()}")
print(f"Home countries ({base['home_country'].nunique()}): "
      f"{sorted(base['home_country'].unique())}")
print(f"Host countries: {base['host_country'].nunique()}")

print(f"\nMissing values (key variables):")
key_check = ["ent", "emp", "tur",
             "ln_gdp_pc_host", "pop_host", "ge_host", "ln_gdp_pc_home", "pop_home", "ge_home",
             "distw", "hist_sev_static_host", "hist_sev_static_home"]
for col in key_check:
    if col in base.columns:
        pct = base[col].isna().mean() * 100
        print(f"  {col:<40} {pct:5.1f}% missing")

# Verify zero_cols have no NaN
residual = sum(base[c].isna().sum() for c in zero_cols if c in base.columns)
if residual == 0:
    print(f"\n  OK: all {len(zero_cols)} disaster/exposure columns have 0 NaNs.")
else:
    print(f"\n  WARNING: {residual:,} NaNs remain in disaster/exposure columns!")

# Verify no duplicate keys
dupes = base.duplicated(subset=["year", "home_country", "host_country", "industry"]).sum()
print(f"\n  Duplicate rows on (year, home, host, industry): {dupes}")

# ── Save ───────────────────────────────────────────────────────────────────────
base.to_parquet(OUT, index=False)
print(f"\nSaved: {OUT}")
print(f"File size: {os.path.getsize(OUT)/1024/1024:.1f} MB")
