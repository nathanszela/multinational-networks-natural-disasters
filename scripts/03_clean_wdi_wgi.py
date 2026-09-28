"""
04_clean_wdi_wgi.py
Clean World Bank WDI (GDP per capita, Population) and WGI (Government Effectiveness).

WDI:
  - API_NY.GDP.MKTP.KD_DS2_en_csv_v2_374654.csv  -> gdp_pc (constant 2015 USD)
  - population_size.csv  -> population
  - Wide format, skiprows=4, years 1960-2025 as columns
  - Keep: Country Code, year 2000, years 2008-2019
  - Reshape to long

WGI:
  - wgidataset_with_sourcedata-2025.xlsx
  - Keep only Government Effectiveness (ge) estimate
  - Years 2007-2019 (2007 needed as t-1 lag for panel year 2008)

Output:
  data/Silver/wdi_clean.parquet
  data/Silver/wgi_clean.parquet
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WB_DIR = os.path.join(ROOT, "data", "Bronze", "worldbank")
SILVER = os.path.join(ROOT, "data", "Silver")
os.makedirs(SILVER, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# WDI: GDP per capita
# ─────────────────────────────────────────────────────────────
def clean_wdi(filepath, value_col_name):
    df = pd.read_csv(filepath, skiprows=4)
    df.columns = df.columns.str.strip().str.strip('"')
    print(f"\nLoaded {os.path.basename(filepath)}: {df.shape}")
    print(f"  Columns sample: {list(df.columns[:6])} ... {list(df.columns[-3:])}")

    # Identify country code column
    cc_col = next((c for c in df.columns if "country code" in c.lower()), None)
    if cc_col is None:
        # try exact match
        cc_col = "Country Code"
    print(f"  Country Code column: {cc_col!r}")

    # Year columns to keep: 2000 (exposure baseline) + 2007 (GDP lag for 2008) + 2008-2019 (panel)
    year_cols_keep = ["2000"] + [str(y) for y in range(2007, 2020)]
    available = [y for y in year_cols_keep if y in df.columns]
    missing_yrs = [y for y in year_cols_keep if y not in df.columns]
    if missing_yrs:
        print(f"  WARNING: missing year columns: {missing_yrs}")

    keep = [cc_col] + available
    df = df[keep].copy()

    # Melt to long
    df = df.melt(id_vars=[cc_col], value_vars=available,
                  var_name="year", value_name=value_col_name)
    df = df.rename(columns={cc_col: "country_code"})
    df["year"] = df["year"].astype("int16")
    df[value_col_name] = pd.to_numeric(df[value_col_name], errors="coerce")

    # Drop rows where country_code looks like an aggregate (starts with numbers or contains spaces)
    df = df.dropna(subset=["country_code"])
    df["country_code"] = df["country_code"].astype(str).str.strip().str.strip('"')
    # Keep only 3-letter ISO-like codes
    df = df[df["country_code"].str.len() == 3].copy()

    print(f"  Final shape: {df.shape}")
    print(f"  Countries: {df['country_code'].nunique()}")
    return df

print("=== WDI: GDP per capita ===")
df_gdp = clean_wdi(
    os.path.join(WB_DIR, "country gdp", "API_NY.GDP.MKTP.KD_DS2_en_csv_v2_374654.csv"),
    "gdp_pc"
)
print(f"  Sample:\n{df_gdp.head(3).to_string()}")

print("\n=== WDI: Population ===")
df_pop = clean_wdi(
    os.path.join(WB_DIR, "country population size", "population_size.csv"),
    "population"
)
print(f"  Sample:\n{df_pop.head(3).to_string()}")

# Merge GDP and Population
df_wdi = df_gdp.merge(df_pop, on=["country_code", "year"], how="outer")

# NY.GDP.MKTP.KD: total GDP in constant 2015 USD (not per capita).
# Compute GDP per capita = total_gdp / population.
df_wdi = df_wdi.rename(columns={"gdp_pc": "gdp_total_const2015_usd"})
df_wdi["gdp_pc_const2015_usd"] = df_wdi["gdp_total_const2015_usd"] / df_wdi["population"]
print("NOTE: GDP file is total GDP (NY.GDP.MKTP.KD, constant 2015 USD).")
print("      Computed gdp_pc_const2015_usd = total_gdp / population.")
print(f"\nWDI merged: {df_wdi.shape}")
print(f"Missing values:\n{df_wdi[['country_code','year','gdp_total_const2015_usd','gdp_pc_const2015_usd','population']].isnull().sum()}")
print(f"\nSample (USA 2019):")
print(df_wdi[(df_wdi['country_code']=='USA') & (df_wdi['year']==2019)].to_string())

df_wdi.to_parquet(os.path.join(SILVER, "wdi_clean.parquet"), index=False)
print(f"\nSaved: {os.path.join(SILVER, 'wdi_clean.parquet')}")

# ─────────────────────────────────────────────────────────────
# WGI: Government Effectiveness
# ─────────────────────────────────────────────────────────────
print("\n=== WGI: Government Effectiveness ===")
wgi_file = os.path.join(WB_DIR, "wgidataset_with_sourcedata-2025.xlsx")
xf = pd.ExcelFile(wgi_file)
print(f"WGI sheets: {xf.sheet_names}")

# Find the Government Effectiveness sheet
ge_sheet = next(
    (s for s in xf.sheet_names if "gov" in s.lower() and "eff" in s.lower()),
    None
)
if ge_sheet is None:
    # Try looking for 'ge' or 'GovernmentEffectiveness'
    ge_sheet = next(
        (s for s in xf.sheet_names
         if s.lower() in ("ge", "governmenteffectiveness", "government effectiveness")),
        None
    )
if ge_sheet is None:
    print("WARNING: Could not auto-detect Government Effectiveness sheet.")
    print("Available sheets:", xf.sheet_names)
    # Try first non-'SourceData' sheet
    ge_sheet = next((s for s in xf.sheet_names if "source" not in s.lower()), xf.sheet_names[0])
    print(f"Using sheet: {ge_sheet!r}")
else:
    print(f"Using GE sheet: {ge_sheet!r}")

# Read with header=None first to understand structure
df_wgi_raw = pd.read_excel(xf, sheet_name=ge_sheet, header=None, nrows=10)
print(f"\nFirst 10 rows raw:")
for i, row in df_wgi_raw.iterrows():
    non_null = [(j, str(v)[:60]) for j, v in enumerate(row) if pd.notna(v)]
    if non_null:
        print(f"  Row {i}: {non_null}")

# Determine header row (usually row 0 or 1 or 2)
# WGI datasets typically have: country code, country name, indicator, year columns
# or country code, year as rows
# Try reading with header=0 first
df_wgi_try = pd.read_excel(xf, sheet_name=ge_sheet, header=0)
print(f"\nWith header=0: {df_wgi_try.shape}, cols: {list(df_wgi_try.columns[:8])}")

# Check if year is a column or years are row values
# WGI 2025 format: typically long format with columns CountryName, CountryCode, Indicator, Year, Estimate, StdErr...
if "Year" in df_wgi_try.columns or "year" in df_wgi_try.columns.str.lower().tolist():
    print("  -> Long format detected (Year as column)")
    df_wgi = df_wgi_try.copy()
    # Standardise column names
    df_wgi.columns = [c.strip() for c in df_wgi.columns]
    # Find relevant columns
    # WGI 2025 specific column names
    # Col: 'Economy (code)' -> ISO-3, 'Year' -> year,
    #      'Governance estimate (approx. -2.5 to +2.5)' -> ge_estimate
    # Since we already loaded the 'ge' sheet, all rows are GE - no indicator filter needed
    year_col = next((c for c in df_wgi.columns if c.strip().lower() == "year"), None)
    code_col = next((c for c in df_wgi.columns
                     if "economy" in c.lower() and "code" in c.lower()
                     and "id" not in c.lower()), None)
    est_col  = next((c for c in df_wgi.columns if "governance estimate" in c.lower()), None)
    print(f"  Columns: year={year_col!r}, code={code_col!r}, estimate={est_col!r}")
    print(f"  All columns: {list(df_wgi.columns[:10])}")

    df_ge = df_wgi.copy()

    rename_dict = {}
    if year_col:  rename_dict[year_col] = "year"
    if code_col:  rename_dict[code_col] = "country_code"
    if est_col:   rename_dict[est_col]  = "ge_estimate"
    df_ge = df_ge.rename(columns=rename_dict)
    select_cols = [c for c in ["year","country_code","ge_estimate"] if c in df_ge.columns]
    print(f"  Selecting columns: {select_cols}")
    df_ge = df_ge[select_cols].copy()
    df_ge["year"]        = pd.to_numeric(df_ge["year"], errors="coerce")
    df_ge["ge_estimate"] = pd.to_numeric(df_ge["ge_estimate"], errors="coerce")
    df_ge = df_ge.dropna(subset=["year","country_code"])
    df_ge["year"] = df_ge["year"].astype("int16")
else:
    # Wide format: country codes as rows, years as columns
    print("  -> Wide format detected")
    # Find the header row by looking for '1996' (WGI starts 1996)
    for hrow in range(0, 10):
        df_test = pd.read_excel(xf, sheet_name=ge_sheet, header=hrow)
        if any("1996" in str(c) for c in df_test.columns):
            print(f"  Header row: {hrow}")
            break
    df_wgi = df_test.copy()
    # Identify code col
    code_col = next((c for c in df_wgi.columns
                     if isinstance(c, str) and ("code" in c.lower() or c.strip() == "")), df_wgi.columns[0])
    year_cols = [c for c in df_wgi.columns if str(c).isdigit() or str(c)[:4].isdigit()]
    # Keep year 2008-2019 only
    keep_years = [c for c in year_cols if str(c)[:4].isdigit() and 2007 <= int(str(c)[:4]) <= 2019]
    df_ge = df_wgi[[code_col] + keep_years].copy()
    df_ge = df_ge.melt(id_vars=[code_col], value_vars=keep_years,
                        var_name="year", value_name="ge_estimate")
    df_ge = df_ge.rename(columns={code_col: "country_code"})
    df_ge["year"] = pd.to_numeric(df_ge["year"], errors="coerce").astype("int16")
    df_ge["ge_estimate"] = pd.to_numeric(df_ge["ge_estimate"], errors="coerce")

# Filter years 2007-2019 (2007 retained as t-1 lag source for panel year 2008)
df_ge = df_ge[(df_ge["year"] >= 2007) & (df_ge["year"] <= 2019)].copy()
df_ge = df_ge.dropna(subset=["ge_estimate"])
df_ge["country_code"] = df_ge["country_code"].astype(str).str.strip()
df_ge = df_ge[df_ge["country_code"].str.len() == 3].copy()

print(f"\nWGI Government Effectiveness final shape: {df_ge.shape}")
print(f"  Countries: {df_ge['country_code'].nunique()}")
print(f"  Years: {sorted(df_ge['year'].unique())}")
print(f"  GE estimate range: {df_ge['ge_estimate'].min():.3f} to {df_ge['ge_estimate'].max():.3f}")
print(f"  Sample:\n{df_ge.head(5).to_string()}")

df_ge.to_parquet(os.path.join(SILVER, "wgi_clean.parquet"), index=False)
print(f"\nSaved: {os.path.join(SILVER, 'wgi_clean.parquet')}")
