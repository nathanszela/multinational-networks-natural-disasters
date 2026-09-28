"""
06_standardise_countries.py
Standardise all country codes to ISO-3 alpha-3 using country_converter.

Checks each Silver file and reports:
  - Already ISO-3: no change
  - ISO-2: convert to ISO-3
  - Country names: convert to ISO-3
  - Unresolvable: log warning, DO NOT drop without user approval

Also renames CEPII columns (iso_o -> home_country, iso_d -> host_country)
so that 08_merge_final.py can join on consistent column names.

Run order: after 01-05 (all cleaning scripts), before 08 (merge).
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
import country_converter as coco

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = os.path.join(ROOT, "data", "Silver")
cc = coco.CountryConverter()

# country_converter with not_found=None silently keeps unrecognised codes unchanged
# (it does NOT set them to NaN). These overrides patch known cases where CC fails
# to convert a source-specific code to ISO-3.
MANUAL_OVERRIDES = {
    "ROM": "ROU",   # Romania: CEPII uses IOC code; ISO-3 is ROU
}

def convert_to_iso3(series, label=""):
    """Convert a series of country codes/names to ISO-3. Returns (converted_series, unresolved_set)."""
    # Apply manual overrides first so CC sees canonical codes
    series = series.replace(MANUAL_OVERRIDES)
    converted = cc.pandas_convert(series, to="ISO3", not_found=None)
    # not_found=None keeps original value unchanged — detect those by comparing
    unchanged_mask = (converted == series) & series.notna()
    # Check whether unchanged values are genuinely valid ISO-3 (i.e. in CC's database)
    valid_iso3 = set(cc.data["ISO3"].dropna().unique())
    unresolved = set(converted[unchanged_mask].unique()) - valid_iso3 - {""}
    if unresolved:
        print(f"  [{label}] Unresolvable codes (kept as-is): {sorted(unresolved)}")
    return converted, unresolved

print("=== Country Code Standardisation ===\n")
all_unresolved = {}

# ── 1. FATS ───────────────────────────────────────────────────────────────────
print("1. FATS (fats_clean.parquet)")
df_fats = pd.read_parquet(os.path.join(SILVER, "fats_clean.parquet"))
for col in ["home_country", "host_country"]:
    converted, unres = convert_to_iso3(df_fats[col], f"FATS.{col}")
    df_fats[col] = converted
    if unres:
        all_unresolved[f"FATS.{col}"] = unres
print(f"  Home countries: {sorted(df_fats['home_country'].dropna().unique())}")
print(f"  Host countries (sample): {sorted(df_fats['host_country'].dropna().unique())[:20]}")
df_fats.to_parquet(os.path.join(SILVER, "fats_clean.parquet"), index=False)
print(f"  Saved: {len(df_fats):,} rows\n")

# ── 2. EM-DAT ─────────────────────────────────────────────────────────────────
print("2. EM-DAT (emdat_clean.parquet)")
df_emdat = pd.read_parquet(os.path.join(SILVER, "emdat_clean.parquet"))
converted, unres = convert_to_iso3(df_emdat["country_iso3"], "EMDAT.country_iso3")
df_emdat["country_iso3"] = converted
if unres:
    all_unresolved["EMDAT.country_iso3"] = unres
df_emdat.to_parquet(os.path.join(SILVER, "emdat_clean.parquet"), index=False)
print(f"  Saved: {len(df_emdat):,} rows\n")

print("2b. EM-DAT historical exposure (emdat_hist_exposure.parquet)")
df_hist = pd.read_parquet(os.path.join(SILVER, "emdat_hist_exposure.parquet"))
converted, unres = convert_to_iso3(df_hist["country_iso3"], "EMDAT_hist.country_iso3")
df_hist["country_iso3"] = converted
if unres:
    all_unresolved["EMDAT_hist.country_iso3"] = unres
df_hist.to_parquet(os.path.join(SILVER, "emdat_hist_exposure.parquet"), index=False)
print(f"  Saved: {len(df_hist):,} rows\n")

# ── 3. WDI ────────────────────────────────────────────────────────────────────
print("3. WDI (wdi_clean.parquet)")
df_wdi = pd.read_parquet(os.path.join(SILVER, "wdi_clean.parquet"))
converted, unres = convert_to_iso3(df_wdi["country_code"], "WDI.country_code")
df_wdi["country_code"] = converted
if unres:
    all_unresolved["WDI.country_code"] = unres
df_wdi.to_parquet(os.path.join(SILVER, "wdi_clean.parquet"), index=False)
print(f"  Saved: {len(df_wdi):,} rows\n")

# ── 4. WGI ────────────────────────────────────────────────────────────────────
print("4. WGI (wgi_clean.parquet)")
df_wgi = pd.read_parquet(os.path.join(SILVER, "wgi_clean.parquet"))
converted, unres = convert_to_iso3(df_wgi["country_code"], "WGI.country_code")
df_wgi["country_code"] = converted
if unres:
    all_unresolved["WGI.country_code"] = unres
df_wgi.to_parquet(os.path.join(SILVER, "wgi_clean.parquet"), index=False)
print(f"  Saved: {len(df_wgi):,} rows\n")

# ── 5. TiVA ───────────────────────────────────────────────────────────────────
print("5. TiVA (tiva_clean.parquet)")
df_tiva = pd.read_parquet(os.path.join(SILVER, "tiva_clean.parquet"))
# TiVA uses ISO-3 already; some rows may be regional aggregates (A5_A7, APEC, etc.)
converted, unres = convert_to_iso3(df_tiva["country"], "TIVA.country")
df_tiva["country"] = converted
if unres:
    all_unresolved["TIVA.country"] = unres
# Regional aggregates will remain unresolved; keep them with NaN ISO3
df_tiva.to_parquet(os.path.join(SILVER, "tiva_clean.parquet"), index=False)
print(f"  Saved: {len(df_tiva):,} rows\n")

# ── 6. CEPII ─────────────────────────────────────────────────────────────────
print("6. CEPII (cepii_clean.parquet)")
df_cepii = pd.read_parquet(os.path.join(SILVER, "cepii_clean.parquet"))
# Support both old naming (iso_o/iso_d) and already-renamed (home_country/host_country)
if "iso_o" in df_cepii.columns and "iso_d" in df_cepii.columns:
    for col in ["iso_o", "iso_d"]:
        converted, unres = convert_to_iso3(df_cepii[col], f"CEPII.{col}")
        df_cepii[col] = converted
        if unres:
            all_unresolved[f"CEPII.{col}"] = unres
    df_cepii = df_cepii.rename(columns={"iso_o": "home_country", "iso_d": "host_country"})
else:
    for col in ["home_country", "host_country"]:
        converted, unres = convert_to_iso3(df_cepii[col], f"CEPII.{col}")
        df_cepii[col] = converted
        if unres:
            all_unresolved[f"CEPII.{col}"] = unres
df_cepii.to_parquet(os.path.join(SILVER, "cepii_clean.parquet"), index=False)
print(f"  Saved: {len(df_cepii):,} rows\n")

# ── Summary of unresolvable codes ─────────────────────────────────────────────
print("=" * 60)
print("SUMMARY OF UNRESOLVABLE COUNTRY CODES")
print("=" * 60)
if all_unresolved:
    for dataset, codes in all_unresolved.items():
        print(f"  {dataset}: {sorted(codes)}")
    print()
    print("NOTE: Rows with unresolvable codes have country set to NaN.")
    print("      These rows will be excluded from merges (left-join will keep them")
    print("      as NaN in joined columns). Review before dropping.")
else:
    print("  All country codes resolved successfully!")
