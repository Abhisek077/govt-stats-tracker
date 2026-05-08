"""
tracker.py — Government Statistics Vintage Tracker
────────────────────────────────────────────────────
Fetches 20 government data series from BLS, BEA, Census, CDC, EPA, HUD.
Compares each pull against the last known vintage.
Logs any numerical changes as revision events.

Designed to run daily via GitHub Actions at $0 cost.
"""

import os
import json
import hashlib
import datetime
import time
import urllib.request
import urllib.error
import csv
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR      = Path("data/vintages")
DIFF_LOG      = Path("data/revision_log.csv")
META_FILE     = Path("data/meta.json")
SUMMARY_FILE  = Path("data/latest_summary.json")

# ── API Keys (from environment / GitHub Secrets) ──────────────────────────────

BLS_API_KEY = os.getenv("BLS_API_KEY", "")       # Optional, increases rate limit
BEA_API_KEY = os.getenv("BEA_API_KEY", "")       # Required for BEA
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")  # Optional, increases rate limit
EPA_AQS_EMAIL = os.getenv("EPA_AQS_EMAIL", "")   # Required for EPA AQS
EPA_AQS_KEY   = os.getenv("EPA_AQS_KEY", "")     # Required for EPA AQS

# ── Fetch helper ──────────────────────────────────────────────────────────────

def fetch_json(url: str, headers: dict = None, timeout: int = 30) -> Optional[dict]:
    """Fetch JSON from a URL with error handling."""
    try:
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [FETCH ERROR] {url[:80]}... → {e}")
        return None


def fetch_text(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch raw text/CSV from a URL."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  [FETCH ERROR] {url[:80]}... → {e}")
        return None


def post_json(url: str, payload: dict, timeout: int = 30) -> Optional[dict]:
    """POST JSON and return response."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [POST ERROR] {url[:80]}... → {e}")
        return None

# ── Series definitions ────────────────────────────────────────────────────────
# Each series has: id, name, agency, fetch function, revision_info

# We'll sample a few key states/counties/metros to keep within rate limits
# Full coverage can be expanded later

SAMPLE_STATES = ["06", "36", "48", "17", "12"]  # CA, NY, TX, IL, FL
SAMPLE_STATE_NAMES = ["California", "New York", "Texas", "Illinois", "Florida"]


def fetch_bls_series(series_ids: list) -> Optional[dict]:
    """Fetch from BLS Public Data API v2."""
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    payload = {
        "seriesid": series_ids,
        "startyear": str(datetime.date.today().year - 1),
        "endyear": str(datetime.date.today().year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY
    return post_json(url, payload)


def build_bls_laus_series_ids():
    """State unemployment rates — LAUS series."""
    return [f"LASST{fips}0000000000003" for fips in SAMPLE_STATES]


def build_bls_ces_series_ids():
    """State nonfarm payroll — CES series."""
    return [f"SMS{fips}000000000000001" for fips in SAMPLE_STATES]


def build_bls_metro_cpi_series_ids():
    """Metro CPI — major metros only."""
    return [
        "CUURS49ASA0",   # West urban (LA/SF)
        "CUURS12ASA0",   # Northeast urban (NYC)
        "CUURS35ASA0",   # South urban (Dallas/Houston)
        "CUURS23ASA0",   # Midwest urban (Chicago)
    ]


def fetch_bea_regional(table_name: str, line_code: str, geo_fips: str) -> Optional[dict]:
    """Fetch from BEA Regional API."""
    if not BEA_API_KEY:
        print("  [SKIP] BEA — no API key")
        return None
    url = (
        f"https://apps.bea.gov/api/data/?UserID={BEA_API_KEY}"
        f"&method=GetData&datasetname=Regional"
        f"&TableName={table_name}&LineCode={line_code}"
        f"&GeoFips={geo_fips}&Year=LAST5&ResultFormat=JSON"
    )
    return fetch_json(url)


def fetch_census_acs(year: int, variables: str, geo: str) -> Optional[dict]:
    """Fetch from Census ACS API."""
    key_param = f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else ""
    url = f"https://api.census.gov/data/{year}/acs/acs1?get={variables}&for={geo}{key_param}"
    return fetch_json(url)


def fetch_cdc_socrata(resource_id: str, params: str = "$limit=5000") -> Optional[dict]:
    """Fetch from CDC Socrata Open Data API."""
    url = f"https://data.cdc.gov/resource/{resource_id}.json?{params}"
    return fetch_json(url)


# ── Vintage management ────────────────────────────────────────────────────────

def get_vintage_path(series_id: str, date: str) -> Path:
    """Path for storing a vintage snapshot."""
    safe_id = series_id.replace("/", "_").replace(" ", "_")
    return DATA_DIR / safe_id / f"{date}.json"


def get_latest_vintage(series_id: str) -> Optional[dict]:
    """Load the most recent vintage for a series."""
    safe_id = series_id.replace("/", "_").replace(" ", "_")
    series_dir = DATA_DIR / safe_id
    if not series_dir.exists():
        return None
    files = sorted(series_dir.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def save_vintage(series_id: str, date: str, data: dict):
    """Save a new vintage snapshot."""
    path = get_vintage_path(series_id, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def compute_hash(data: dict) -> str:
    """Deterministic hash of data for quick comparison."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def find_diffs(old: dict, new: dict, prefix: str = "") -> list:
    """Recursively find changed values between two data snapshots."""
    diffs = []
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old:
                diffs.append({"path": path, "type": "added", "old": None, "new": new[key]})
            elif key not in new:
                diffs.append({"path": path, "type": "removed", "old": old[key], "new": None})
            else:
                diffs.extend(find_diffs(old[key], new[key], path))
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            path = f"{prefix}[{i}]"
            if i >= len(old):
                diffs.append({"path": path, "type": "added", "old": None, "new": new[i]})
            elif i >= len(new):
                diffs.append({"path": path, "type": "removed", "old": old[i], "new": None})
            else:
                diffs.extend(find_diffs(old[i], new[i], path))
    else:
        if str(old) != str(new):
            diffs.append({"path": prefix, "type": "changed", "old": old, "new": new})
    return diffs


