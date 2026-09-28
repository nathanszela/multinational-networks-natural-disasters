"""
06_clean_cepii.py
Clean CEPII GeoDist bilateral distance and colonial links database.

File: geo_cepii.xls

Kept variables: iso_o, iso_d, distw, contig, colony, comlang_off
Dropped: alternative distance measures, detailed colonial history vars

Output: data/Silver/cepii_clean.parquet
"""

import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRONZE = os.path.join(ROOT, "data", "Bronze")
SILVER = os.path.join(ROOT, "data", "Silver")
os.makedirs(SILVER, exist_ok=True)
# Use dist_cepii.xls (bilateral pairs file downloaded from CEPII)
IN_FILE  = os.path.join(BRONZE, "dist_cepii.xls")
OUT_FILE = os.path.join(SILVER, "cepii_clean.parquet")

# ── Load ───────────────────────────────────────────────────────────────────────
print("Loading CEPII dist_cepii.xls...")
# xlrd handles .xls format
df = pd.read_excel(IN_FILE, engine="xlrd")
print(f"  Raw shape: {df.shape}")
print(f"  Columns: {list(df.columns)}")

# ── Identify columns ────────────────────────────────────────────────────────────
col_map = {}
for c in df.columns:
    cl = c.lower().strip()
    if cl == "iso_o":        col_map["iso_o"] = c
    elif cl == "iso_d":      col_map["iso_d"] = c
    elif cl == "distw":      col_map["distw"] = c
    elif cl == "contig":     col_map["contig"] = c
    elif cl == "colony":     col_map["colony"] = c
    elif cl == "comlang_off": col_map["comlang_off"] = c
    elif cl == "dist":       col_map["dist"] = c          # fallback if distw absent
    elif cl == "distwces":   col_map["distwces"] = c      # secondary fallback

print(f"\nDetected columns: {col_map}")

# Fallback: if distw missing, use dist
if "distw" not in col_map and "dist" in col_map:
    col_map["distw"] = col_map.pop("dist")
    print("  Using 'dist' as fallback for 'distw'")

# ── Select and rename ──────────────────────────────────────────────────────────
keep_keys = ["iso_o", "iso_d", "distw", "contig", "colony", "comlang_off"]
keep_cols = [col_map[k] for k in keep_keys if k in col_map]
df_clean = df[keep_cols].copy()

rename = {col_map[k]: k for k in keep_keys if k in col_map}
df_clean = df_clean.rename(columns=rename)

# ── Type conversions ───────────────────────────────────────────────────────────
for col in ["distw", "contig", "colony", "comlang_off"]:
    if col in df_clean.columns:
        df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce")

# ── Remove self-pairs (iso_o == iso_d) ────────────────────────────────────────
before = len(df_clean)
df_clean = df_clean[df_clean["iso_o"] != df_clean["iso_d"]].copy()
print(f"After removing self-pairs: {before:,} -> {len(df_clean):,}")

# ── Drop rows with missing distance ────────────────────────────────────────────
before = len(df_clean)
df_clean = df_clean.dropna(subset=["distw"])
print(f"After dropping missing distw: {before:,} -> {len(df_clean):,}")

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n=== CEPII CLEAN SUMMARY ===")
print(f"Shape: {df_clean.shape}")
print(f"Origin countries (iso_o): {df_clean['iso_o'].nunique()}")
print(f"Destination countries (iso_d): {df_clean['iso_d'].nunique()}")
print(f"Distance range: {df_clean['distw'].min():.0f} - {df_clean['distw'].max():.0f} km")
if "contig" in df_clean.columns:
    print(f"Contiguous pairs: {int(df_clean['contig'].sum()):,}")
if "colony" in df_clean.columns:
    print(f"Colonial pairs: {int(df_clean['colony'].sum()):,}")
if "comlang_off" in df_clean.columns:
    print(f"Common official language pairs: {int(df_clean['comlang_off'].sum()):,}")
print(f"\nMissing values:\n{df_clean.isnull().sum()}")
print(f"\nSample:")
print(df_clean.head(5).to_string())

# ── Save ───────────────────────────────────────────────────────────────────────
df_clean.to_parquet(OUT_FILE, index=False)
print(f"\nSaved to {OUT_FILE}")
print(f"  File size: {os.path.getsize(OUT_FILE)/1024:.1f} KB")
