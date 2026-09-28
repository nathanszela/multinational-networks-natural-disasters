"""
02_clean_emdat.py
Clean EM-DAT natural disasters database.

emdat_clean.parquet  — (country_iso3, year) for panel years 2008-2019
  13 type count columns  : n_earthquake, n_volcanic_activity, n_mass_movement_dry,
                           n_mass_movement_wet, n_impact, n_flood, n_storm, n_wildfire,
                           n_drought, n_extreme_temperature, n_animal_incident,
                           n_epidemic, n_infestation
  3 severity group cols  : sev_sudden_physical  = ln(1 + sum(Total Affected)/population) for
                             Earthquake, Volcanic activity, Mass movement (dry/wet), Impact
                           sev_seasonal_physical = ln(1 + sum(Total Affected)/population) for
                             Flood, Storm, Wildfire
                           sev_climatic_slow     = ln(1 + sum(Total Affected)/population) for
                             Drought, Extreme temperature
                           (population = WDI country-year population; NaN if country absent from WDI)
  1 auxiliary col        : total_missing_affected (count of events with NaN Total Affected)

emdat_hist_exposure.parquet — (country_iso3, year) for panel years 2008-2019
  hist_sev_static          ln(1 + sum(total_affected_filled, 1987-2007) / pop_1987)  [time-invariant per country]
  hist_sev_dynamic         ln(1 + sum(total_affected_filled, [year-21, year-1]) / pop_(year-21))
  hist_cnt_sudden_static   count of Sudden Physical events 1987-2007 (auxiliary)
  hist_cnt_sudden_dynamic  count of Sudden Physical events [year-21, year-1] (auxiliary)
  hist_cnt_seasonal_static  count of Seasonal Physical events 1987-2007 (auxiliary)
  hist_cnt_seasonal_dynamic count of Seasonal Physical events [year-21, year-1] (auxiliary)
  hist_cnt_slow_static     count of Climatic Slow events 1987-2007 (auxiliary)
  hist_cnt_slow_dynamic    count of Climatic Slow events [year-21, year-1] (auxiliary)
  hist_cnt_total_static    count of all mapped disaster types 1987-2007 (auxiliary)
  hist_cnt_total_dynamic   count of all mapped disaster types [year-21, year-1] (auxiliary)
  NaN in hist_sev_* when country is absent from WDI population data.
  Note: windows are strictly pre-period (t-1 at most) so hist variables are
  predetermined with respect to contemporaneous disaster shocks.

Rules:
  1. Duration filter: multi-year events are kept and assigned to Start Year
  2. Disaster Type (13 categories) drives all severity and count columns
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRONZE = os.path.join(ROOT, "data", "Bronze", "Natural disasters")
WB_POP = os.path.join(ROOT, "data", "Bronze", "worldbank", "country population size",
                       "population_size.csv")
SILVER = os.path.join(ROOT, "data", "Silver")
os.makedirs(SILVER, exist_ok=True)

IN_FILE  = os.path.join(BRONZE, "disasters_from_1987.xlsx")
OUT_MAIN = os.path.join(SILVER, "emdat_clean.parquet")
OUT_HIST = os.path.join(SILVER, "emdat_hist_exposure.parquet")

# ── Configuration ──────────────────────────────────────────────────────────────
# Maps EM-DAT "Disaster Type" label -> column suffix
TYPE_MAP = {
    "Earthquake":          "earthquake",
    "Volcanic activity":   "volcanic_activity",
    "Mass movement (dry)": "mass_movement_dry",
    "Mass movement (wet)": "mass_movement_wet",
    "Impact":              "impact",
    "Flood":               "flood",
    "Storm":               "storm",
    "Wildfire":            "wildfire",
    "Drought":             "drought",
    "Extreme temperature": "extreme_temperature",
    "Animal incident":     "animal_incident",
    "Epidemic":            "epidemic",
    "Infestation":         "infestation",
}
ALL_TYPES = list(TYPE_MAP.values())

# Grouped severity: ln(1 + sum(Total Affected))
SEV_GROUPS = {
    "sev_sudden_physical":   ["Earthquake", "Volcanic activity",
                               "Mass movement (dry)", "Mass movement (wet)", "Impact"],
    "sev_seasonal_physical": ["Flood", "Storm", "Wildfire"],
    "sev_climatic_slow":     ["Drought", "Extreme temperature"],
}

# Historical count groups: mirrors SEV_GROUPS; drives hist_cnt_{group}_{static|dynamic}
HIST_CNT_GROUPS = {
    "sudden":   ["Earthquake", "Volcanic activity",
                 "Mass movement (dry)", "Mass movement (wet)", "Impact"],
    "seasonal": ["Flood", "Storm", "Wildfire"],
    "slow":     ["Drought", "Extreme temperature"],
}

PANEL_YEARS  = list(range(2008, 2020))   # 2008-2019 inclusive
STATIC_START = 1987
STATIC_END   = 2007

# ── Load ───────────────────────────────────────────────────────────────────────
print("Loading EM-DAT disasters...")
df = pd.read_excel(IN_FILE)
print(f"  Raw shape: {df.shape}")
df.columns = df.columns.str.strip()
print(f"  Columns: {list(df.columns)}")

# ── Identify key columns by pattern matching ──────────────────────────────────
col_map = {}
for c in df.columns:
    cl = c.lower().strip()
    if "iso" in cl and "iso3" not in cl.replace(" ", ""):
        col_map["iso"] = c
    elif "iso3" in cl.replace(" ", ""):
        col_map["iso3"] = c
    elif cl == "country":
        col_map["country_name"] = c
    elif "start" in cl and "year" in cl:
        col_map["start_year"] = c
    elif "end" in cl and "year" in cl:
        col_map["end_year"] = c
    elif cl == "disaster type":
        col_map["disaster_type"] = c
    elif "total affected" in cl:
        col_map["total_affected"] = c

print(f"\nDetected column mapping: {col_map}")

iso_col = col_map.get("iso3") or col_map.get("iso")
print(f"Using ISO column: {iso_col!r}")

if "disaster_type" not in col_map:
    raise RuntimeError("Could not detect 'Disaster Type' column — check column names.")

# ── Keep relevant columns ──────────────────────────────────────────────────────
keep = list({v for v in col_map.values()})
df = df[keep].copy()
rename = {v: k for k, v in col_map.items()}
df = df.rename(columns=rename)

if "iso3" in df.columns:
    df = df.rename(columns={"iso3": "country_iso3"})
elif "iso" in df.columns:
    df = df.rename(columns={"iso": "country_iso3"})

# ── Ensure numeric types ───────────────────────────────────────────────────────
for col in ["start_year", "end_year", "total_affected"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

print(f"\nYear range: {df['start_year'].min():.0f} - {df['start_year'].max():.0f}")
print(f"Disaster types found: {sorted(df['disaster_type'].dropna().unique())}")

# ── Duration filter ────────────────────────────────────────────────────────────
multi_year = (df["start_year"] != df["end_year"]).sum()
print(f"\nMulti-year events kept and assigned to start_year: {multi_year:,}")
df_filtered = df.copy()

# ── Binary indicator for missing Total Affected ───────────────────────────────
df_filtered["missing_affected"] = df_filtered["total_affected"].isna().astype("int8")
# 100-person proxy: EM-DAT entry criteria guarantee ≥100 affected; used in both
# panel severity (emdat_clean) and historical severity (emdat_hist_exposure)
df_filtered["total_affected_filled"] = df_filtered["total_affected"].fillna(100)

# ── Map disaster type to clean suffix ─────────────────────────────────────────
df_filtered["type_clean"] = df_filtered["disaster_type"].map(TYPE_MAP)
unmapped = df_filtered["type_clean"].isna()
if unmapped.any():
    print(f"\nINFO: {unmapped.sum()} rows with unmapped Disaster Type (will be excluded from counts/severity):")
    print(f"  {df_filtered.loc[unmapped, 'disaster_type'].value_counts().to_dict()}")

# ── Load WDI population ────────────────────────────────────────────────────────
print("\nLoading WDI population data (1987-1999 + 1987 for static)...")
df_pop_wide = pd.read_csv(WB_POP, skiprows=4)
df_pop_wide.columns = df_pop_wide.columns.str.strip()

if "Country Code" not in df_pop_wide.columns:
    raise RuntimeError("Could not find 'Country Code' column in WDI population file.")

# Pop 1987 for static exposure (denominator for 1987-2007 cumulated affected)
if "1987" in df_pop_wide.columns:
    df_pop1987 = (
        df_pop_wide[["Country Code", "1987"]]
        .rename(columns={"Country Code": "country_iso3", "1987": "pop_1987"})
        .dropna(subset=["pop_1987"])
    )
    df_pop1987["pop_1987"] = pd.to_numeric(df_pop1987["pop_1987"], errors="coerce")
    print(f"  pop_1987 loaded: {len(df_pop1987)} countries")
else:
    print("  WARNING: '1987' column not found — hist_sev_static will be NaN")
    df_pop1987 = pd.DataFrame(columns=["country_iso3", "pop_1987"])

# Population long table for years 1987-1999 (needed for dynamic exposure denominator)
dynamic_pop_years = [str(y) for y in range(STATIC_START, 2000) if str(y) in df_pop_wide.columns]
missing_pop_years = [str(y) for y in range(STATIC_START, 2000) if str(y) not in df_pop_wide.columns]
if missing_pop_years:
    print(f"  WARNING: Missing population years: {missing_pop_years}")

pop_cols = ["Country Code"] + dynamic_pop_years
df_pop_long = (
    df_pop_wide[pop_cols]
    .rename(columns={"Country Code": "country_iso3"})
    .melt(id_vars="country_iso3", var_name="pop_year", value_name="population")
)
df_pop_long["pop_year"] = df_pop_long["pop_year"].astype(int)
df_pop_long["population"] = pd.to_numeric(df_pop_long["population"], errors="coerce")
df_pop_long = df_pop_long.dropna(subset=["population"])
print(f"  Population long table: {len(df_pop_long)} rows ({len(dynamic_pop_years)} years × countries)")

# Population for panel years 2008-2019 (severity denominator)
panel_pop_years = [str(y) for y in PANEL_YEARS if str(y) in df_pop_wide.columns]
df_pop_panel = (
    df_pop_wide[["Country Code"] + panel_pop_years]
    .rename(columns={"Country Code": "country_iso3"})
    .melt(id_vars="country_iso3", var_name="pop_year", value_name="pop_panel")
)
df_pop_panel["pop_year"] = df_pop_panel["pop_year"].astype(int)
df_pop_panel["pop_panel"] = pd.to_numeric(df_pop_panel["pop_panel"], errors="coerce")
df_pop_panel = df_pop_panel.dropna(subset=["pop_panel"])
print(f"  Panel population table: {len(df_pop_panel)} rows ({len(panel_pop_years)} years × countries)")

# ── Build type count pivot ─────────────────────────────────────────────────────
print("\nAggregating disaster counts by (country, year, type)...")
df_typed = df_filtered.dropna(subset=["type_clean"])

count_agg = (
    df_typed
    .groupby(["country_iso3", "start_year", "type_clean"])
    .size()
    .reset_index(name="count")
)
count_pivot = count_agg.pivot_table(
    index=["country_iso3", "start_year"],
    columns="type_clean",
    values="count",
    aggfunc="sum",
    fill_value=0,
).add_prefix("n_").reset_index()
count_pivot.columns.name = None

# Ensure all 13 type columns present
for t in ALL_TYPES:
    col = f"n_{t}"
    if col not in count_pivot.columns:
        count_pivot[col] = 0
        print(f"  Added zero column: {col}")

# ── Build 3 grouped severity columns: ln(1 + sum(Total Affected)) ───────────
print("Building grouped severity columns...")
df_sev = df_filtered.copy()

sev_frames = []
for sev_col, types_in_group in SEV_GROUPS.items():
    mask = df_sev["disaster_type"].isin(types_in_group)
    grp = (
        df_sev[mask]
        .groupby(["country_iso3", "start_year"], dropna=False)["total_affected_filled"]
        .sum()
        .reset_index()
    )
    grp = grp.merge(
        df_pop_panel.rename(columns={"pop_year": "start_year"}),
        on=["country_iso3", "start_year"], how="left"
    )
    grp[sev_col] = np.log1p(grp["total_affected_filled"] / grp["pop_panel"])
    sev_frames.append(grp[["country_iso3", "start_year", sev_col]])

# Merge all three sev_ frames together (outer so a country-year with any event appears)
sev_merged = sev_frames[0]
for sf in sev_frames[1:]:
    sev_merged = sev_merged.merge(sf, on=["country_iso3", "start_year"], how="outer")
for sev_col in SEV_GROUPS:
    sev_merged[sev_col] = sev_merged[sev_col].fillna(0.0)

# ── Build total_missing_affected ──────────────────────────────────────────────
missing_agg = (
    df_filtered
    .groupby(["country_iso3", "start_year"], dropna=False)
    .agg(total_missing_affected=("missing_affected", "sum"))
    .reset_index()
)

# ── Combine all columns ────────────────────────────────────────────────────────
# Start from count_pivot (has all typed events), outer-join sev and missing
df_panel = count_pivot.merge(sev_merged, on=["country_iso3", "start_year"], how="outer")
df_panel = df_panel.merge(missing_agg, on=["country_iso3", "start_year"], how="outer")

# Fill zeros for count cols that may be NaN after outer join
for t in ALL_TYPES:
    df_panel[f"n_{t}"] = df_panel[f"n_{t}"].fillna(0).astype(int)
for sev_col in SEV_GROUPS:
    df_panel[sev_col] = df_panel[sev_col].fillna(0.0)

df_panel = df_panel.rename(columns={"start_year": "year"})
df_panel = df_panel[(df_panel["year"] >= 2008) & (df_panel["year"] <= 2019)].copy()
df_panel["year"] = df_panel["year"].astype(int)

print(f"Panel shape (2008-2019): {df_panel.shape}")

df_panel.to_parquet(OUT_MAIN, index=False)
print(f"\nSaved emdat_clean.parquet: {OUT_MAIN}")

# ── Historical Exposure ────────────────────────────────────────────────────────
print("\nComputing Historical Exposure (static 1987-2007 + dynamic rolling-21yr ending t-1)...")

# --- Static: log-severity + group counts for events 1987-2007 per country ---
df_static_events = df_filtered[
    (df_filtered["start_year"] >= STATIC_START) &
    (df_filtered["start_year"] <= STATIC_END)
]
df_static_typed = df_static_events.dropna(subset=["type_clean"])

static_agg = (
    df_static_events
    .groupby("country_iso3", dropna=False)
    .agg(hist_sum_affected_static=("total_affected_filled", "sum"))
    .reset_index()
)
static_agg = static_agg.merge(df_pop1987, on="country_iso3", how="left")
# NaN when population missing (country absent from WDI)
static_agg["hist_sev_static"] = np.log1p(
    static_agg["hist_sum_affected_static"] / static_agg["pop_1987"]
)

# Group-specific event counts (mapped types only)
for grp_name, types_in_grp in HIST_CNT_GROUPS.items():
    mask = df_static_typed["disaster_type"].isin(types_in_grp)
    grp_cnt = (
        df_static_typed[mask]
        .groupby("country_iso3", dropna=False)
        .size()
        .reset_index(name=f"hist_cnt_{grp_name}_static")
    )
    static_agg = static_agg.merge(grp_cnt, on="country_iso3", how="left")
    static_agg[f"hist_cnt_{grp_name}_static"] = (
        static_agg[f"hist_cnt_{grp_name}_static"].fillna(0).astype(int)
    )

# Total count across all 13 mapped disaster types
total_cnt_static = (
    df_static_typed
    .groupby("country_iso3", dropna=False)
    .size()
    .reset_index(name="hist_cnt_total_static")
)
static_agg = static_agg.merge(total_cnt_static, on="country_iso3", how="left")
static_agg["hist_cnt_total_static"] = static_agg["hist_cnt_total_static"].fillna(0).astype(int)

static_counts = static_agg[[
    "country_iso3", "hist_sev_static",
    "hist_cnt_sudden_static", "hist_cnt_seasonal_static",
    "hist_cnt_slow_static",   "hist_cnt_total_static",
]]

# Broadcast static values across all panel years
static_broadcast = static_counts.copy()
static_broadcast = static_broadcast.loc[
    static_broadcast.index.repeat(len(PANEL_YEARS))
].reset_index(drop=True)
static_broadcast["year"] = PANEL_YEARS * len(static_counts)
static_broadcast = static_broadcast.sort_values(["country_iso3", "year"]).reset_index(drop=True)

# --- Dynamic: rolling 21-year window ending at t-1 per panel year ---
# For year t: window = [t-21, t-1]  e.g. 2008 → [1987, 2007], 2009 → [1988, 2008]
# This ensures the variable is strictly predetermined w.r.t. contemporaneous shocks.
dynamic_records = []
for y in PANEL_YEARS:
    window_start = y - 21   # e.g. 2008 -> 1987
    window_end   = y - 1    # e.g. 2008 -> 2007
    df_dyn = df_filtered[
        (df_filtered["start_year"] >= window_start) &
        (df_filtered["start_year"] <= window_end)
    ]
    df_dyn_typed = df_dyn.dropna(subset=["type_clean"])

    dyn_agg = (
        df_dyn
        .groupby("country_iso3", dropna=False)
        .agg(hist_sum_affected_dynamic=("total_affected_filled", "sum"))
        .reset_index()
    )
    pop_year_df = df_pop_long[df_pop_long["pop_year"] == window_start][
        ["country_iso3", "population"]
    ]
    dyn_agg = dyn_agg.merge(pop_year_df, on="country_iso3", how="left")
    # NaN when population missing (country absent from WDI)
    dyn_agg["hist_sev_dynamic"] = np.log1p(
        dyn_agg["hist_sum_affected_dynamic"] / dyn_agg["population"]
    )

    # Group-specific event counts (mapped types only)
    for grp_name, types_in_grp in HIST_CNT_GROUPS.items():
        mask = df_dyn_typed["disaster_type"].isin(types_in_grp)
        grp_cnt = (
            df_dyn_typed[mask]
            .groupby("country_iso3", dropna=False)
            .size()
            .reset_index(name=f"hist_cnt_{grp_name}_dynamic")
        )
        dyn_agg = dyn_agg.merge(grp_cnt, on="country_iso3", how="left")
        dyn_agg[f"hist_cnt_{grp_name}_dynamic"] = (
            dyn_agg[f"hist_cnt_{grp_name}_dynamic"].fillna(0).astype(int)
        )

    # Total count across all 13 mapped disaster types
    total_dyn = (
        df_dyn_typed
        .groupby("country_iso3", dropna=False)
        .size()
        .reset_index(name="hist_cnt_total_dynamic")
    )
    dyn_agg = dyn_agg.merge(total_dyn, on="country_iso3", how="left")
    dyn_agg["hist_cnt_total_dynamic"] = dyn_agg["hist_cnt_total_dynamic"].fillna(0).astype(int)

    dyn_agg["year"] = y
    dynamic_records.append(
        dyn_agg[[
            "country_iso3", "year",
            "hist_sev_dynamic",
            "hist_cnt_sudden_dynamic", "hist_cnt_seasonal_dynamic",
            "hist_cnt_slow_dynamic",   "hist_cnt_total_dynamic",
        ]]
    )

df_dynamic = pd.concat(dynamic_records, ignore_index=True)
df_dynamic["year"] = df_dynamic["year"].astype(int)

# --- Combine static + dynamic ---
df_hist = static_broadcast.merge(df_dynamic, on=["country_iso3", "year"], how="outer")

# Fill group counts that may be NaN after outer join
HIST_CNT_COLS = [
    f"hist_cnt_{grp}_{window}"
    for grp in list(HIST_CNT_GROUPS.keys()) + ["total"]
    for window in ["static", "dynamic"]
]
for col in HIST_CNT_COLS:
    df_hist[col] = df_hist[col].fillna(0).astype(int)
# hist_sev_* remain NaN when population is missing — intentional, do not fill with 0
df_hist = df_hist.sort_values(["country_iso3", "year"]).reset_index(drop=True)

# Reorder columns: primary severity vars first, then auxiliary counts by group
df_hist = df_hist[[
    "country_iso3", "year",
    "hist_sev_static",          "hist_sev_dynamic",
    "hist_cnt_sudden_static",   "hist_cnt_sudden_dynamic",
    "hist_cnt_seasonal_static", "hist_cnt_seasonal_dynamic",
    "hist_cnt_slow_static",     "hist_cnt_slow_dynamic",
    "hist_cnt_total_static",    "hist_cnt_total_dynamic",
]]

df_hist.to_parquet(OUT_HIST, index=False)
print(f"Saved emdat_hist_exposure.parquet: {OUT_HIST}")
print(f"  Shape: {df_hist.shape}")

# ── Validation ─────────────────────────────────────────────────────────────────
print("\n=== EM-DAT CLEAN SUMMARY ===")
print(f"Panel (2008-2019): {df_panel.shape}")

expected_main = (
    {"country_iso3", "year"}
    | {f"n_{t}" for t in ALL_TYPES}
    | set(SEV_GROUPS.keys())
    | {"total_missing_affected"}
)
missing_main = expected_main - set(df_panel.columns)
extra_main   = set(df_panel.columns) - expected_main
if missing_main:
    print(f"WARNING: Missing expected columns: {missing_main}")
else:
    print(f"All {len(expected_main)} expected columns present.")
if extra_main:
    print(f"INFO: Extra columns in panel: {extra_main}")

print(f"\nType count columns (non-zero rows):")
for t in ALL_TYPES:
    col = f"n_{t}"
    print(f"  {col:<35} {(df_panel[col] > 0).sum():,} non-zero rows")

print(f"\nSeverity group columns (non-zero rows):")
for sev_col in SEV_GROUPS:
    print(f"  {sev_col:<35} {(df_panel[sev_col] > 0).sum():,} non-zero rows  "
          f"max={df_panel[sev_col].max():.2f}")

print(f"\ntotal_missing_affected: "
      f"range {df_panel['total_missing_affected'].min()} - {df_panel['total_missing_affected'].max()}")

print(f"\nHistorical exposure sample (USA, IND, JPN):")
sample = df_hist[df_hist["country_iso3"].isin(["USA", "IND", "JPN"])].head(12)
print(sample[["country_iso3", "year", "hist_sev_static", "hist_sev_dynamic",
              "hist_cnt_sudden_static", "hist_cnt_seasonal_static",
              "hist_cnt_slow_static", "hist_cnt_total_static"]].to_string(index=False))

print(f"\nMissing values in panel:")
nans = df_panel.isnull().sum()
print(nans[nans > 0] if nans.any() else "  None")

print(f"\nSample panel (5 rows):")
print(df_panel.head(5).to_string())
