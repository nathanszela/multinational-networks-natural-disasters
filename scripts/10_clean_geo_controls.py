"""
10_clean_geo_controls.py
Static geographic host-country controls.

Sources:
  - Land area: data/Bronze/worldbank/land_size/API_AG.LND.TOTL.K2_DS2_en_csv_v2_265772.csv
    WB indicator AG.LND.TOTL.K2 — Land area (sq. km). Country codes are WB codes
    (same system as WDI); 06_standardise_countries.py handles these in wdi_clean.
    Land area is essentially time-invariant — this script takes the mean over
    2008-2019 as a single static value per country.

  - Landlocked: data/Bronze/worldbank/landlocked-countries-2026.csv
    43 landlocked countries with ISO-2 flag codes. All other countries get 0.
    Conversion: flagCode (ISO-2) → ISO-3 via country_converter.

Note: This script applies its own ISO-3 standardisation and does NOT need to pass
through 06_standardise_countries.py. The output already uses ISO-3 country codes.

Run order: independent of 01-05; must complete before 06 (which re-saves Silver
files). In practice run it alongside 01-05.

Output: data/Silver/geo_static.parquet
  country_code   : str (ISO-3)
  surface_area_km2: float — mean land area (sq. km) over 2008-2019
  landlocked     : int8 — 1 if landlocked, 0 otherwise
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
import country_converter as coco

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRONZE = os.path.join(ROOT, "data", "Bronze", "worldbank")
SILVER = os.path.join(ROOT, "data", "Silver")
OUT    = os.path.join(SILVER, "geo_static.parquet")

PANEL_YEARS = [str(y) for y in range(2008, 2020)]

cc = coco.CountryConverter()
print("=== GEO STATIC CONTROLS ===\n")

# ── Part 1: Land area (surface area in sq. km) ────────────────────────────────
print("--- Part 1: Land area (WB AG.LND.TOTL.K2) ---")

land_path = os.path.join(BRONZE, "land_size",
    "API_AG.LND.TOTL.K2_DS2_en_csv_v2_265772.csv")
land_raw = pd.read_csv(land_path, skiprows=4)

# Keep Country Code + panel year columns; drop aggregates and trailing empty cols
year_cols = [c for c in land_raw.columns if c in PANEL_YEARS]
land = land_raw[["Country Code"] + year_cols].copy()
land = land.rename(columns={"Country Code": "country_code_wb"})

# Mean over 2008-2019 (land area is static; mean handles rare year-to-year noise)
land["surface_area_km2"] = land[year_cols].mean(axis=1, skipna=True)

# Drop rows where all panel years are NaN (2 countries per the data inspection)
before = len(land)
land = land.dropna(subset=["surface_area_km2"])
print(f"  Dropped {before - len(land)} rows with no land area in 2008-2019")
print(f"  Remaining: {len(land)} countries")

# Standardise country codes to ISO-3
land["country_code"] = cc.pandas_convert(land["country_code_wb"], to="ISO3", not_found=None)
unresolved_land = set(land["country_code"][land["country_code"] == land["country_code_wb"]].unique())
unresolved_land = {c for c in unresolved_land if c not in set(cc.data["ISO3"].dropna())}
if unresolved_land:
    print(f"  Unresolvable WB codes (aggregates/historical): {sorted(unresolved_land)}")

# Drop unresolvable WB aggregate codes (kept as-is by not_found=None but not real ISO-3)
valid_iso3 = set(cc.data["ISO3"].dropna().unique())
land = land[land["country_code"].isin(valid_iso3)].copy()
land = land[["country_code", "surface_area_km2"]].copy()
print(f"  Countries with valid ISO-3 and surface area: {len(land)}")
print(f"  Sample (first 5):\n{land.head().to_string(index=False)}")

# ── Part 2: Landlocked dummy ───────────────────────────────────────────────────
print("\n--- Part 2: Landlocked countries ---")

lock_path = os.path.join(BRONZE, "landlocked-countries-2026.csv")
lock_raw = pd.read_csv(lock_path)

# flagCode is ISO-2; convert to ISO-3
lock_raw["country_code"] = cc.pandas_convert(lock_raw["flagCode"], to="ISO3", not_found=None)

failed_lock = lock_raw[lock_raw["country_code"].isna()]
if not failed_lock.empty:
    print(f"  WARNING: Could not convert {len(failed_lock)} landlocked flag codes:")
    print(f"    {list(failed_lock['flagCode'])}")

landlocked_iso3 = set(lock_raw["country_code"].dropna().unique())
print(f"  Landlocked countries (ISO-3): {len(landlocked_iso3)}")
print(f"  {sorted(landlocked_iso3)}")

# ── Part 3: Merge and finalise ────────────────────────────────────────────────
print("\n--- Part 3: Merge ---")

# Add landlocked dummy to land area table
land["landlocked"] = land["country_code"].isin(landlocked_iso3).astype("int8")

print(f"  Landlocked = 1 in output: {land['landlocked'].sum()}")
print(f"  Landlocked = 0 in output: {(land['landlocked'] == 0).sum()}")

# Verify all landlocked ISO-3 codes appear in the table
missing_from_land = landlocked_iso3 - set(land["country_code"].dropna())
if missing_from_land:
    print(f"  INFO: Landlocked countries absent from land area file: {sorted(missing_from_land)}")
    # Add them as rows with NaN surface_area but landlocked=1
    extras = pd.DataFrame({
        "country_code": sorted(missing_from_land),
        "surface_area_km2": np.nan,
        "landlocked": np.int8(1),
    })
    land = pd.concat([land, extras], ignore_index=True)
    print(f"  Added {len(extras)} landlocked rows with NaN surface_area")

# Drop rows with NaN country_code (WB aggregates that failed conversion)
before = len(land)
land = land.dropna(subset=["country_code"])
print(f"  Dropped {before - len(land)} rows with NaN country_code (WB aggregates)")

# Ensure no duplicate country_code
dupes = land.duplicated(subset="country_code").sum()
if dupes:
    print(f"  WARNING: {dupes} duplicate country_code rows — deduplicating (keep first)")
    land = land.drop_duplicates(subset="country_code", keep="first")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("GEO STATIC SUMMARY")
print("=" * 60)
print(f"Shape: {land.shape}")
print(f"  country_code NaN:    {land['country_code'].isna().sum()}")
print(f"  surface_area NaN:    {land['surface_area_km2'].isna().sum()}")
print(f"  landlocked = 1:      {(land['landlocked'] == 1).sum()}")
print(f"  landlocked = 0:      {(land['landlocked'] == 0).sum()}")
print(f"\n  Sample (landlocked countries in our panel area):")
sample_landlocked = land[land["landlocked"] == 1].head(10)
print(sample_landlocked.to_string(index=False))

# ── Save ──────────────────────────────────────────────────────────────────────
land.to_parquet(OUT, index=False)
print(f"\nSaved: {OUT}")
print(f"File size: {os.path.getsize(OUT)/1024:.1f} KB")
