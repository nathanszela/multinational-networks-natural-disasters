"""
08_create_estimation_sample.py
Final estimation sample selection from panel_final.parquet.

Input:  data/Silver/panel_final.parquet  (produced by 07_merge.py)
Output: data/Silver/estimation_sample.parquet

Cleaning steps applied (in order):
  1. NaN → 0.0 for disaster/exposure columns
       n_*           : 13 disaster count columns
       sev_*         : 3 grouped severity columns
       hist_sev_*    : 4 historical log-severity columns (host + home, static + dynamic)
       hist_cnt_*    : 4 historical event-count auxiliary columns (host + home)
     Rationale: NaN in these columns means the country-year has no EM-DAT
     entry (not that data are missing for a covered entity). Imputing 0 is
     the correct economic assumption for "no recorded disaster / zero severity".

  1b. Lag economic macro controls (t-1) and create log GDP variables:
       ge_host, ge_home    → replaced by their t-1 values
       ln_gdp_pc_host      → log(gdp_pc_host_{t-1})  [new column]
       ln_gdp_pc_home      → log(gdp_pc_home_{t-1})  [new column]
       gdp_pc_host, gdp_pc_home → dropped (contemporaneous raw values; use ln_gdp_pc_* instead)
     Rationale: using predetermined (t-1) values avoids simultaneity bias in
     the regression. wdi_clean.parquet includes 2007 so year 2008 observations
     obtain their t-1 lag correctly.

  2. Drop internal investment rows (home_country == host_country).
     Rationale: FDI gravity models are defined on cross-border pairs only.

  3. Drop NACE Section K (Financial and Insurance Activities).
     Rationale: Section K is dominated by SPVs, holding companies, and
     confidentiality suppressions. Its disaster-response dynamics are
     structurally incomparable to manufacturing/service sectors, and its
     GVC position values are anomalous (financial intermediation is
     mechanically upstream in input-output tables).

  4. Listwise deletion on host macro-controls:
       ln_gdp_pc_host, pop_host, ge_host
     Rationale: rows missing these are geographic/statistical aggregates
     or very small territories without WDI/WGI coverage.

  5. Listwise deletion on gravity variable:
       distw
     Rationale: same as above — CEPII has no entry for these pairs.

  6. Dyad pruning — drop structural zeros:
       Remove any (home_country, host_country, industry) triplet where
       sum(ent) across all years is 0 or NaN (using min_count=1 so a
       dyad whose ent is always NaN/confidentiality-suppressed is also
       dropped).  Rationale: purely zero/missing dyads carry no
       information for the level equation and inflate the panel.

  7. Dual-strategy structure preserved (no nace_section filter applied):
       Strategy A : industry == "B-S_X_O"  (aggregate manufacturing)
       Strategy B : nace_section.notna()   (section-letter rows, has GVC)
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = os.path.join(ROOT, "data", "Silver")
IN     = os.path.join(SILVER, "panel_final.parquet")
OUT    = os.path.join(SILVER, "estimation_sample.parquet")

print("=== ESTIMATION SAMPLE SELECTION ===\n")

# ── Load ────────────────────────────────────────────────────────────────────
print(f"Loading: {IN}")
df = pd.read_parquet(IN)
print(f"  Input shape: {df.shape}")
print(f"  Columns ({len(df.columns)}): {list(df.columns)}\n")

# ── Step 1: NaN → 0 for disaster and historical exposure columns ─────────
ZERO_PREFIXES = ("n_", "sev_", "hist_sev_", "hist_cnt_")
zero_cols = [c for c in df.columns if c.startswith(ZERO_PREFIXES)]

print(f"Step 1: NaN → 0.0 imputation for {len(zero_cols)} disaster/exposure columns")
total_imputed = 0
for col in zero_cols:
    n_nan = df[col].isna().sum()
    if n_nan > 0:
        df[col] = df[col].fillna(0.0)
        print(f"  {col:<45} {n_nan:>8,} NaNs imputed")
        total_imputed += n_nan
    else:
        df[col] = df[col].fillna(0.0)  # ensure float dtype even if 0 NaNs
print(f"  Total NaNs imputed: {total_imputed:,}")
print(f"  Shape after step 1: {df.shape}\n")

# ── Step 1b: Lag economic macro controls; create ln_gdp_pc variables ─────────
# Load Silver source files directly so 2007 values are available as t-1 lag for 2008.
# wdi_clean.parquet keeps years 2007-2019; wgi_clean.parquet keeps years 2007-2019
# (03_clean_wdi_wgi.py was updated to include 2007 for GE).
print("Step 1b: Lag ge_* and gdp_pc_* to t-1; create ln_gdp_pc_host/home")

df_wdi_src = pd.read_parquet(os.path.join(SILVER, "wdi_clean.parquet"))
df_wgi_src = pd.read_parquet(os.path.join(SILVER, "wgi_clean.parquet"))

# Build t-1 lookups: shift year forward by 1 so value(t-1) is matched to year t
gdp_lag = (
    df_wdi_src[["country_code", "year", "gdp_pc_const2015_usd"]]
    .dropna(subset=["gdp_pc_const2015_usd"])
    .copy()
)
gdp_lag["year"] = gdp_lag["year"] + 1

ge_lag = (
    df_wgi_src[["country_code", "year", "ge_estimate"]]
    .dropna(subset=["ge_estimate"])
    .copy()
)
ge_lag["year"] = ge_lag["year"] + 1

for side, country_col, ge_col in [
    ("host", "host_country", "ge_host"),
    ("home", "home_country", "ge_home"),
]:
    # Merge lagged GDP: creates ln_gdp_pc_{side} from log(gdp_pc_{t-1})
    df = df.merge(
        gdp_lag.rename(columns={"country_code": country_col, "gdp_pc_const2015_usd": "_gdp_lag"}),
        on=[country_col, "year"], how="left"
    )
    df[f"ln_gdp_pc_{side}"] = np.log(df["_gdp_lag"])
    df = df.drop(columns=["_gdp_lag"])

    # Replace ge_{side} with its t-1 value
    df = df.drop(columns=[ge_col]).merge(
        ge_lag.rename(columns={"country_code": country_col, "ge_estimate": ge_col}),
        on=[country_col, "year"], how="left"
    )

    print(f"  ln_gdp_pc_{side} NaN: {df[f'ln_gdp_pc_{side}'].isna().sum():,}")
    print(f"  {ge_col:<12} NaN: {df[ge_col].isna().sum():,}")

# Drop raw contemporaneous gdp_pc columns — regression must use ln_gdp_pc_* (lagged)
df = df.drop(columns=["gdp_pc_host", "gdp_pc_home"], errors="ignore")
print(f"  Dropped gdp_pc_host, gdp_pc_home (contemporaneous raw; ln_gdp_pc_* are the lagged versions)")
print(f"  Shape after step 1b: {df.shape}\n")

# ── Step 2: Drop internal investment (home == host) ──────────────────────
print("Step 2: Drop rows where home_country == host_country (internal investment)")
before = len(df)
df = df[df["home_country"] != df["host_country"]].copy()
dropped = before - len(df)
print(f"  Dropped: {dropped:,} rows  →  {len(df):,} remaining\n")

# ── Step 3: Drop NACE Section K (Financial & Insurance Activities) ───────
print("Step 3: Drop NACE Section K (Financial and Insurance Activities)")
before = len(df)
df = df[df["industry"] != "K"].copy()
dropped = before - len(df)
print(f"  Dropped: {dropped:,} rows  →  {len(df):,} remaining\n")

# ── Step 4: Listwise deletion on host macro-controls ────────────────────
MACRO_CONTROLS = ["ln_gdp_pc_host", "pop_host", "ge_host"]
print(f"Step 4: Listwise deletion on host macro-controls: {MACRO_CONTROLS}")
before = len(df)
df = df.dropna(subset=MACRO_CONTROLS)
dropped = before - len(df)
print(f"  Dropped: {dropped:,} rows  →  {len(df):,} remaining\n")

# ── Step 5: Listwise deletion on gravity ─────────────────────────────────
print("Step 5: Listwise deletion on gravity variable: distw")
before = len(df)
df = df.dropna(subset=["distw"])
dropped = before - len(df)
print(f"  Dropped: {dropped:,} rows  →  {len(df):,} remaining\n")

# ── Step 6: Dyad pruning — drop structural zeros ─────────────────────────
print("Step 6: Dyad pruning — drop dyads where ent is always 0 or NaN")
before = len(df)
dyad_cols = ["home_country", "host_country", "industry"]
dyad_ent_sum = df.groupby(dyad_cols)["ent"].sum(min_count=1)
active_dyads = (
    dyad_ent_sum[dyad_ent_sum > 0]
    .reset_index()[dyad_cols]
    .assign(_keep=True)
)
df = df.merge(active_dyads, on=dyad_cols, how="inner").drop(columns="_keep")
dropped = before - len(df)
n_dyads_before = before // df["year"].nunique()  # approximate
n_dyads_after  = len(active_dyads)
print(f"  Active dyads retained: {n_dyads_after:,}")
print(f"  Dropped: {dropped:,} rows  →  {len(df):,} remaining\n")

# ── Summary ──────────────────────────────────────────────────────────────
print("=" * 70)
print("ESTIMATION SAMPLE SUMMARY")
print("=" * 70)
print(f"Shape: {df.shape}")

print(f"\nDual-strategy row counts:")
n_strategy_b = df["nace_section"].notna().sum()
n_strategy_a = (df["industry"] == "B-S_X_O").sum()
print(f"  Strategy B (nace_section.notna()): {n_strategy_b:>10,} rows")
print(f"  Strategy A (industry=B-S_X_O):    {n_strategy_a:>10,} rows")

print(f"\nYear range: {df['year'].min()} - {df['year'].max()}")
print(f"Home countries ({df['home_country'].nunique()}): "
      f"{sorted(df['home_country'].unique())}")
print(f"Host countries: {df['host_country'].nunique()}")

print(f"\nMissing values (key variables):")
key_check_cols = [
    "ent", "emp", "tur",
    "ln_gdp_pc_host", "pop_host", "ge_host",
    "ln_gdp_pc_home", "pop_home", "ge_home",
    "distw", "gvc_position",
] + zero_cols
for col in key_check_cols:
    if col in df.columns:
        pct = df[col].isna().mean() * 100
        if pct > 0:
            print(f"  {col:<45} {pct:5.1f}% missing")

# Confirm zero_cols have no NaN remaining
residual_nans = sum(df[c].isna().sum() for c in zero_cols)
if residual_nans == 0:
    print(f"\n  OK: all {len(zero_cols)} disaster/exposure columns have 0 NaNs.")
else:
    print(f"\n  WARNING: {residual_nans:,} NaNs remain in disaster/exposure columns!")

# ── Save ─────────────────────────────────────────────────────────────────
df.to_parquet(OUT, index=False)
print(f"\nSaved: {OUT}")
print(f"File size: {os.path.getsize(OUT)/1024/1024:.1f} MB")