def log_revision(date: str, series_id: str, series_name: str, agency: str,
                 diff_count: int, sample_diff: str):
    """Append a revision event to the CSV log."""
    exists = DIFF_LOG.exists()
    with open(DIFF_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["date", "series_id", "series_name", "agency",
                         "diff_count", "sample_diff"])
        w.writerow([date, series_id, series_name, agency, diff_count,
                     sample_diff[:300]])

# ── Main collection logic ─────────────────────────────────────────────────────

def process_series(series_id: str, series_name: str, agency: str,
                   data: Optional[dict], today: str) -> dict:
    """Compare new data against last vintage, save, and log diffs."""
    result = {
        "series_id":   series_id,
        "series_name": series_name,
        "agency":      agency,
        "status":      "ok",
        "diff_count":  0,
        "is_new":      False,
    }

    if data is None:
        result["status"] = "fetch_failed"
        return result

    previous = get_latest_vintage(series_id)

    if previous is None:
        # First vintage — just save it
        save_vintage(series_id, today, data)
        result["is_new"] = True
        return result

    # Compare hashes first (fast path)
    old_hash = compute_hash(previous)
    new_hash = compute_hash(data)

    if old_hash == new_hash:
        result["status"] = "unchanged"
        return result

    # Data changed — find specific diffs
    diffs = find_diffs(previous, data)
    result["diff_count"] = len(diffs)
    result["status"] = "REVISED"

    # Save new vintage
    save_vintage(series_id, today, data)

    # Log the revision
    sample = "; ".join(
        f"{d['path']}: {d['old']} → {d['new']}" for d in diffs[:3]
    )
    log_revision(today, series_id, series_name, agency, len(diffs), sample)

    print(f"  ⚠️  REVISION DETECTED: {len(diffs)} values changed")
    for d in diffs[:5]:
        print(f"     {d['path']}: {d['old']} → {d['new']}")

    return result


