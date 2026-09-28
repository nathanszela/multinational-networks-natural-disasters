# Data pipeline: detailed documentation

> This document describes every step of the pipeline, from raw sources to the estimation samples, with the reasoning behind each data-handling choice. It was maintained during the project as a working reference. Hypotheses H1/H2/H3 in this file correspond to research questions RQ1/RQ2/RQ3 in the final thesis. Notebook and file names below are the original working names; see the mapping table in the main README.

---

## Table of Contents

1. [Project Identity](#1-project-identity)
2. [Pipeline Overview](#2-pipeline-overview)
3. [Script-by-Script Walkthrough](#3-script-by-script-walkthrough)
   - [01 — Clean FATS](#01_clean_fatspy)
   - [02 — Clean EM-DAT](#02_clean_emdatpy)
   - [03 — Clean WDI / WGI](#03_clean_wdi_wgipy)
   - [04 — Clean TiVA](#04_clean_tivapy)
   - [05 — Clean CEPII](#05_clean_cepiipy)
   - [06 — Standardise Countries](#06_standardise_countriespy)
   - [07 — Merge](#07_mergepy)
   - [08 — Create Estimation Sample](#08_create_estimation_samplepy)
4. [Specific Data Handling Rules — The "Why"](#4-specific-data-handling-rules--the-why)
5. [Schema & Variables Dictionary](#5-schema--variables-dictionary)
6. [Known Pitfalls for Future Analysis](#6-known-pitfalls-for-future-analysis)
7. [Retired Scripts](#7-retired-scripts)

---

## 1. Project Identity

### Research Question
How do natural disasters in host countries affect the affiliate activity of Multinational Enterprises (MNEs) headquartered in European countries? The focus is on **resilience**: do MNEs retract, maintain, or expand operations after disaster shocks, and does the effect vary by industry, disaster type, or firm origin?

### Data Architecture
- **Primary source**: Eurostat FATS Outward (Foreign Affiliates Statistics). **OECD AMNE has been fully dropped** and all scripts referencing it have been deleted.
- **Coverage**: 29 home countries (EU-27 + GBR + NOR), approximately 210 host countries, NACE Rev.2 industry sections A–S plus aggregate codes, panel years **2008–2019**.
- **Unit of observation**: `(year, home_country, host_country, industry)` — a dyadic affiliate relationship at the industry level.
- **Dependent variables**: `ent` (number of affiliates), `emp` (employees in affiliates), `tur` (turnover of affiliates).

### Analytical Strategies (dual-strategy structure)
Both strategies are preserved in `estimation_sample.parquet`; the analyst selects one at regression time:

| Strategy | Filter | Description | GVC available? |
|---|---|---|---|
| **A** | `industry == "B-S_X_O"` | Total manufacturing aggregate; maximum host-country coverage (73 partners) | No |
| **B** | `nace_section.notna()` | Section-letter NACE rows (A–S); narrower coverage but GVC data available | Yes |

### Home Countries (29 reporters)
`AUT, BEL, BGR, CYP, CZE, DEU, DNK, ESP, EST, FIN, FRA, GBR, GRC, HRV, HUN, IRL, ITA, LTU, LUX, LVA, MLT, NLD, NOR, POL, PRT, ROU, SVK, SVN, SWE`

Note: IS (Iceland), LI (Liechtenstein), CH (Switzerland) are queried but return no FATS data.

### European Sub-regions (for heterogeneity analysis)
- **W. Europe**: AUT, BEL, CHE, DEU, FRA, LIE, LUX, NLD
- **N. Europe**: DNK, EST, FIN, GBR, IRL, ISL, LTU, LVA, NOR, SWE
- **S. Europe**: CYP, ESP, GRC, HRV, ITA, MLT, PRT, SVN
- **E. Europe**: BGR, CZE, HUN, POL, ROU, SVK

---

## 2. Pipeline Overview

### Run Order
```
01  →  02 + 03 + 04 + 05 (parallel)  →  06  →  07  →  08
                                                     ↘  09 (extensive margin, independent of 08)
10 (geo_static) can run alongside 01-05; 06 does not process it (10 handles its own ISO-3 conversion)
```

Scripts 02–05 are independent and can run simultaneously. **06 must complete before 07** because it renames CEPII columns (`iso_o → home_country`, `iso_d → host_country`) that the merge joins depend on. `07_merge.py` contains a defensive fallback for both old and new naming. **09 is independent of 08** — both read from `panel_final.parquet` and Silver files directly.

### Output Files (Silver layer)

| Script | Output File | Key | Shape |
|---|---|---|---|
| 01 | `fats_clean.parquet` | year, home, host, nace_r2_section, variable | ~2.7M rows × 7 cols |
| 02a | `emdat_clean.parquet` | country_iso3, year | ~1,388 × 19 |
| 02b | `emdat_hist_exposure.parquet` | country_iso3, year | ~2,624 × 12 |
| 03 | `wdi_clean.parquet` | country_code, year | ~3,458 rows |
| 03 | `wgi_clean.parquet` | country_code, year | ~2,536 rows |
| 04 | `tiva_clean.parquet` | country, section, year | ~81 countries × 19 sections × 12 years |
| 05 | `cepii_clean.parquet` | iso_o, iso_d | ~47,742 bilateral pairs |
| 06 | *(re-saves all above in-place with ISO-3 codes + CEPII rename)* | — | — |
| 07 | `panel_final.parquet` | year, home, host, industry | ~57 columns |
| 08 | `estimation_sample.parquet` | year, home, host, industry | subset of panel_final (intensive margin) |
| 09 | `estimation_sample_extensive.parquet` | year, home, host, industry | Cartesian × B-S_X_O (extensive margin) |
| 10 | `geo_static.parquet` | country_code | country_code, surface_area_km2, landlocked (216 countries) |

### Bronze Data Sources

| Dataset | Location | Format |
|---|---|---|
| FATS Outward | Eurostat API (live download) | API → in-memory |
| EM-DAT disasters | `data/Bronze/Natural disasters/disasters_from_1988.xlsx` | Excel |
| WDI GDP | `data/Bronze/worldbank/country gdp/API_NY.GDP.MKTP.KD_DS2_en_csv_v2_374654.csv` | World Bank CSV (skiprows=4) — NY.GDP.MKTP.KD, constant 2015 USD |
| WDI Population | `data/Bronze/worldbank/country population size/population_size.csv` | World Bank CSV (skiprows=4) |
| WGI | `data/Bronze/worldbank/wgidataset_with_sourcedata-2025.xlsx` | Excel (multi-sheet) |
| TiVA backward | `data/Bronze/GVC/backwards/EXGR_FVASH.csv` | OECD CSV |
| TiVA forward | `data/Bronze/GVC/forward/EXGR_INTDVASH.csv` | OECD CSV |
| CEPII distances | `data/Bronze/dist_cepii.xls` | Excel (bilateral) |

---

## 3. Script-by-Script Walkthrough

---

### `01_clean_fats.py`

**Purpose**: Fetch FATS Outward data from the Eurostat API and produce a clean long-format parquet with NACE Rev.2 section codes.

#### Dual-Vintage API Fetch
Eurostat changed NACE classification mid-panel:
- `FATS_OUT2_R2`: 2010–2019, NACE **Rev.2**
- `FATS_OUT2`: 2008–2009, NACE **Rev.1.1**

Both are fetched for each of the 29 home countries via `eurostat.get_data_df()`. Each country-dataset combination is melted from wide (year columns) to long format. The `vintage` column (`"r2"` or `"r1"`) is attached for downstream normalisation.

#### NACE Rev.2 Keep-Whitelist Logic (NOT extract-leading-letter)
The Eurostat API returns both the **section total** (e.g. `"C"`) and its **constituent division codes** (e.g. `"C10"`, `"C13"`, `"C10-C12"`) in the same response. A naive approach of extracting the leading letter would map `"C10" → "C"`, then `aggfunc="sum"` in the pivot would add `C10` to `C`, double-counting.

The correct approach is a **keep-whitelist**:
- Keep: single-letter codes matching `^[A-U]$` — these are NACE section totals.
- Keep: `"B-S_X_O"` and `"G-S_X_O"` — FATS aggregate codes kept for minor-partner host countries where section-level data is suppressed by Eurostat.
- **Drop everything else**: division codes (`C10`, `D35`), sub-section aggregates (`C10-C12`), non-standard codes (`NAL`, `H_X_H53`).

```python
# From 01_clean_fats.py — extract_section_r2()
if re.match(r'^[A-U]$', code):
    return code, False
if code in {"B-S_X_O", "G-S_X_O"}:
    return code, False
return None, False  # drop all else
```

#### NACE Rev.1.1 → Rev.2 Crosswalk (2008–2009 only)
The `NACE_R1_TO_R2` dictionary maps Rev.1.1 section/division codes to Rev.2 section letters:

| Rev.1.1 | Rev.2 | Ambiguous? | Note |
|---|---|---|---|
| `D` / `D15` | `C` | No | Manufacturing: 1-to-1 |
| `J` | `K` | No | Financial intermediation |
| `L` | `O` | No | Public administration |
| `E` | `D_E` | **Yes** | Electricity+Water splits into D+E |
| `I` | `H_J` | **Yes** | Transport+Comm splits into H+J |
| `K` | `L_M_N` | **Yes** | Business services splits into L+M+N |
| `O` | `R_S` | **Yes** | Other community splits into R+S |
| `C-O_X_L` | `B-S_X_O` | No | Aggregate crosswalk |

Ambiguous rows (`crosswalk_ambiguous=True`) are **dropped** — a single Rev.1.1 section cannot be cleanly assigned to one Rev.2 section. This is a **thesis limitation**: sectors D/E, H/J, L/M/N, R/S are excluded for years 2008–2009 (~0.8% of all raw rows).

#### Country Code Conversion
Eurostat uses non-standard ISO-2 codes. Manual overrides are applied first, then `country_converter` handles the rest:

```python
MANUAL_OVERRIDES = {
    "CN_X_HK": "CHN",   # China excl. Hong Kong — not in standard ISO
    "EL":      "GRC",   # Eurostat code for Greece (standard is GR → GRC)
    "UK":      "GBR",   # Eurostat code for UK (standard is GB → GBR)
}
```

Using `"GR"` or `"GB"` in the API call causes Eurostat `Faultcode 150` (invalid geo code).

Regional aggregates that cannot be resolved (e.g. `EU28`, `WORLD`, `AFR`) are retained as-is in `fats_clean.parquet` and filtered out in Layer 0 of `07_merge.py`.

#### Variable Filter
Only `ENT` (number of affiliates), `EMP` (employees), `TUR` (turnover) are kept from the `indic_bp` column. All other FATS indicators are dropped.

#### Output Schema
`year (int16), home_country (ISO-3), host_country (ISO-3 or aggregate), nace_r2_section (str), variable (ENT/EMP/TUR), value (float), vintage (r1/r2), home_region (str)`

---

### `02_clean_emdat.py`

**Purpose**: Clean the EM-DAT natural disasters database into two output files: a panel of disaster shocks (2008–2019) and a historical exposure dataset.

#### Input
`data/Bronze/Natural disasters/disasters_from_1988.xlsx` — all EM-DAT events from 1988 onward. Column names are detected dynamically via pattern matching (EM-DAT column names vary across dataset versions).

#### 100-Person Proxy for Missing `Total Affected`
```python
df_filtered["total_affected_filled"] = df_filtered["total_affected"].fillna(100)
```
EM-DAT's entry criteria guarantee that each recorded event affected ≥100 people. Therefore, when `Total Affected` is not reported, 100 is a **conservative lower-bound proxy** — it is never an overestimate, and it avoids assigning zero severity to events that did occur. This proxy is used consistently in **both** the panel severity columns and the historical exposure columns.

A binary flag `missing_affected` (0/1) is also created to track how many events per country-year had missing affected counts. This is exported as `total_missing_affected` (an auxiliary diagnostic column, not used in regressions).

#### 13 Disaster Types
The `TYPE_MAP` dictionary maps EM-DAT "Disaster Type" labels to clean column suffixes. The 13 recognised types are:

`earthquake, volcanic_activity, mass_movement_dry, mass_movement_wet, impact, flood, storm, wildfire, drought, extreme_temperature, animal_incident, epidemic, infestation`

Events with unmapped disaster types are silently excluded from counts and severity (a warning is printed).

#### Multi-Year Events
Events spanning multiple years are kept and assigned to `start_year`. No special handling is applied — the event contributes its full `Total Affected` count to the year it began.

#### Three Grouped Severity Columns
Severity is defined as the **log of per-capita affected** within a disaster group:

```
sev_group = ln(1 + sum(total_affected_filled for events in group) / pop_panel_year)
```

The three groups and their constituent disaster types:

| Column | Disaster Types | Rationale |
|---|---|---|
| `sev_sudden_physical` | Earthquake, Volcanic activity, Mass movement (dry/wet), Impact | Geophysical — sudden onset, physically destructive |
| `sev_seasonal_physical` | Flood, Storm, Wildfire | Hydro-meteorological — recurrent, seasonal pattern |
| `sev_climatic_slow` | Drought, Extreme temperature | Slow-onset climatic — affects agriculture and heat stress |

Population denominator: WDI country-year population (`population_size.csv`). A severity value is `NaN` if the country is absent from the WDI population table (not a data error — simply no denominator available).

The three severity frames are merged with `how="outer"` to ensure any country-year with events in at least one group appears in the output. After the outer merge, remaining NaN severity values (from groups with no events in that country-year) are filled to 0.0.

#### Historical Exposure (`emdat_hist_exposure.parquet`)

Two measures of a country's pre-panel disaster experience are computed:

**Static** (`hist_sev_static`): Time-invariant per country.
```
hist_sev_static = ln(1 + sum(total_affected_filled, years 1988–2008) / pop_1988)
```
The 1988 start year matches the EM-DAT input file (`disasters_from_1988.xlsx`). The static measure is broadcast to all panel years (2008–2019) — it is the same value for a given country regardless of the year.

**Dynamic** (`hist_sev_dynamic`): Rolling 20-year window, varies by panel year.
```
hist_sev_dynamic[year] = ln(1 + sum(total_affected_filled, [year−20, year]) / pop_{year−20})
```
For panel year 2008, the window is 1988–2008 (identical to the static window — **see pitfall in Section 6**). For 2009 it shifts to 1989–2009, etc.

Population denominators for the dynamic measure come from the WDI population table for the base year of each window (`pop_{year−20}`). For 2008–2019 this requires population for 1988–1999.

**Group-specific and total auxiliary count columns** (8 columns, not used in regression — diagnostic):

| Column | Window | Disaster types counted |
|---|---|---|
| `hist_cnt_sudden_static` | 1988–2008, time-invariant | Earthquake, Volcanic activity, Mass movement (dry/wet), Impact |
| `hist_cnt_sudden_dynamic` | [year−20, year], varies | Same as above |
| `hist_cnt_seasonal_static` | 1988–2008, time-invariant | Flood, Storm, Wildfire |
| `hist_cnt_seasonal_dynamic` | [year−20, year], varies | Same as above |
| `hist_cnt_slow_static` | 1988–2008, time-invariant | Drought, Extreme temperature |
| `hist_cnt_slow_dynamic` | [year−20, year], varies | Same as above |
| `hist_cnt_total_static` | 1988–2008, time-invariant | All 13 mapped disaster types |
| `hist_cnt_total_dynamic` | [year−20, year], varies | All 13 mapped disaster types |

These mirror the three `SEV_GROUPS` (Sudden Physical, Seasonal Physical, Climatic Slow) from the panel severity columns. Only **mapped** disaster types are counted (events with unmapped `Disaster Type` are excluded). The groups are defined in the `HIST_CNT_GROUPS` constant in `02_clean_emdat.py`.

**NaN behavior**: Both `hist_sev_static` and `hist_sev_dynamic` remain `NaN` when the country is absent from the WDI population table. **Do not fill these with 0** — a `NaN` means the historical severity cannot be computed, not that it is zero. Filling occurs downstream in `08_create_estimation_sample.py` after the join, using the "no EM-DAT entry = zero severity" logic.

---

### `03_clean_wdi_wgi.py`

**Purpose**: Clean World Bank macro-economic controls (GDP per capita, population, government effectiveness).

#### WDI GDP
The input file `API_NY.GDP.MKTP.KD_DS2_en_csv_v2_374654.csv` contains **total GDP in constant 2015 USD** (World Bank indicator `NY.GDP.MKTP.KD`), not per capita. The script computes:
```python
df_wdi["gdp_pc_const2015_usd"] = df_wdi["gdp_total_const2015_usd"] / df_wdi["population"]
```
This yields GDP per capita in **constant 2015 USD**, comparable across countries and years without inflation or exchange-rate contamination.

#### WDI Format
Both the GDP file and `population_size.csv` use the World Bank standard CSV format with 4 header rows (`skiprows=4`). Year columns are string-encoded (`"2008"`, ..., `"2019"`). The script keeps years 2000 (historical exposure baseline) and 2007–2019 (panel + lag year), then melts to long format.

Only rows where `Country Code` has exactly 3 characters are kept, which filters out World Bank regional aggregates (e.g. `"ZJ"`, `"XU"`, `"WLD"`).

#### WGI Government Effectiveness
The WGI file `wgidataset_with_sourcedata-2025.xlsx` contains multiple indicator sheets. The script auto-detects the Government Effectiveness sheet by name matching (`"gov"` + `"eff"`). It handles both long format (Year as a column — WGI 2025 style) and wide format (years as columns — older WGI style). The relevant column is:
- Long format: `"Governance estimate (approx. -2.5 to +2.5)"`
- Wide format: year columns after a country code column

Only `ge_estimate` (the GE point estimate) is retained. Standard errors and percentile ranks are dropped.

---

### `04_clean_tiva.py`

**Purpose**: Compute the GVC Position Index from OECD TiVA data.

#### Source Files
- `EXGR_FVASH.csv`: Foreign Value Added Share in Exports — measures **backward linkage / downstreamness**. A high value means the country/sector imports many foreign inputs for its exports.
- `EXGR_INTDVASH.csv`: Domestic Intermediate Value Added as Share of Gross Exports — measures **forward linkage / upstreamness**. A high value means the country/sector exports mostly intermediates used by others.

Both files are filtered to `COUNTERPART_AREA == "W"` (world aggregate, not bilateral).

#### Filtering Logic
```python
# Single-letter section codes only (A–S); drops _T totals and multi-section codes
section_mask = df["section"].apply(
    lambda x: isinstance(x, str) and len(x.strip()) == 1 and x.strip() in VALID_SECTIONS
)
# 3-letter ISO country codes only; drops TiVA regional aggregates (A5_A7, APEC, etc.)
country_mask = df["country"].apply(
    lambda x: bool(re.match(r"^[A-Z]{3}$", str(x).strip()))
)
```

#### GVC Position Index (Koopman, Wang & Wei 2014)
```
gvc_position = ln(1 + fwd/100) − ln(1 + bwd/100)
```
- **Positive value**: net upstream position (country/sector sells intermediates to others)
- **Negative value**: net downstream position (country/sector absorbs foreign intermediates)
- `np.log1p` is used (`ln(1 + x)`) which is NaN-safe: `np.log1p(NaN) = NaN`, preventing silent errors when either component is missing.

#### What Enters the Final Panel
Only `gvc_position` is carried into `panel_final.parquet`. The raw components `gvc_fwd_int` and `gvc_bwd_fva` are retained in `tiva_clean.parquet` for diagnostics but are **not** merged into the panel in `07_merge.py`.

#### Coverage
~81 countries × 19 NACE sections (A–S) × 12 years (2008–2019). Aggregate NACE codes (`B-S_X_O`, `G-S_X_O`) have no TiVA match — these rows get `NaN` for `gvc_position` in the final panel.

---

### `05_clean_cepii.py`

**Purpose**: Clean CEPII bilateral gravity variables.

#### Correct Source File
Use `dist_cepii.xls` (**bilateral pairs** file), **not** `geo_cepii.xls` (which is country-level metadata). The bilateral file is located at `data/Bronze/dist_cepii.xls`.

#### Variables Kept
| Column | Definition |
|---|---|
| `iso_o` | Origin country (home in MNE context) — ISO-3 |
| `iso_d` | Destination country (host in MNE context) — ISO-3 |
| `distw` | Population-weighted distance between most-populated cities (km) |
| `contig` | 1 if countries share a land border, 0 otherwise |
| `colony` | 1 if colonial relationship ever existed, 0 otherwise |
| `comlang_off` | 1 if countries share an official language, 0 otherwise |

Alternative distance measures (`distwces`, `distcap`, `dist`) and detailed colonial history variables are dropped.

Self-pairs (`iso_o == iso_d`) and rows with missing `distw` are removed before saving.

Note: `iso_o/iso_d` are renamed to `home_country/host_country` in `06_standardise_countries.py`. The `07_merge.py` script contains a defensive check for both naming conventions.

---

### `06_standardise_countries.py`

**Purpose**: Ensure all Silver parquet files use consistent ISO-3 alpha-3 country codes, and rename CEPII columns.

The script reads each Silver file and calls:
```python
cc.pandas_convert(series, to="ISO3", not_found=None)
```
Unresolvable codes (e.g. TiVA regional aggregates like `"A5_A7"`, `"APEC"`) are set to `NaN` — **they are not dropped**. A summary of unresolved codes is printed at the end.

**Critical rename for CEPII**:
```python
df_cepii = df_cepii.rename(columns={"iso_o": "home_country", "iso_d": "host_country"})
```
This rename must happen before `07_merge.py` runs, or the CEPII join on `[home_country, host_country]` will fail.

Each file is re-saved in-place (overwrites the original Silver file).

---

### `07_merge.py`

**Purpose**: Join all Silver datasets into a single wide panel. This is the most architecturally complex script.

#### Layer 0 — Building the Base Panel (FATS Pivot)

**Step 1 — NACE Whitelist Filter (defensive)**:
```python
NACE_WHITELIST = set("ABCDEFGHIJKLMNOPQRS") | {"B-S_X_O", "G-S_X_O"}
df_fats_base = df_fats_base[df_fats_base["industry"].isin(NACE_WHITELIST)].copy()
```
This is redundant given `01_clean_fats.py` already applies the whitelist, but acts as a safety net against any future regression in script 01.

**Step 2 — Deduplication Check**:
Before pivoting, a check verifies no duplicate `(year, home_country, host_country, industry, variable)` rows exist. A duplicate here would cause the pivot to silently sum two observations for the same cell, inflating ENT/EMP/TUR.

**Step 3 — The Critical Pivot**:
```python
df_wide = df_fats_base.pivot_table(
    index=["year", "home_country", "host_country", "industry"],
    columns="variable",
    values="value",
    aggfunc=lambda x: x.sum(min_count=1),
    dropna=True,
).reset_index()
```

Two key parameters:

- **`aggfunc=lambda x: x.sum(min_count=1)`**: When Eurostat suppresses a value for confidentiality (ENT ∈ {1, 2}), the API returns NaN. With `min_count=1`, a group containing only NaN values returns NaN — preserving the suppression signal. With plain `aggfunc="sum"`, that single-row NaN group becomes `0.0`, falsely recording "zero affiliates".

- **`dropna=True`**: Drops rows where **all** of ENT, EMP, TUR are NaN (fully suppressed — no usable information). This was the source of a previous bug: pandas `pivot_table` with `dropna=True` first drops NaN-key **columns**, then drops rows that are fully NaN. This was inadvertently removing ~41,000 fully-suppressed observations that should have been in the output.

**Step 4 — `home_region` Re-attachment**:
`home_region` is not included in the pivot index (it would create redundant group dimensions). It is re-attached via a lookup after the pivot:
```python
home_region_map = (
    df_fats_base[["home_country", "home_region"]]
    .drop_duplicates(subset="home_country")
    .set_index("home_country")["home_region"]
)
df_wide["home_region"] = df_wide["home_country"].map(home_region_map)
```

**Step 5 — `nace_section` Derivation**:
```python
df_wide["nace_section"] = df_wide["industry"].apply(
    lambda x: x if (isinstance(x, str) and len(x) == 1 and x in VALID_SECTIONS) else None
)
```
This must be done **after** the pivot. If `nace_section` were in the pivot index, pandas would drop rows keyed on `None` (aggregate codes), losing those rows entirely.

**Step 6 — Geographic Aggregate Filter**:
Eurostat returns aggregate host "countries" like `EU27_2007`, `WORLD`, `AFR`, `AN` (Netherlands Antilles). These have no single-point disaster shock, no WDI/WGI controls, and are not usable in regression. They are filtered out here, before any joins.

#### Layers 1–7 — Sequential Left Joins

All 7 layers use `how="left"`, preserving the full base panel row count. After each join, an `assert len(df_wide) == before` guard confirms no fan-out (which would indicate duplicate join keys in the source data).

| Layer | Source | Join Key | Columns Added |
|---|---|---|---|
| 1 | `emdat_clean.parquet` | `[year, host_country]` | 13 `n_*` counts, 3 `sev_*`, `total_missing_affected` |
| 2 | `emdat_hist_exposure.parquet` | `[year, host_country]` | `hist_sev_static_host`, `hist_sev_dynamic_host`, `hist_cnt_sudden_static_host`, `hist_cnt_sudden_dynamic_host`, `hist_cnt_seasonal_static_host`, `hist_cnt_seasonal_dynamic_host`, `hist_cnt_slow_static_host`, `hist_cnt_slow_dynamic_host`, `hist_cnt_total_static_host`, `hist_cnt_total_dynamic_host` |
| 3 | `emdat_hist_exposure.parquet` | `[year, home_country]` | same 10 columns with `_home` suffix |
| 4 | `cepii_clean.parquet` | `[home_country, host_country]` | `distw`, `contig`, `colony`, `comlang_off` |
| 5a | `wdi_clean.parquet` | `[year, host_country]` | `gdp_pc_host`, `pop_host` |
| 5b | `wdi_clean.parquet` | `[year, home_country]` | `gdp_pc_home`, `pop_home` |
| 6a | `wgi_clean.parquet` | `[year, host_country]` | `ge_host` |
| 6b | `wgi_clean.parquet` | `[year, home_country]` | `ge_home` |
| 7 | `tiva_clean.parquet` | `[year, host_country, nace_section]` | `gvc_position` |

Layer 7 uses `nace_section` (not `industry`) as the join key. Aggregate industry rows (`nace_section = NaN`) have no TiVA match and receive `NaN` for `gvc_position`.

---

### `08_create_estimation_sample.py`

**Purpose**: Apply final cleaning steps to produce the estimation-ready sample from `panel_final.parquet`.

#### Step 1 — NaN → 0.0 for Disaster and Exposure Columns

All columns with prefixes `n_`, `sev_`, `hist_sev_`, `hist_cnt_` are filled to 0.0:
```python
ZERO_PREFIXES = ("n_", "sev_", "hist_sev_", "hist_cnt_")
zero_cols = [c for c in df.columns if c.startswith(ZERO_PREFIXES)]
for col in zero_cols:
    df[col] = df[col].fillna(0.0)
```

**Rationale**: A NaN in these columns means the country-year has no EM-DAT entry — not that data were collected and are missing. The correct economic interpretation is "zero recorded disasters / zero severity". This is distinct from NaN in `gdp_pc_host` (where NaN genuinely means "no data available").

#### Step 2 — Drop Internal Investment

Rows where `home_country == host_country` are removed. FDI gravity models are defined on cross-border pairs only. These rows should not exist after geographic aggregate filtering, but the step is applied defensively.

#### Step 3 — Drop NACE Section K (Financial & Insurance Activities)

```python
df = df[df["industry"] != "K"].copy()
```

Section K is excluded from the estimation sample entirely for three structural reasons:
1. **Confidentiality suppression**: Financial affiliates often number 1–2 per host, triggering Eurostat's confidentiality rules. ENT is frequently NaN for K, making the dependent variable unreliable.
2. **Shell company contamination**: Many K affiliates are SPVs, holding companies, or insurance captives with no employees. `emp` is 0 or suppressed while `ent` is nonzero — the labour-intensity signal is meaningless.
3. **GVC anomaly**: TiVA Section K shows extreme `gvc_position` values because financial intermediation is structurally upstream in input-output tables (regardless of actual disaster exposure).

Section K rows are retained in `panel_final.parquet` for reference; the exclusion happens only here.

#### Step 4 — Listwise Deletion on Host Macro-Controls

Drop rows where any of `gdp_pc_host`, `pop_host`, `ge_host` is NaN. These rows correspond to very small territories or statistical aggregates that survived the geographic aggregate filter but still lack World Bank coverage.

#### Step 5 — Listwise Deletion on Gravity

Drop rows where `distw` is NaN. Same reason as Step 4 — CEPII has no entry for these dyads (typically micro-territories or non-standard entities).

#### Step 6 — Dyad Pruning (Structural Zeros)

```python
dyad_cols = ["home_country", "host_country", "industry"]
dyad_ent_sum = df.groupby(dyad_cols)["ent"].sum(min_count=1)
active_dyads = (
    dyad_ent_sum[dyad_ent_sum > 0]
    .reset_index()[dyad_cols]
    .assign(_keep=True)
)
df = df.merge(active_dyads, on=dyad_cols, how="inner").drop(columns="_keep")
```

**Logic**: A dyad `(home, host, industry)` is "active" if the sum of `ent` across all panel years is strictly positive. Dyads where ENT is always 0 or always NaN/suppressed are removed.

**Why `min_count=1`**: Without it, `.sum()` on an all-NaN group returns 0.0 (not NaN). That would incorrectly mark always-suppressed dyads as "active" (sum = 0, which is > 0... wait, 0 is not > 0 — but the sum being 0 and sum being NaN have different implications). With `min_count=1`, an all-NaN group returns NaN, which fails the `> 0` test and is correctly excluded.

**Scale of pruning**: ~64% of rows in `panel_final.parquet` are dropped here. This is expected — most possible dyad combinations in a 29-home × 210-host × 21-industry space are structurally inactive (no European MNE has affiliates in every host country in every sector).

---

### `09_create_extensive_sample.py`

**Purpose**: Build an extensive-margin estimation sample that retains structurally inactive dyads (ENT = 0 for all years) to test whether natural disaster risk deters MNE entry into host countries. This complements `08_create_estimation_sample.py` (intensive margin) rather than replacing it.

**Rationale**: `08_create_estimation_sample.py` Step 6 prunes all dyads where ENT is always 0 or suppressed. These "always-zero" pairs are exactly the informative observations needed to study the extensive margin — whether European MNEs chose not to establish any affiliates in a given country. The advisor's suggestion motivates this script.

**Scope**: Restricted to `industry == "B-S_X_O"` only. The extensive margin question ("does home MNE have any affiliates in host country?") is naturally a country-pair question; at section level it becomes ambiguous (absent in C but present in G still means "present in the country"). B-S_X_O is the aggregate that best captures overall presence.

**Estimation approach**: PPML (Poisson PML, Silva & Tenreyro 2006), which handles structural zeros natively and is the standard in the gravity literature. Do **not** use OLS with `ln(ent + 1)` on this sample — the distribution of ENT has a structural mass at zero and cannot be well-approximated by a log transformation.

#### Construction Logic

Unlike `08_create_estimation_sample.py` (which starts from `panel_final.parquet` and subsets), `09_create_extensive_sample.py` builds from scratch to guarantee coverage of pairs absent from the FATS panel:

1. **Valid host countries**: countries with non-NaN `gdp_pc + pop` (WDI) AND `ge` (WGI) in at least one panel year → **203 hosts** after intersection
2. **Valid (home, host) pairs**: 29 home countries × valid hosts × non-NaN `distw` (CEPII) → **5,481 pairs**
3. **Cartesian base**: 5,481 pairs × 12 years × B-S_X_O → **65,772 rows** (no row pruning)
4. **Controls joined from Silver files** directly (Layers 1–6 same as `07_merge.py`, Layer 7 TiVA omitted — `gvc_position = NaN` for B-S_X_O)
5. **FATS ENT/EMP/TUR**: left join from `panel_final.parquet` filtered to B-S_X_O
6. **Structural zeros**: rows absent from FATS → `ENT = EMP = TUR = 0.0`
7. **NaN → 0** for disaster/exposure columns; **no dyad pruning**

#### Output Flag: `_fats_active`

| Value | Meaning |
|---|---|
| `True` | The (home, host) pair had ENT > 0 in at least one year in FATS |
| `False` | Never had ENT > 0 in FATS — structural zero or always confidentiality-suppressed |

Use `_fats_active` to distinguish "never entered" from "entered and then exited" in heterogeneity analyses.

#### Key Statistics (`estimation_sample_extensive.parquet`)

| Metric | Value |
|---|---|
| Shape | 65,772 rows × 58 cols |
| Home countries | 29 |
| Host countries | 190 |
| ENT = 0 (struct. zero + true zero) | 43,476 (66%) |
| ENT > 0 (active affiliates) | 21,798 (33%) |
| ENT = NaN (confidentiality suppressed) | 498 (0.8%) |
| `_fats_active = True` rows | 29,712 (45%) |
| `_fats_active = False` rows | 36,060 (55%) |
| `gdp_pc_host` NaN | 0.4% (specific years for near-valid hosts) |

#### CEPII ROM → ROU Fix

CEPII dist_cepii.xls uses "ROM" for Romania. `06_standardise_countries.py` did not convert this code (it appears in `cepii_clean.parquet` as "ROM"). `09_create_extensive_sample.py` applies a manual replacement `"ROM" → "ROU"` at load time so that Romania is included as a home country. This is a **pre-existing bug in 06** — it does not affect `07_merge.py` (which joins CEPII on home+host, and Romania's FATS home rows do match because 06 correctly standardized fats_clean.parquet; the mismatch only matters when CEPII is used as the base for the Cartesian expansion in 09).

---

## 4. Specific Data Handling Rules — The "Why"

### Confidentiality Suppression: ENT ∈ {1, 2} → NaN, Not Zero

Eurostat applies confidentiality rules: when ENT (number of affiliates) is 1 or 2, the value is suppressed and the API returns NaN. If the pipeline used `aggfunc="sum"` (without `min_count=1`) in the `pivot_table`, a single-row group with NaN would be silently converted to 0.0. The resulting `panel_final.parquet` would contain rows falsely recorded as "zero affiliates" when the true meaning is "at least 1–2 affiliates, exact count confidential."

This matters for:
- Descriptive statistics: understated non-zero affiliate relationships
- Regressions using `log(ent + 1)` or Poisson: a false 0 is counted as "no activity" when there is activity
- Dyad pruning: a dyad where ENT is always suppressed would survive if suppressed values were converted to 0

The fix: `aggfunc=lambda x: x.sum(min_count=1)`. After pruning, any remaining NaN in `ent` in the estimation sample reflects true confidentiality suppression for that specific year — not absence of activity.

### Dyad Pruning — Why Drop 64% of the Panel?

The raw panel from `07_merge.py` contains the full Cartesian product of all active (home, host, industry) combinations ever observed in the FATS API, across all panel years. Many dyads are zero or suppressed for all 12 years.

Structural zeros carry no information for a **levels regression** — you cannot estimate a treatment effect on a dependent variable that never varies. They also inflate the dataset, slow down estimation, and create numerical issues in models with many fixed effects.

After steps 1–4 of `08_create_estimation_sample.py`, the remaining rows all have valid macro controls. Step 5 then prunes dyads that are uniformly zero/missing, retaining only dyads with demonstrated affiliate activity. The ~36% of rows that survive are the economically meaningful observations.

### Shell Company / Tax Haven Bias — `emp` Fix (Layer 0, `07_merge.py`)

Some host countries function as financial hubs or tax havens (e.g. Cayman Islands `CYM`, British Virgin Islands `VGB`, Luxembourg `LUX` as a host). These hosts attract high `ENT` counts from holding companies and Special Purpose Vehicles (SPVs), but `EMP` (employees) is reported as exactly 0 because these entities have no operational workforce.

**Pipeline fix applied in `07_merge.py`** (immediately after the FATS pivot):
```python
shell_mask = (df_wide["ent"] > 0) & (df_wide["emp"] == 0.0)
df_wide.loc[shell_mask, "emp"] = np.nan
```

**Why `emp = 0` is wrong here**: When Eurostat reports `emp = 0` alongside `ent > 0`, it means no employees are recorded — not that "zero employees" is the true operational count. Treating this as a genuine zero would contaminate any `emp/ent` labour-intensity ratio with extreme near-zero values from shell entities. Setting `emp = NaN` instead signals that the employee count is operationally meaningless for this observation, consistent with how other suppressed/uninformative values are handled.

**Scope**: This fix applies to `emp` only. `tur` is not modified — turnover for holding companies may be real even if workforce is zero.

**Downstream effect**: `panel_final.parquet` will contain more NaN values in `emp` than before. The `estimation_sample.parquet` will also show increased NaN in `emp` (NaN in `emp` does not trigger listwise deletion — only `gdp_pc_host`, `pop_host`, `ge_host`, and `distw` trigger listwise deletion).

The `is_host_tax_haven` flag previously suggested for notebooks is no longer needed for `emp` regressions — the problematic zeros are already removed upstream.

---

## 5. Schema & Variables Dictionary

Two estimation-ready files coexist:
- **`data/Silver/estimation_sample.parquet`** — intensive margin, all industries/sections, ~36% of panel_final rows after dyad pruning
- **`data/Silver/estimation_sample_extensive.parquet`** — extensive margin, B-S_X_O only, Cartesian panel of all valid (home, host) pairs, **no dyad pruning**

The schema below applies to both files unless otherwise noted. Additional column `_fats_active` (bool) exists only in `estimation_sample_extensive.parquet`.

**File**: `data/Silver/estimation_sample.parquet`

### Identifiers

| Column | Type | Description |
|---|---|---|
| `year` | int | Panel year, 2008–2019 |
| `home_country` | str (ISO-3) | MNE headquarters country (one of 29 EU+NOR reporters) |
| `host_country` | str (ISO-3) | Country where affiliate is located |
| `industry` | str | NACE Rev.2 section letter (A–S) or aggregate code (`B-S_X_O`, `G-S_X_O`) |
| `nace_section` | str or NaN | Single letter A–S for section-level rows; NaN for aggregate codes |
| `home_region` | str | European sub-region of home country: `W. Europe`, `N. Europe`, `S. Europe`, `E. Europe` |

### Dependent Variables

| Column | Type | Description |
|---|---|---|
| `ent` | float (NaN if suppressed) | Number of foreign affiliates. NaN = Eurostat confidentiality (ENT ∈ {1,2}) |
| `emp` | float (NaN if suppressed or shell) | Number of employees in affiliates. NaN = Eurostat suppression **or** shell company fix (ent > 0 and emp == 0 → set to NaN in Layer 0 of `07_merge.py`) |
| `tur` | float (NaN if suppressed) | Turnover of affiliates (EUR thousands). NaN = suppressed |

### Disaster Shock Variables (Host Country, Panel Year)
All are 0.0 after `08_create_estimation_sample.py` (no NaN remains).

**Event Count Variables** (13 columns): `n_earthquake`, `n_volcanic_activity`, `n_mass_movement_dry`, `n_mass_movement_wet`, `n_impact`, `n_flood`, `n_storm`, `n_wildfire`, `n_drought`, `n_extreme_temperature`, `n_animal_incident`, `n_epidemic`, `n_infestation`
- Type: int
- Definition: number of events of each type recorded in EM-DAT for that host country in that year

**Grouped Severity Variables** (3 columns):

| Column | Formula | Disaster Types Included |
|---|---|---|
| `sev_sudden_physical` | `ln(1 + Σ affected / pop)` | Earthquake, Volcanic activity, Mass movement (dry/wet), Impact |
| `sev_seasonal_physical` | `ln(1 + Σ affected / pop)` | Flood, Storm, Wildfire |
| `sev_climatic_slow` | `ln(1 + Σ affected / pop)` | Drought, Extreme temperature |

Population denominator = WDI country-year population. Events with missing `Total Affected` contribute 100 (proxy).

**Auxiliary**: `total_missing_affected` (int) — count of events with missing Total Affected in that country-year. Diagnostic only.

### Historical Exposure Variables (Host + Home, 20 columns)

**Log-severity (regression-ready, 4 columns):**

| Column | Definition | Time variation |
|---|---|---|
| `hist_sev_static_host` | `ln(1 + Σ affected 1988–2008 / pop_1988)` | Time-invariant (same value all panel years) |
| `hist_sev_dynamic_host` | `ln(1 + Σ affected [year−20, year] / pop_{year−20})` | Varies by year |
| `hist_sev_static_home` | Same formula for home country | Time-invariant |
| `hist_sev_dynamic_home` | Same formula for home country | Varies by year |

**Group-specific event counts — auxiliary, not for regression (16 columns):**

Each column follows the pattern `hist_cnt_{group}_{window}_{side}` where:
- `{group}`: `sudden` (Earthquake/Volcanic/Mass movement/Impact), `seasonal` (Flood/Storm/Wildfire), `slow` (Drought/Extreme temperature), `total` (all 13 mapped types)
- `{window}`: `static` (1988–2008, time-invariant) or `dynamic` ([year−20, year], time-varying)
- `{side}`: `host` or `home`

Example: `hist_cnt_sudden_static_host` = count of sudden-physical events in the host country 1988–2008.

All historical exposure columns are filled to 0.0 in the estimation sample (0 = no recorded historical exposure).

### Macro-Economic Controls

| Column | Definition | Source | Note |
|---|---|---|---|
| `ln_gdp_pc_host` | Log GDP per capita, host country, t-1 | WDI `NY.GDP.MKTP.KD` / pop, lagged | Constant 2015 USD; created in `08`/`09` |
| `pop_host` | Population, host country | WDI | Contemporaneous year t |
| `ge_host` | Government Effectiveness estimate, host, t-1 | WGI | Lagged; replaced by t-1 in `08`/`09` |
| `ln_gdp_pc_home` | Log GDP per capita, home country, t-1 | WDI `NY.GDP.MKTP.KD` / pop, lagged | Constant 2015 USD; created in `08`/`09` |
| `pop_home` | Population, home country | WDI | Contemporaneous year t |
| `ge_home` | Government Effectiveness estimate, home, t-1 | WGI | Lagged; replaced by t-1 in `08`/`09` |

### GVC Variable

| Column | Definition | Coverage |
|---|---|---|
| `gvc_position` | `ln(1 + fwd/100) − ln(1 + bwd/100)` (Koopman, Wang & Wei 2014) | Section-letter NACE rows only; NaN for aggregate codes + non-TiVA countries |

Positive = net upstream (exports intermediates); Negative = net downstream (absorbs foreign inputs).

### Gravity Variables (Static — No Year Dimension)

| Column | Definition |
|---|---|
| `distw` | Population-weighted great-circle distance, km (CEPII) |
| `contig` | 1 if home and host share a land border |
| `colony` | 1 if colonial relationship ever existed between home and host |
| `comlang_off` | 1 if home and host share an official language |

### Static Geographic Controls — Host Country (Layer 8, `10_clean_geo_controls.py`)

| Column | Type | Definition | Source |
|---|---|---|---|
| `surface_area_host` | float | Land area of host country, sq. km — mean over 2008-2019 (time-invariant in practice) | WB `AG.LND.TOTL.K2` |
| `landlocked_host` | int8 (0/1) | 1 if host country is landlocked, 0 otherwise | landlocked-countries-2026.csv (43 landlocked countries) |

**Coverage**: `surface_area_host` matched ~96% of panel rows; `landlocked_host` matched ~96% (NaN only for host countries absent from the WB land area file). Both variables are in `estimation_sample.parquet` and `estimation_sample_extensive.parquet`.

**Notable landlocked host countries in the panel**: AUT, CZE, HUN, SVK, LUX (EU home countries also appearing as hosts), plus non-EU: KAZ, UZB, MNG, ETH, ZMB, BOL, etc.

---

## 6. Known Pitfalls for Future Analysis

### "Biais Luxembourg" (Home Country Outlier)

Luxembourg (`LUX`) is a home country in the panel. Due to its role as a European financial hub and holding-company jurisdiction, Luxembourg MNEs show anomalously high `ENT` counts across many host countries. A single Luxembourg-headquartered holding company may legally own affiliates in dozens of jurisdictions, inflating the affiliate counts without reflecting genuine operational activity.

**Practical implication**: Luxembourg can dominate descriptive statistics and drive outlier leverage in regressions. Any heterogeneity analysis or robustness check should include a version excluding `home_country == "LUX"`. In PPML or count-data regressions, Luxembourg observations can dominate the pseudo-likelihood and pull coefficients.

### Small Country Bias in Disaster Severity Ratios

The severity formula divides total affected by population:
```
sev = ln(1 + total_affected / population)
```
For countries with small populations (e.g. Pacific island states, Caribbean microstates), even a moderate disaster affecting 10,000 people can produce a very large severity value if population is 50,000. This creates extreme outliers in `sev_sudden_physical`, `sev_seasonal_physical`, and `sev_climatic_slow`.

**Practical implication**: Check for high-leverage observations using Cook's distance or dfbeta statistics before interpreting severity coefficients. Consider winsorising severity at the 99th percentile, or use raw event counts (`n_*`) as alternative shock measures for robustness.

### Sector K (Financial and Insurance Activities)

NACE Section K is structurally different from other sectors in this panel and is **excluded from `estimation_sample.parquet`** (Step 3 of `08_create_estimation_sample.py`):

1. **Confidentiality suppression**: Financial affiliates often number 1–2 per host country, triggering Eurostat confidentiality rules. ENT is frequently NaN for K.
2. **Shell company contamination**: Many K affiliates are SPVs, holding companies, or insurance captives with no employees. `emp` is often 0 or suppressed while `ent` is nonzero.
3. **GVC anomaly**: TiVA Section K often shows extreme `gvc_position` values because financial intermediation is structurally upstream in input-output tables.
4. **Disaster response heterogeneity**: Financial affiliates may have a fundamentally different response to physical disasters than manufacturing or service affiliates — their assets are primarily financial (ledger entries) rather than physical infrastructure.

Section K rows remain in `panel_final.parquet` and can be extracted for a dedicated sensitivity analysis if needed (`df_panel[df_panel["industry"] == "K"]`).

### NaN vs 0 in Disaster Columns: `panel_final.parquet` vs `estimation_sample.parquet`

In `panel_final.parquet`: NaN in disaster columns means "this country-year has no entry in EM-DAT" — which could mean no disaster occurred, or that a disaster occurred but was not recorded, or that the country is simply absent from EM-DAT.

In `estimation_sample.parquet`: All disaster columns are 0.0 (never NaN). The imputation is deliberate — we treat "no EM-DAT entry" as "zero disasters and zero severity."

**Do not run regressions directly on `panel_final.parquet`** without first going through `08_create_estimation_sample.py`. Using NaN disaster values in a regression would cause those rows to be dropped by listwise deletion, which would conflate "no disaster" with "disaster of unknown severity."

### GDP in Constant 2015 USD

`ln_gdp_pc_host` and `ln_gdp_pc_home` are computed from `NY.GDP.MKTP.KD` (total GDP, constant 2015 USD) divided by WDI population, then log-transformed. Values are lagged one period (t-1) to avoid simultaneity bias. The raw `gdp_pc_host/home` columns are dropped from the estimation samples; only the lagged log versions are retained.

### Historical Exposure Collinearity in Year 2008

For panel year 2008:
- `hist_sev_static`: window 1988–2008, population denominator = pop_1988
- `hist_sev_dynamic`: window [2008−20, 2008] = [1988, 2008], population denominator = pop_1988

**Both cover exactly the same window with the same denominator. They are perfectly collinear for year 2008.**

Starting from 2009, the dynamic window shifts to [1989, 2009] with pop_1989 denominator, while static remains fixed at [1988, 2008] / pop_1988. The collinearity dissipates over time.

**Practical implication**: Never include both `hist_sev_static_host` and `hist_sev_dynamic_host` in the same regression without either: (a) dropping year 2008, (b) lagging the static measure by one year, or (c) using only one of the two.

### NACE Sections Missing for 2008–2009

Due to the NACE Rev.1.1 → Rev.2 crosswalk ambiguity, four broad sectors are entirely absent from 2008–2009:

| Missing for 2008–2009 | Rev.1.1 section | Rev.2 sections |
|---|---|---|
| Electricity + Water | E | D + E |
| Transport + ICT | I | H + J |
| Real Estate + Business Services | K | L + M + N |
| Arts + Other Services | O | R + S |

Any regression using section-level data (Strategy B) with year 2008 or 2009 will have structural gaps for these sectors. Consider excluding 2008–2009 from Strategy B regressions, or explicitly noting the limited coverage in the methods section.

---

## 7. Retired Scripts

The following scripts previously existed and have been deleted or renamed:

| Script | Reason |
|---|---|
| `07_harmonise_industries.py` | AMNE crosswalk — OECD AMNE data dropped entirely; no downstream consumer |
| `08_merge_final.py` | Replaced and renamed as `07_merge.py` (2026-03-31 refactor) |
| `09_create_sample.py` | Contained AMNE references; sample creation now handled in `08_create_estimation_sample.py` |
| `10_standardise_countries.py` | Renamed to `06_standardise_countries.py` (AMNE block removed) |

**AMNE**: OECD Analytical MNE database. Dropped from the pipeline in favour of a FATS-only base. All AMNE-related scripts have been deleted.

---

*Last updated: 2026-06-17 | Changes: added 09_create_extensive_sample.py (extensive margin); added 10_clean_geo_controls.py → geo_static.parquet (surface_area_km2, landlocked); Layer 8 added to 07_merge.py; surface_area_host + landlocked_host in both estimation samples; ROM→ROU CEPII bug fixed in 06_standardise_countries.py; pipeline fully re-run*

---

## 8. Regression Notebooks

All notebooks in `notebooks/` include an `os.chdir` guard in the imports cell that navigates to the project root when the kernel is launched from the `notebooks/` subdirectory. Data paths use `data/Silver/...` relative to the project root.

### `notebooks/cross_sectional_H1_2008.ipynb`

| Property | Value |
|---|---|
| **Hypothesis** | H1 — Ex-ante Location Strategy |
| **Year** | 2008 cross-section |
| **Strategy** | A (`industry == "B-S_X_O"`, total aggregate) |
| **Dependent variable** | `ln_ent` = ln(ent + 1); NaN (suppressed) dropped listwise |
| **Estimator** | OLS with HC3 heteroskedasticity-robust standard errors |
| **Models** | 3 stepwise (M1 baseline gravity → M2 + historical exposure → M3 + interaction) |

**Engineered variables:**

| Variable | Construction | Purpose |
|---|---|---|
| `ln_hist_cnt_total_static_host` | `np.log1p(hist_cnt_total_static_host)` | Corrects for land-area bias in raw event counts |
| `interaction_ge_hist` | `ge_host × ln_hist_cnt_total_static_host` | Tests institutional mitigation of historical exposure penalty |

**Model specifications:**

| Model | Regressors |
|---|---|
| M1 — Baseline Gravity | `ln_gdp_pc_host`, `ln_pop_host`, `ln_gdp_pc_home`, `ln_pop_home`, `ln_distw`, `contig`, `colony`, `comlang_off`, `ge_host` |
| M2 — + Historical Exposure | M1 + `hist_sev_static_host`, `ln_hist_cnt_total_static_host` |
| M3 — + Institutional Interaction | M2 + `interaction_ge_hist` |

**Key results (2026-04-29 run):**

| Model | N | Adj. R² |
|---|---|---|
| M1 | 1,411 | 0.5807 |
| M2 | 1,411 | 0.5925 |
| M3 | 1,411 | 0.5924 |

- **VIF**: `ge_host` (9.14) and `interaction_ge_hist` (8.57) are flagged; all other regressors ≤ 5. Collinearity is structural to the interaction design. Recommended robustness check: mean-center `ge_host` and `ln_hist_cnt_total_static_host` before forming the interaction term.
- **`hist_sev_static_host`**: −0.18 (M3), not significant (p≈0.15). Sign consistent with H1 but imprecise.
- **`ln_hist_cnt_total_static_host`**: +0.32*** (M3), significant and positive — **counter to H1**. Likely reflects EM-DAT reporting-quality bias: better-reporting countries also attract more FDI.
- **`interaction_ge_hist`**: −0.024, not significant (p≈0.45), sign opposite to H1. VIF renders estimate unreliable; mean-centering recommended before interpreting.

**Note**: `hist_sev_static_host` and `hist_sev_dynamic_host` are perfectly collinear in 2008 — only static is included. See §6 (Historical Exposure Collinearity in Year 2008).
