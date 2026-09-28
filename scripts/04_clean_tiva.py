"""
04_clean_tiva.py
Clean TiVA GVC indicators (OECD 2025 edition) — GVC Position Index.

Sources:
  EXGR_FVASH.csv    — Foreign Value Added Share in Exports (backward linkage /
                       downstreamness): COUNTERPART_AREA = W (world total)
  EXGR_INTDVASH.csv — Domestic Value added in exports of Intermediate products as
                       share of gross exports (forward linkage / upstreamness):
                       COUNTERPART_AREA = W. Industry-indexed, preferred proxy for
                       upstreamness (Koopman, Wang & Wei, 2014).

Both files use single-letter NACE/ISIC section codes (A-S) as pre-aggregated ACTIVITY rows.
Filter to single-letter codes A-S only (drops _T total rows and multi-section codes).

GVC Position Index (Koopman, Wang & Wei, 2014):
  gvc_position = ln(1 + fwd/100) - ln(1 + bwd/100)

Output: data/Silver/tiva_clean.parquet
  Columns: country (ISO-3), section (NACE/ISIC letter), year,
           gvc_fwd_int, gvc_bwd_fva, gvc_position
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
import re

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRONZE = os.path.join(ROOT, "data", "Bronze", "GVC")
SILVER = os.path.join(ROOT, "data", "Silver")
os.makedirs(SILVER, exist_ok=True)
OUT_FILE = os.path.join(SILVER, "tiva_clean.parquet")

BWD_FILE = os.path.join(BRONZE, "backwards", "EXGR_FVASH.csv")
FWD_FILE = os.path.join(BRONZE, "forward",   "EXGR_INTDVASH.csv")

VALID_SECTIONS = set("ABCDEFGHIJKLMNOPQRS")  # 19 sections (no T or U in TiVA)


def load_and_clean(filepath, value_col_name):
    """Load a TiVA CSV, filter to world total + section-level + ISO-3 countries + 2008-2019."""
    print(f"  Loading {os.path.basename(filepath)}...")
    df = pd.read_csv(filepath, low_memory=False)
    print(f"    Raw shape: {df.shape}")

    # Filter to world aggregate only
    df = df[df["COUNTERPART_AREA"] == "W"].copy()

    # Keep relevant columns
    df = df[["REF_AREA", "ACTIVITY", "TIME_PERIOD", "OBS_VALUE"]].copy()
    df.columns = ["country", "section", "year", value_col_name]
    df["year"]          = pd.to_numeric(df["year"],          errors="coerce")
    df[value_col_name]  = pd.to_numeric(df[value_col_name],  errors="coerce")

    # Filter to single-letter section codes A-S
    section_mask = df["section"].apply(
        lambda x: isinstance(x, str) and len(x.strip()) == 1 and x.strip() in VALID_SECTIONS
    )
    df = df[section_mask].copy()
    df["section"] = df["section"].str.strip()

    # Filter years 2008-2019
    df = df[(df["year"] >= 2008) & (df["year"] <= 2019)].copy()

    # Drop regional aggregates (keep 3-uppercase-letter ISO codes only)
    country_mask = df["country"].apply(
        lambda x: bool(re.match(r"^[A-Z]{3}$", str(x).strip()))
    )
    df = df[country_mask].copy()

    # Aggregate to (country, section, year) — defensive
    df = (
        df
        .groupby(["country", "section", "year"], dropna=False)[value_col_name]
        .mean()
        .reset_index()
    )
    print(f"    Final shape: {df.shape}  |  countries: {df['country'].nunique()}")
    return df


# ── Load and clean both files ──────────────────────────────────────────────────
print("Loading TiVA files...")
df_bwd = load_and_clean(BWD_FILE, "gvc_bwd_fva")
df_fwd = load_and_clean(FWD_FILE, "gvc_fwd_int")

# ── Merge on (country, section, year) ─────────────────────────────────────────
df_tiva = df_bwd.merge(df_fwd, on=["country", "section", "year"], how="outer")
print(f"\nMerged TiVA shape: {df_tiva.shape}")

# ── GVC Position Index (Koopman, Wang & Wei, 2014) ────────────────────────────
# gvc_position = ln(1 + fwd/100) - ln(1 + bwd/100)
# np.log1p is NaN-safe: NaN input → NaN output
df_tiva["gvc_position"] = (
    np.log1p(df_tiva["gvc_fwd_int"] / 100)
    - np.log1p(df_tiva["gvc_bwd_fva"] / 100)
)

# ── Validation ─────────────────────────────────────────────────────────────────
print(f"\nCountries: {df_tiva['country'].nunique()}")
print(f"Sections:  {sorted(df_tiva['section'].unique())}")
print(f"Years:     {sorted(df_tiva['year'].unique())}")
print(f"\ngvc_bwd_fva range:")
print(df_tiva["gvc_bwd_fva"].describe())
print(f"\ngvc_fwd_int range:")
print(df_tiva["gvc_fwd_int"].describe())
print(f"\ngvc_position range:")
print(df_tiva["gvc_position"].describe())
print(f"\nMissing values:")
print(df_tiva.isnull().sum())
print(f"\nSample (Germany):")
print(df_tiva[df_tiva["country"] == "DEU"].head(10).to_string())

# ── Save ───────────────────────────────────────────────────────────────────────
df_tiva.to_parquet(OUT_FILE, index=False)
print(f"\nSaved to {OUT_FILE}")
print(f"  File size: {os.path.getsize(OUT_FILE)/1024:.1f} KB")
