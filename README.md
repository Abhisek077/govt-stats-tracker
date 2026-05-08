# Government Statistics Vintage Tracker

**Capturing the numbers before they silently change.**

A fully automated system that takes daily snapshots of 20 US federal data series and logs when agencies silently revise historical figures. The revision history preserved here does not exist anywhere else.

📊 **[View Live Dashboard →](https://abhisek077.github.io/govt-stats-tracker/)**

---

## Why This Exists

Government agencies routinely revise published statistics — unemployment rates, poverty figures, mortality counts, pollution data — without changelog or notification. These "silent revisions" shift federal funding allocations, change policy conclusions, and alter historical narratives.

The Philadelphia Fed maintains a real-time dataset for a handful of national macroeconomic series. **For everything else — sub-national employment, public health, environment, housing — no systematic vintage archive exists.** If you didn't capture the original number before revision, it's gone forever.

This project fills that gap with a $0-cost automated system that runs daily on GitHub Actions.

---

## What's Tracked

20 data series across 6 federal agencies, specifically chosen because they are **not** covered by existing vintage archives (Philadelphia Fed / ALFRED) and have **documented revision patterns** with real-world consequences:

| Agency | Series | Why It Matters |
|--------|--------|----------------|
| **BLS** | State unemployment rates (LAUS) | Revised every March; drives Medicaid eligibility, SNAP, workforce funding |
| **BLS** | State nonfarm payroll (CES) | March 2025 benchmark revision was -911,000 jobs nationally |
| **BLS** | QCEW by state/industry | Preliminary → final over 5+ months, no vintage archive |
| **BLS** | Metro-level CPI | Seasonal factor updates silently overwrite prior months |
| **BEA** | State GDP by industry | Drives Medicaid FMAP, highway funding, education grants |
| **BEA** | MSA/County personal income | Used for poverty thresholds; revised 3+ years retroactively |
| **Census** | ACS poverty rates | 2021 methodology change retroactively revised 2019 figures |
| **Census** | ACS county median income | Input to HUD Section 8 income limits |
| **Census** | County population estimates | Prior-year estimates disappear when superseded |
| **CDC** | Provisional drug overdose deaths | 10–20% revision rates in some counties |
| **CDC** | Provisional respiratory mortality | COVID-era counts revised 10–20% after ICD-10 finalization |
| **CDC** | BRFSS behavioral risk estimates | 2011 methodology change revised prevalence by 1–5 points |
| **EPA** | AQS PM2.5 annual summary | ~4% routinely corrected; affects NAAQS attainment designations |
| **EPA** | TRI toxic releases | Facilities resubmit years later; shifts environmental justice conclusions |
| **HUD** | Point-in-Time homeless count | CoCs can resubmit; methodology changes break comparability |
| **HUD** | Fair Market Rents | Silently corrected when methodology errors are found |

---

## Data Rescue

This repo also contains a one-time archive of the **CPS Food Security Supplement (1995–2024)**, which was terminated by USDA in September 2025. Run `scripts/rescue_food_insecurity.py` once to capture this before it disappears from Census APIs.

---

## How It Works

```
Daily at 2 AM ET (GitHub Actions cron)
    ↓
Poll all 20 series via their public JSON APIs
    ↓
Compare each response against the last saved vintage (SHA-256 hash)
    ↓
If changed → compute field-level diff → log to revision_log.csv
    ↓
Save new vintage snapshot (data/vintages/{series}/{date}.json)
    ↓
Regenerate public dashboard (docs/index.html)
    ↓
Commit everything back to repo
```

Every vintage is preserved forever in git history. The revision log is append-only.

---

## Setup (Fork This)

### 1. Fork the repo

### 2. Get free API keys (all optional but recommended)

| Key | Where | Required? |
|-----|-------|-----------|
| `BLS_API_KEY` | [bls.gov/developers](https://www.bls.gov/developers/home.htm) | Optional (increases rate limit from 25→500/day) |
| `BEA_API_KEY` | [apps.bea.gov/API/signup](https://apps.bea.gov/API/signup/) | Required for BEA series |
| `CENSUS_API_KEY` | [api.census.gov](https://api.census.gov/data/key_signup.html) | Optional (increases rate limit) |
| `EPA_AQS_EMAIL` | [aqs.epa.gov](https://aqs.epa.gov/aqsweb/documents/data_api.html) | Required for EPA AQS |
| `EPA_AQS_KEY` | Same as above | Required for EPA AQS |

### 3. Add keys as GitHub Secrets
`Settings → Secrets and variables → Actions → New repository secret`

### 4. Enable GitHub Pages
`Settings → Pages → Source: Deploy from branch → main /docs`

### 5. Run it once manually
`Actions → Daily Stats Tracker → Run workflow`

---

## Repository Structure

```
├── .github/workflows/
│   └── daily_track.yml          # Automated daily schedule
├── scripts/
│   ├── tracker.py               # Core: fetch, diff, log
│   ├── generate_dashboard.py    # Builds public HTML dashboard
│   └── rescue_food_insecurity.py # One-time data rescue
├── data/
│   ├── vintages/                # Every snapshot, organized by series/date
│   │   ├── bls_laus_LASST060000000000003/
│   │   │   ├── 2026-05-08.json
│   │   │   ├── 2026-05-09.json
│   │   │   └── ...
│   │   └── ...
│   ├── revision_log.csv         # Append-only log of all detected revisions
│   ├── meta.json                # Run counts, start date
│   ├── latest_summary.json      # Most recent poll results
│   └── rescued/                 # One-time data rescue archives
└── docs/
    └── index.html               # Public dashboard (GitHub Pages)
```

---

## Methodology

- **Polling frequency:** Daily for CDC provisional series (weekly revisions); daily for all others (catches revision windows)
- **Comparison method:** SHA-256 hash of canonicalized JSON for fast unchanged detection; recursive field-level diff for changed data
- **Vintage preservation:** Every snapshot is saved as a dated JSON file. Git history provides an additional layer of provenance
- **Instrument stability:** The tracker script is a fixed instrument. Changes to the polling logic are documented in commit messages. The data format is schema-stable by design — we never retroactively change how we store vintages

---

## Citation

If you use this dataset in research, please cite:

```
Government Statistics Vintage Tracker [Dataset].
https://github.com/YOUR_USERNAME/govt-stats-tracker
Started: [DATE]. Accessed: [DATE].
```

---

## License

Code: MIT. Data: Public domain (all source data is US government work).

---

*This project is not affiliated with any federal agency. All data is fetched from publicly available government APIs.*
