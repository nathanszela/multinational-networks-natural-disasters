# Data

Raw and processed data are not included in this repository. EM-DAT does not allow redistribution, and the processed files are large. To reproduce the results, download the raw files below and place them at the paths shown (relative to the repository root). The scripts then create everything in `data/Silver/`.

| Source | Where to get it | Expected path |
|---|---|---|
| Eurostat FATS outward (`FATS_OUT2_R2`, `FATS_OUT2`) | Downloaded automatically by `scripts/01_clean_fats.py` through the Eurostat API | none |
| EM-DAT, all natural disasters, 1987 onwards | [emdat.be](https://www.emdat.be/) (free account, non-commercial use) | `data/Bronze/Natural disasters/disasters_from_1987.xlsx` |
| World Bank GDP, constant 2015 USD (`NY.GDP.MKTP.KD`) | [data.worldbank.org](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD) | `data/Bronze/worldbank/country gdp/API_NY.GDP.MKTP.KD_DS2_en_csv_v2_374654.csv` |
| World Bank population (`SP.POP.TOTL`) | [data.worldbank.org](https://data.worldbank.org/indicator/SP.POP.TOTL) | `data/Bronze/worldbank/country population size/population_size.csv` |
| World Bank land area (`AG.LND.TOTL.K2`) | [data.worldbank.org](https://data.worldbank.org/indicator/AG.LND.TOTL.K2) | `data/Bronze/worldbank/land_size/API_AG.LND.TOTL.K2_DS2_en_csv_v2_265772.csv` |
| Worldwide Governance Indicators (2025 release) | [worldbank.org/en/publication/worldwide-governance-indicators](https://www.worldbank.org/en/publication/worldwide-governance-indicators) | `data/Bronze/worldbank/wgidataset_with_sourcedata-2025.xlsx` |
| Landlocked countries list | Any public list with ISO country codes | `data/Bronze/worldbank/landlocked-countries-2026.csv` |
| OECD TiVA, backward participation (`EXGR_FVASH`) | [OECD Data Explorer, TiVA](https://www.oecd.org/en/topics/sub-issues/trade-in-value-added.html) | `data/Bronze/GVC/backwards/EXGR_FVASH.csv` |
| OECD TiVA, forward participation (`EXGR_INTDVASH`) | same | `data/Bronze/GVC/forward/EXGR_INTDVASH.csv` |
| CEPII GeoDist, bilateral distances | [cepii.fr](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=6) | `data/Bronze/dist_cepii.xls` |

File names that include a version number (World Bank downloads) must match exactly, or the path must be edited at the top of the corresponding script.