def run():
    today = datetime.date.today().isoformat()
    print(f"\n{'='*65}")
    print(f"  Government Statistics Vintage Tracker — {today}")
    print(f"{'='*65}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    # ── BLS: State unemployment (LAUS) ────────────────────────────────────
    print("\n[BLS] Fetching state unemployment rates (LAUS)...")
    laus_ids = build_bls_laus_series_ids()
    bls_data = fetch_bls_series(laus_ids)
    if bls_data and bls_data.get("status") == "REQUEST_SUCCEEDED":
        for series in bls_data.get("Results", {}).get("series", []):
            sid = series.get("seriesID", "unknown")
            name = f"State unemployment — {sid}"
            results.append(process_series(
                f"bls_laus_{sid}", name, "BLS",
                series.get("data", []), today
            ))
    else:
        print("  [SKIP] BLS LAUS fetch failed")
    time.sleep(2)

    # ── BLS: State nonfarm payroll (CES) ──────────────────────────────────
    print("\n[BLS] Fetching state nonfarm payroll (CES)...")
    ces_ids = build_bls_ces_series_ids()
    bls_data = fetch_bls_series(ces_ids)
    if bls_data and bls_data.get("status") == "REQUEST_SUCCEEDED":
        for series in bls_data.get("Results", {}).get("series", []):
            sid = series.get("seriesID", "unknown")
            name = f"State nonfarm payroll — {sid}"
            results.append(process_series(
                f"bls_ces_{sid}", name, "BLS",
                series.get("data", []), today
            ))
    else:
        print("  [SKIP] BLS CES fetch failed")
    time.sleep(2)

    # ── BLS: Metro CPI ────────────────────────────────────────────────────
    print("\n[BLS] Fetching metro CPI...")
    cpi_ids = build_bls_metro_cpi_series_ids()
    bls_data = fetch_bls_series(cpi_ids)
    if bls_data and bls_data.get("status") == "REQUEST_SUCCEEDED":
        for series in bls_data.get("Results", {}).get("series", []):
            sid = series.get("seriesID", "unknown")
            name = f"Metro CPI — {sid}"
            results.append(process_series(
                f"bls_cpi_{sid}", name, "BLS",
                series.get("data", []), today
            ))
    else:
        print("  [SKIP] BLS CPI fetch failed")
    time.sleep(2)

    # ── BEA: State GDP ────────────────────────────────────────────────────
    print("\n[BEA] Fetching state GDP...")
    for fips, name in zip(SAMPLE_STATES, SAMPLE_STATE_NAMES):
        data = fetch_bea_regional("SQGDP9", "1", fips + "000")
        results.append(process_series(
            f"bea_sgdp_{fips}", f"State GDP — {name}", "BEA",
            data, today
        ))
        time.sleep(1)

    # ── BEA: MSA personal income ──────────────────────────────────────────
    print("\n[BEA] Fetching MSA personal income...")
    for fips, name in zip(SAMPLE_STATES, SAMPLE_STATE_NAMES):
        data = fetch_bea_regional("CAINC1", "1", fips + "000")
        results.append(process_series(
            f"bea_pinc_{fips}", f"Personal income — {name}", "BEA",
            data, today
        ))
        time.sleep(1)

    # ── Census: ACS poverty & median income ───────────────────────────────
    print("\n[Census] Fetching ACS poverty rates...")
    last_year = datetime.date.today().year - 1
    acs_data = fetch_census_acs(last_year, "B17001_001E,B17001_002E,NAME", "state:*")
    results.append(process_series(
        f"census_acs_poverty_{last_year}", f"ACS state poverty — {last_year}",
        "Census", acs_data, today
    ))
    time.sleep(2)

    print("\n[Census] Fetching ACS median household income...")
    acs_income = fetch_census_acs(last_year, "B19013_001E,NAME", "state:*")
    results.append(process_series(
        f"census_acs_income_{last_year}", f"ACS state median income — {last_year}",
        "Census", acs_income, today
    ))
    time.sleep(2)

    # ── Census: County population estimates ───────────────────────────────
    print("\n[Census] Fetching county population estimates...")
    pop_url = f"https://api.census.gov/data/{last_year}/pep/population?get=POP_2020,NAME&for=state:*"
    if CENSUS_API_KEY:
        pop_url += f"&key={CENSUS_API_KEY}"
    pop_data = fetch_json(pop_url)
    results.append(process_series(
        f"census_pop_{last_year}", f"State population estimates — {last_year}",
        "Census", pop_data, today
    ))
    time.sleep(2)

    # ── CDC: Provisional drug overdose deaths ─────────────────────────────
    print("\n[CDC] Fetching provisional drug overdose deaths...")
    od_data = fetch_cdc_socrata("xkb8-kh2a",
        "$limit=5000&$order=year DESC,month DESC")
    results.append(process_series(
        "cdc_overdose_provisional", "Provisional drug overdose deaths",
        "CDC", od_data, today
    ))
    time.sleep(2)

    # ── CDC: Provisional respiratory mortality ────────────────────────────
    print("\n[CDC] Fetching provisional respiratory mortality...")
    resp_data = fetch_cdc_socrata("muzy-jte6",
        "$limit=5000&$order=end_date DESC")
    results.append(process_series(
        "cdc_respiratory_provisional", "Provisional respiratory mortality",
        "CDC", resp_data, today
    ))
    time.sleep(2)

    # ── CDC: BRFSS behavioral risk factors ────────────────────────────────
    print("\n[CDC] Fetching BRFSS behavioral risk estimates...")
    brfss_data = fetch_cdc_socrata("dttw-5yxu",
        "$limit=5000&$order=year DESC&$where=year>2020")
    results.append(process_series(
        "cdc_brfss", "BRFSS behavioral risk estimates",
        "CDC", brfss_data, today
    ))
    time.sleep(2)

    # ── EPA: AQS PM2.5 annual summary ────────────────────────────────────
    print("\n[EPA] Fetching AQS PM2.5 data...")
    if EPA_AQS_EMAIL and EPA_AQS_KEY:
        aqs_url = (
            f"https://aqs.epa.gov/data/api/annualData/byState"
            f"?email={EPA_AQS_EMAIL}&key={EPA_AQS_KEY}"
            f"&param=88101&bdate={last_year}0101&edate={last_year}1231"
            f"&state=06"  # California as sample
        )
        aqs_data = fetch_json(aqs_url)
        results.append(process_series(
            "epa_aqs_pm25_ca", "AQS PM2.5 annual — California",
            "EPA", aqs_data, today
        ))
    else:
        print("  [SKIP] EPA AQS — no credentials")
    time.sleep(2)

    # ── EPA: TRI toxic releases ───────────────────────────────────────────
    print("\n[EPA] Fetching TRI toxic releases...")
    tri_url = "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/reporting_year/=/2023/state_abbr/=/CA/JSON/rows/0:100"
    tri_data = fetch_json(tri_url)
    results.append(process_series(
        "epa_tri_ca_2023", "TRI toxic releases — California 2023",
        "EPA", tri_data, today
    ))
    time.sleep(2)

    # ── HUD: Homeless PIT count ───────────────────────────────────────────
    print("\n[HUD] Fetching Point-in-Time homeless count...")
    hud_pit_url = "https://www.huduser.gov/hudapi/public/pit?year=2024"
    hud_data = fetch_json(hud_pit_url)
    results.append(process_series(
        "hud_pit_2024", "Point-in-Time homeless count 2024",
        "HUD", hud_data, today
    ))
    time.sleep(2)

    # ── HUD: Fair Market Rents ────────────────────────────────────────────
    print("\n[HUD] Fetching Fair Market Rents...")
    fmr_url = "https://www.huduser.gov/hudapi/public/fmr/listMetroAreas"
    fmr_data = fetch_json(fmr_url)
    results.append(process_series(
        "hud_fmr_metros", "Fair Market Rents — metro list",
        "HUD", fmr_data, today
    ))

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    revised  = [r for r in results if r["status"] == "REVISED"]
    failed   = [r for r in results if r["status"] == "fetch_failed"]
    new      = [r for r in results if r.get("is_new")]
    unchanged= [r for r in results if r["status"] == "unchanged"]

    print(f"  Total series polled:  {len(results)}")
    print(f"  New (first vintage):  {len(new)}")
    print(f"  Unchanged:            {len(unchanged)}")
    print(f"  ⚠️  REVISED:           {len(revised)}")
    print(f"  Failed:               {len(failed)}")

    # Save summary
    summary = {
        "date":       today,
        "total":      len(results),
        "new":        len(new),
        "unchanged":  len(unchanged),
        "revised":    len(revised),
        "failed":     len(failed),
        "revisions":  [
            {"series": r["series_id"], "name": r["series_name"],
             "agency": r["agency"], "diffs": r["diff_count"]}
            for r in revised
        ],
        "results":    results,
    }
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))

    # Update meta
    meta = {}
    if META_FILE.exists():
        meta = json.loads(META_FILE.read_text())
    if "started" not in meta:
        meta["started"] = today
    meta["last_run"] = today
    meta["total_runs"] = meta.get("total_runs", 0) + 1
    meta["total_revisions_detected"] = meta.get("total_revisions_detected", 0) + len(revised)
    META_FILE.write_text(json.dumps(meta, indent=2))

    print(f"\n✓ Vintages saved to {DATA_DIR}")
    print(f"✓ Summary saved to {SUMMARY_FILE}")
    if revised:
        print(f"✓ Revisions logged to {DIFF_LOG}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    run()
