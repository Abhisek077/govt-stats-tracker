"""
rescue_food_insecurity.py — ONE-TIME DATA RESCUE
──────────────────────────────────────────────────
The CPS Food Security Supplement was terminated in September 2025.
This script downloads and archives the complete 1995–2024 series
before institutional memory of where to find it fades.

Run this ONCE. It is not part of the daily cron job.
"""

import urllib.request
import json
import os
from pathlib import Path

OUTPUT_DIR = Path("data/rescued/cps_food_insecurity")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CENSUS_KEY = os.getenv("CENSUS_API_KEY", "")

# Available years for the CPS Food Security Supplement
# The supplement ran annually as part of the December CPS
YEARS = list(range(2015, 2025))  # API availability varies; 2015-2024 most reliable

print("=" * 60)
print("  CPS Food Insecurity Data Rescue")
print("  USDA terminated this series September 2025")
print("=" * 60)

rescued = 0
failed = 0

for year in YEARS:
    print(f"\n[{year}] Attempting download...")

    # Try the CPS Food Security API endpoint
    key_param = f"&key={CENSUS_KEY}" if CENSUS_KEY else ""
    url = (
        f"https://api.census.gov/data/{year}/cps/foodsec/dec"
        f"?get=HRFS12M1,HRFS12M2,HRFS12M3,HRFS12M4,GESTFIPS"
        f"&for=state:*{key_param}"
    )

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        outfile = OUTPUT_DIR / f"food_insecurity_{year}.json"
        outfile.write_text(json.dumps(data, indent=2))
        print(f"  ✓ Saved: {outfile} ({len(data)} rows)")
        rescued += 1

    except Exception as e:
        print(f"  ✗ Failed: {e}")
        failed += 1

    # Be polite to the API
    import time
    time.sleep(2)

# Also save metadata about what we rescued and when
meta = {
    "rescue_date": str(__import__("datetime").date.today()),
    "source": "Census CPS Food Security Supplement (December)",
    "status": "TERMINATED September 2025 by USDA",
    "years_attempted": YEARS,
    "years_rescued": rescued,
    "years_failed": failed,
    "note": (
        "This data series measured household food insecurity in the US "
        "annually since 1995. It was terminated when USDA discontinued "
        "the supplement. This archive preserves the API-accessible years."
    ),
}
(OUTPUT_DIR / "RESCUE_META.json").write_text(json.dumps(meta, indent=2))

print(f"\n{'=' * 60}")
print(f"  Rescued: {rescued} years")
print(f"  Failed:  {failed} years")
print(f"  Saved to: {OUTPUT_DIR}")
print(f"{'=' * 60}")
