"""
01_clean_fats.py
Fetch and clean FATS Outward from Eurostat (two vintages).

Sources:
  FATS_OUT2     (2007-2009, NACE Rev.1.1)  -> covers 2008-2009
  FATS_OUT2_R2  (2010-2020, NACE Rev.2)    -> covers 2010-2019

Industry granularity: NACE Rev.2 section level (letters A-S + FATS aggregate codes).
  Rev.2 (keep-whitelist, NOT extract-leading-letter):
    "C"       -> "C"        (section total kept)
    "C10"     -> DROPPED    (division nested inside "C"; keeping it alongside "C"
                             would cause double-counting in pivot_table aggfunc="sum")
    "C10-C12" -> DROPPED    (sub-section aggregate)
    "B-S_X_O" -> "B-S_X_O" (macro-aggregate kept for minor-partner coverage)
  Rev.1.1: "D15" -> "C" (via crosswalk); ambiguous codes (D_E, H_J, L_M_N, R_S) -> DROPPED
  Cross-section FATS aggregate codes (B-S_X_O, G-S_X_O) are kept as-is.

Output: data/Silver/fats_clean.parquet
  Columns: year, home_country, host_country, nace_r2_section,
           variable, value, vintage
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import re
import pandas as pd
import numpy as np
import eurostat
import country_converter as coco

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = os.path.join(ROOT, "data", "Silver")
os.makedirs(SILVER, exist_ok=True)
OUT_FILE = os.path.join(SILVER, "fats_clean.parquet")

# ── NACE Rev.1.1 → NACE Rev.2 section crosswalk ────────────────────────────────
# Source: Eurostat NACE Rev.1.1 to Rev.2 official correspondence
# Rules:
#   1-to-1 mappings: straightforward recode
#   1-to-many (ambiguous): combined code, flagged as crosswalk_ambiguous=True
#
# Key: Rev.1.1 section code -> Rev.2 section code (or combined code if ambiguous)
NACE_R1_TO_R2 = {
    # Clear 1-to-1 or near-1-to-1 mappings
    "A":   ("A",   False),   # Agriculture/Forestry -> Agriculture/Forestry/Fishing
    "B":   ("A",   False),   # Fishing (merged into Rev.2 A)
    "A_B": ("A",   False),   # Agriculture + Fishing combined -> Rev.2 A
    "C":   ("B",   False),   # Mining & Quarrying
    "D":   ("C",   False),   # Manufacturing (main 1-to-1)
    "F":   ("F",   False),   # Construction
    "G":   ("G",   False),   # Wholesale and retail trade
    "H":   ("I",   False),   # Hotels & restaurants -> Accommodation & food services
    "J":   ("K",   False),   # Financial intermediation -> Financial & insurance
    "L":   ("O",   False),   # Public administration
    "M":   ("P",   False),   # Education
    "N":   ("Q",   False),   # Health and social work
    "P":   ("T",   False),   # Private households
    "Q":   ("U",   False),   # International organizations
    # Ambiguous 1-to-many mappings (FLAGGED)
    "E":   ("D_E", True),    # Electricity+Water -> Rev.2 D (Electricity) + E (Water) SPLIT
    "I":   ("H_J", True),    # Transport+Comm -> Rev.2 H (Transport) + J (ICT) SPLIT
    "K":   ("L_M_N", True),  # Real estate+Business -> Rev.2 L + M + N SPLIT
    "O":   ("R_S", True),    # Other community -> Rev.2 R (Arts) + S (Other) SPLIT
    # FATS-specific aggregate codes (Rev.1.1) — normalised to Rev.2 dash notation
    "C-O_X_L": ("B-S_X_O", False),  # Total excl. public admin -> Rev.2 B-S_X_O
    "A-O_X_L": (None,       False),  # No clean Rev.2 equivalent -> drop
    "G-O_X_L": ("G-S_X_O", False),  # Services excl. public admin -> Rev.2 G-S_X_O
}

# ── EU + EFTA countries in Eurostat ISO-2 format ─────────────────────────────
# NOTE: Eurostat uses 'EL' for Greece and 'UK' for United Kingdom (not GR/GB).
# Using GR or GB causes Faultcode 150 (invalid geo code).
EU_EFTA_GEO = [
    "AT","BE","BG","CY","CZ","DE","DK","EE",
    "EL",          # Greece (Eurostat code, NOT GR)
    "ES","FI","FR","HR","HU","IE","IT",
    "LT","LU","LV","MT","NL","PL","PT","RO",
    "SE","SI","SK",
    "UK",          # United Kingdom (Eurostat code, NOT GB)
    "IS","LI","NO","CH",
]

# ── European region of home country (for heterogeneity analysis) ──────────────
# Source: UN geoscheme + conventional European sub-region groupings.
# Covers all 29 FATS reporters (IS/LI/CH return no data but are included for safety).
HOME_REGION_MAP = {
    # Western Europe
    "AUT": "W. Europe", "BEL": "W. Europe", "CHE": "W. Europe",
    "DEU": "W. Europe", "FRA": "W. Europe", "LUX": "W. Europe",
    "NLD": "W. Europe",
    # Northern Europe
    "DNK": "N. Europe", "EST": "N. Europe", "FIN": "N. Europe",
    "GBR": "N. Europe", "IRL": "N. Europe", "ISL": "N. Europe",
    "LTU": "N. Europe", "LVA": "N. Europe", "NOR": "N. Europe",
    "SWE": "N. Europe",
    # Southern Europe
    "CYP": "S. Europe", "ESP": "S. Europe", "GRC": "S. Europe",
    "HRV": "S. Europe", "ITA": "S. Europe", "MLT": "S. Europe",
    "PRT": "S. Europe", "SVN": "S. Europe",
    # Eastern Europe
    "BGR": "E. Europe", "CZE": "E. Europe", "HUN": "E. Europe",
    "LIE": "W. Europe",  # Liechtenstein — Western European microstate
    "POL": "E. Europe", "ROU": "E. Europe", "SVK": "E. Europe",
}

# ── ISO conversion helpers ────────────────────────────────────────────────────
# Manual overrides for codes country_converter cannot resolve
MANUAL_OVERRIDES = {
    "CN_X_HK": "CHN",   # China excl. Hong Kong (Eurostat FATS partner code)
    "EL":      "GRC",   # Eurostat Greece
    "UK":      "GBR",   # Eurostat United Kingdom
}
_cc = coco.CountryConverter()

def _batch_to_iso3(series):
    """Convert a Series of country codes to ISO-3 in one batch (fast).
    Applies manual overrides first, then passes remaining unique codes to
    country_converter in a single call instead of row-by-row.
    """
    unique_codes = series.unique().tolist()
    mapping = {}
    to_coco = []
    for code in unique_codes:
        s = str(code).strip()
        if s in MANUAL_OVERRIDES:
            mapping[code] = MANUAL_OVERRIDES[s]
        else:
            to_coco.append(code)
    if to_coco:
        _SENTINEL = "__NOT_FOUND__"
        converted = _cc.convert(to_coco, to="ISO3", not_found=_SENTINEL)
        if isinstance(converted, str):
            converted = [converted]
        for code, iso3 in zip(to_coco, converted):
            # Fall back to original code for regional aggregates (EU28, WORLD, etc.)
            mapping[code] = str(code) if iso3 == _SENTINEL else iso3
    return series.map(mapping)

# ── Helper: fetch one country from one dataset and melt to long ───────────────
def fetch_and_melt(dataset, geo, nace_col_name="nace_r2", year_range=None):
    """Download one geo from dataset; return long-format DataFrame."""
    try:
        df = eurostat.get_data_df(dataset, filter_pars={"geo": geo})
    except Exception as e:
        print(f"    ERROR {geo}: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Rename home country column
    home_col = [c for c in df.columns if "TIME_PERIOD" in str(c) or c == "geo"][0]
    df = df.rename(columns={home_col: "home_country"})

    # Identify year columns
    year_cols = [c for c in df.columns if str(c).isdigit()]

    # Melt wide -> long
    id_vars = [c for c in df.columns if c not in year_cols]
    df = df.melt(id_vars=id_vars, value_vars=year_cols, var_name="year", value_name="value")
    df["year"] = df["year"].astype("int16")

    # Filter years
    if year_range:
        df = df[(df["year"] >= year_range[0]) & (df["year"] <= year_range[1])].copy()

    # Rename nace column uniformly to 'nace_raw'
    if nace_col_name in df.columns:
        df = df.rename(columns={nace_col_name: "nace_raw"})
    elif "nace_r1" in df.columns:
        df = df.rename(columns={"nace_r1": "nace_raw"})

    # Drop always-constant columns
    df = df.drop(columns=["freq"], errors="ignore")

    return df


# ── Normalise NACE codes to Rev.2 section letters ─────────────────────────────
def normalise_nace(df, vintage):
    """
    Filter raw NACE codes to top-level Rev.2 section letters only.

    Rev.2 data (keep-whitelist logic — NOT extract-leading-letter):
      "C"       -> nace_r2_section = "C"        (section total, kept)
      "C10"     -> DROPPED  (division code; already included in "C" total)
      "C10-C12" -> DROPPED  (sub-section aggregate)
      "B-S_X_O" -> nace_r2_section = "B-S_X_O"  (macro-aggregate, kept)

    Rev.1.1 data (mapped via NACE_R1_TO_R2 crosswalk):
      "D15"  -> "C"   (1-to-1: Rev.1.1 D = Manufacturing -> Rev.2 C)
      "E12"  -> "D_E" (ambiguous: Rev.1.1 E splits into Rev.2 D + E, flagged)
      "D"    -> "C"   (section letter handled directly via crosswalk)

    Output column: nace_r2_section
    """
    if vintage == "r2":
        df = df.copy()
        def extract_section_r2(code):
            code = str(code).strip()
            # Keep ONLY pure single-letter section codes (A–U = full NACE Rev.2 range).
            # Division codes like "C10", "D35" are intentionally NOT collapsed to their
            # parent letter here — Eurostat returns both the section total ("C") AND its
            # constituent divisions ("C10", "C13", …) in the same API response.
            # Mapping divisions → "C" would cause aggfunc="sum" in the pivot to double-
            # count those values (they are already included in the section total).
            if re.match(r'^[A-U]$', code):
                return code, False
            # Keep whitelisted macro-aggregates needed for minor-partner host countries
            # where section-level data is suppressed by Eurostat.
            if code in {"B-S_X_O", "G-S_X_O"}:
                return code, False
            # Drop everything else: division codes (C10, D35), sub-section aggregates
            # (C10-C12), non-standard codes (NAL, C_MET, H_X_H53), etc.
            return None, False

        results = [extract_section_r2(c) for c in df["nace_raw"]]
        df["nace_r2_section"], df["crosswalk_ambiguous"] = zip(*results)

    else:  # Rev.1.1
        df = df.copy()
        def extract_section_r1(code):
            code = str(code).strip()
            # Division code: section letter + 2 digits (e.g. "D15")
            m = re.match(r'^([A-Q])(\d{2})$', code)
            if m:
                r1_section = m.group(1)
                if r1_section in NACE_R1_TO_R2:
                    r2_section, ambiguous = NACE_R1_TO_R2[r1_section]
                    return r2_section, ambiguous
                return None, False
            # Section letter or aggregate code directly in crosswalk (e.g. "D", "C-O_X_L")
            if code in NACE_R1_TO_R2:
                r2_section, ambiguous = NACE_R1_TO_R2[code]
                return r2_section, ambiguous
            return None, False

        results = [extract_section_r1(c) for c in df["nace_raw"]]
        df["nace_r2_section"], df["crosswalk_ambiguous"] = zip(*results)

    return df


# ── Main download loop ─────────────────────────────────────────────────────────
print("=== FATS DOWNLOAD ===")
print()

all_frames = []
unknown_nace_r1 = set()

# --- PART A: FATS_OUT2_R2 (2010-2019, NACE Rev.2) ---
print("Part A: FATS_OUT2_R2 (2010-2019, NACE Rev.2)")
for geo in EU_EFTA_GEO:
    df_g = fetch_and_melt("FATS_OUT2_R2", geo, nace_col_name="nace_r2", year_range=(2010, 2019))
    if not df_g.empty:
        df_g["vintage"] = "r2"
        all_frames.append(df_g)
        print(f"  {geo}: {len(df_g):,} rows")
    else:
        print(f"  {geo}: no data")

# --- PART B: FATS_OUT2 (2008-2009, NACE Rev.1.1) ---
print("\nPart B: FATS_OUT2 (2008-2009, NACE Rev.1.1)")
for geo in EU_EFTA_GEO:
    df_g = fetch_and_melt("FATS_OUT2", geo, nace_col_name="nace_r1", year_range=(2008, 2009))
    if not df_g.empty:
        df_g["vintage"] = "r1"
        all_frames.append(df_g)
        print(f"  {geo}: {len(df_g):,} rows")
    else:
        print(f"  {geo}: no data")

if not all_frames:
    print("ERROR: No data retrieved. Check API connection.")
    sys.exit(1)

df_raw = pd.concat(all_frames, ignore_index=True)
print(f"\nCombined raw: {df_raw.shape}")

# ── Normalise NACE codes ───────────────────────────────────────────────────────
r2_mask = df_raw["vintage"] == "r2"
r1_mask = df_raw["vintage"] == "r1"

df_r2 = normalise_nace(df_raw[r2_mask].copy(), "r2")
df_r1 = normalise_nace(df_raw[r1_mask].copy(), "r1")
df_norm = pd.concat([df_r2, df_r1], ignore_index=True)

# ── Drop ambiguous crosswalk rows ─────────────────────────────────────────────
# Ambiguous codes (D_E, H_J, L_M_N, R_S) come from 2008-2009 Rev.1.1 data where
# one Rev.1.1 section splits into multiple Rev.2 sections. Since we cannot assign
# a single clean section letter, these rows are dropped. This affects sectors E,
# H/I, K, and O only for years 2008-2009.
ambig_mask = df_norm["crosswalk_ambiguous"].fillna(False).astype(bool)
n_total_before_ambig_drop = len(df_norm[df_norm["nace_r2_section"].notna()])
n_ambig = ambig_mask.sum()
ambig_pct = 100 * n_ambig / len(df_norm) if len(df_norm) > 0 else 0
print(f"\nINFO: Dropping {n_ambig:,} ambiguous Rev.1.1 crosswalk rows "
      f"({ambig_pct:.1f}% of all raw rows; codes: D_E, H_J, L_M_N, R_S). "
      f"Thesis limitation: sectors D/E, H/J, L/M/N, R/S excluded for 2008-2009.")
df_norm = df_norm[~ambig_mask].copy()

# ── Keep only rows with a resolved section code ────────────────────────────────
before = len(df_norm)
df_norm = df_norm[df_norm["nace_r2_section"].notna()].copy()
print(f"After section filter: {before:,} -> {len(df_norm):,} rows")
print(f"Sections/aggregates covered: {sorted(df_norm['nace_r2_section'].unique())}")

# ── Filter variables ───────────────────────────────────────────────────────────
VARS_KEEP = {"ENT", "EMP", "TUR"}
before = len(df_norm)
df_norm = df_norm[df_norm["indic_bp"].isin(VARS_KEEP)].copy()
print(f"After variable filter (ENT/EMP/TUR): {before:,} -> {len(df_norm):,} rows")

# ── Final renames ──────────────────────────────────────────────────────────────
df_norm = df_norm.rename(columns={
    "indic_bp":    "variable",
    "partner":     "host_country",
    "home_country":"home_country",
})

# Drop the raw NACE column; keep section code and metadata
df_final = df_norm[[
    "year", "home_country", "host_country",
    "nace_r2_section", "variable", "value",
    "vintage"
]].copy()
# NOTE: home_region is added after ISO-3 conversion below

# ── Convert Eurostat ISO-2 codes to ISO-3 ─────────────────────────────────────
print("\nConverting country codes to ISO-3...")
df_final["home_country"] = _batch_to_iso3(df_final["home_country"])
df_final["host_country"] = _batch_to_iso3(df_final["host_country"])

# Validate: home countries should all be ISO-3 after the fix
home_unresolved = sorted([
    c for c in df_final["home_country"].unique()
    if not (len(str(c)) == 3 and str(c).isalpha() and str(c).isupper())
])
host_unresolved = sorted([
    c for c in df_final["host_country"].unique()
    if not (len(str(c)) == 3 and str(c).isalpha() and str(c).isupper())
])
if home_unresolved:
    print(f"  WARNING — Unresolved home codes: {home_unresolved}")
else:
    print("  All home country codes resolved to ISO-3.")
if host_unresolved:
    print(f"  Non-ISO3 host codes (regional aggregates etc., first 20): {host_unresolved[:20]}")
assert "EL" not in df_final["home_country"].unique(), "EL not converted to GRC"
assert "UK" not in df_final["home_country"].unique(), "UK not converted to GBR"

# ── Assign European home region ────────────────────────────────────────────────
df_final["home_region"] = df_final["home_country"].map(HOME_REGION_MAP)
unmapped_home = sorted(df_final.loc[df_final["home_region"].isna(), "home_country"].unique())
if unmapped_home:
    print(f"  WARNING — home countries not in HOME_REGION_MAP: {unmapped_home}")
else:
    print("  All home countries assigned a region.")

# ── Drop geographic aggregates and non-country host entities ──────────────────
# These are Eurostat statistical zones (EU28, WORLD, EXT_*, AFR…) and dissolved
# territories (AN). They lack GDP/GE controls and do not experience single-point
# natural disaster shocks; they are unusable in regression.
# NOTE: Run validate_fats_world.ipynb BEFORE re-running this script if you want
# the WORLD suppression-gap analysis — it requires WORLD rows to still be present.
GEO_AGGREGATES = {
    "WORLD",
    "EU25", "EU27_2007", "EU27_2020", "EU28", "EA13",
    "EXT_EU25", "EXT_EU27_2007", "EXT_EU27_2020", "EXT_EU28",
    "EXT_EU_NAL", "EXT_EA13",
    "OFFSHO",
    "AFR", "AME", "ASI", "EUR", "OCE_PLR",
    "AN",   # Netherlands Antilles (dissolved 2010)
}
before_geo = len(df_final)
df_final = df_final[~df_final["host_country"].isin(GEO_AGGREGATES)].copy()
n_dropped_geo = before_geo - len(df_final)
print(f"\nDropped {n_dropped_geo:,} rows with aggregate/non-country host codes "
      f"({n_dropped_geo / before_geo * 100:.1f}% of pre-drop rows)")
print(f"Remaining host countries: {df_final['host_country'].nunique()}")

# ── Summary ────────────────────────────────────────────────────────────────────
print("\n=== FATS CLEAN SUMMARY ===")
print(f"Shape: {df_final.shape}")
print(f"\nYear range: {df_final['year'].min()} - {df_final['year'].max()}")
print(f"\nHome countries ({df_final['home_country'].nunique()}): {sorted(df_final['home_country'].unique())}")
print(f"\nHome region distribution (row counts):")
print(df_final["home_region"].value_counts().sort_index().to_string())
print(f"\nHost countries: {df_final['host_country'].nunique()}")
print(f"\nNACE sections/aggregates ({df_final['nace_r2_section'].nunique()}):")
print(df_final["nace_r2_section"].value_counts().head(30).to_string())
print(f"\nVariables:")
print(df_final["variable"].value_counts().to_string())
print(f"\nVintage counts:")
print(df_final["vintage"].value_counts().to_string())
print(f"\nMissing values:")
print(df_final.isnull().sum())
print(f"\nSample:")
print(df_final.head(5).to_string())

# ── Save ───────────────────────────────────────────────────────────────────────
df_final.to_parquet(OUT_FILE, index=False)
print(f"\nSaved to {OUT_FILE}")
print(f"  File size: {os.path.getsize(OUT_FILE)/1024:.1f} KB")
