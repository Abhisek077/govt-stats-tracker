"""
tracker.py — Government Statistics Vintage Tracker
────────────────────────────────────────────────────
Fetches government data series from BLS, BEA, Census, CDC, EPA, HUD.
Compares each pull against the last known vintage.
Logs any numerical changes as revision events.
"""

import os, json, hashlib, datetime, time, urllib.request, urllib.parse, urllib.error, csv
from pathlib import Path

DATA_DIR     = Path("data/vintages")
DIFF_LOG     = Path("data/revision_log.csv")
META_FILE    = Path("data/meta.json")
SUMMARY_FILE = Path("data/latest_summary.json")

BLS_API_KEY    = os.getenv("BLS_API_KEY", "")
BEA_API_KEY    = os.getenv("BEA_API_KEY", "")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")
EPA_AQS_EMAIL  = os.getenv("EPA_AQS_EMAIL", "")
EPA_AQS_KEY    = os.getenv("EPA_AQS_KEY", "")
HUD_API_TOKEN  = os.getenv("HUD_API_TOKEN", "")

ACS_YEAR           = 2023
SAMPLE_STATES      = ["06", "36", "48", "17", "12"]
SAMPLE_STATE_NAMES = ["California", "New York", "Texas", "Illinois", "Florida"]


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch_json(url, headers=None, timeout=30):
    try:
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [FETCH ERROR] {url[:80]}... → {e}")
        return None


def fetch_encoded(base_url, params, headers=None, timeout=30):
    """URL-encode params safely — but do NOT use for URLs with @ in values."""
    url = base_url + "?" + urllib.parse.urlencode(params)
    return fetch_json(url, headers=headers, timeout=timeout)


def post_json(url, payload, timeout=30):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [POST ERROR] {url[:80]}... → {e}")
        return None


# ── Agency-specific fetchers ──────────────────────────────────────────────────

def fetch_bls(series_ids):
    payload = {
        "seriesid":  series_ids,
        "startyear": str(datetime.date.today().year - 1),
        "endyear":   str(datetime.date.today().year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY
    return post_json("https://api.bls.gov/publicAPI/v2/timeseries/data/", payload)


def fetch_bea(table, line, geo):
    if not BEA_API_KEY:
        print("  [SKIP] BEA — no BEA_API_KEY secret set")
        return None
    url = (
        f"https://apps.bea.gov/api/data/?UserID={BEA_API_KEY}"
        f"&method=GetData&datasetname=Regional&TableName={table}"
        f"&LineCode={line}&GeoFips={geo}&Year=LAST5&ResultFormat=JSON"
    )
    return fetch_json(url)


def fetch_census_acs(year, variables, geo):
    params = {"get": variables, "for": geo}
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY
    return fetch_encoded(f"https://api.census.gov/data/{year}/acs/acs1", params)


def fetch_cdc(resource_id, params):
    """CDC Socrata — use fetch_encoded for proper param handling."""
    return fetch_encoded(f"https://data.cdc.gov/resource/{resource_id}.json", params)


# ── Vintage management ────────────────────────────────────────────────────────

def get_latest_vintage(series_id):
    safe = series_id.replace("/", "_").replace(" ", "_")
    d = DATA_DIR / safe
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


def save_vintage(series_id, date, data):
    safe = series_id.replace("/", "_").replace(" ", "_")
    p = DATA_DIR / safe / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True))


def compute_hash(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def find_diffs(old, new, prefix=""):
    diffs = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            path = f"{prefix}.{k}" if prefix else k
            if k not in old:
                diffs.append({"path": path, "type": "added",   "old": None,     "new": new[k]})
            elif k not in new:
                diffs.append({"path": path, "type": "removed", "old": old[k],   "new": None})
            else:
                diffs.extend(find_diffs(old[k], new[k], path))
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            path = f"{prefix}[{i}]"
            if i >= len(old):
                diffs.append({"path": path, "type": "added",   "old": None,    "new": new[i]})
            elif i >= len(new):
                diffs.append({"path": path, "type": "removed", "old": old[i],  "new": None})
            else:
                diffs.extend(find_diffs(old[i], new[i], path))
    else:
        if str(old) != str(new):
            diffs.append({"path": prefix, "type": "changed", "old": old, "new": new})
    return diffs


def log_revision(date, sid, name, agency, count, sample):
    exists = DIFF_LOG.exists()
    with open(DIFF_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["date", "series_id", "series_name", "agency", "diff_count", "sample_diff"])
        w.writerow([date, sid, name, agency, count, sample[:300]])


def process(series_id, name, agency, data, today):
    r = {
        "series_id":   series_id,
        "series_name": name,
        "agency":      agency,
        "status":      "ok",
        "diff_count":  0,
        "is_new":      False,
    }
    if data is None:
        r["status"] = "fetch_failed"
        return r
    prev = get_latest_vintage(series_id)
    if prev is None:
        save_vintage(series_id, today, data)
        r["is_new"] = True
        return r
    if compute_hash(prev) == compute_hash(data):
        r["status"] = "unchanged"
        return r
    diffs = find_diffs(prev, data)
    r["diff_count"] = len(diffs)
    r["status"] = "REVISED"
    save_vintage(series_id, today, data)
    sample = "; ".join(f"{d['path']}: {d['old']} → {d['new']}" for d in diffs[:3])
    log_revision(today, series_id, name, agency, len(diffs), sample)
    print(f"  ⚠️  REVISION: {len(diffs)} changes — {sample[:120]}")
    return r


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    today = datetime.date.today().isoformat()
    print(f"\n{'='*65}\n  Vintage Tracker — {today}\n{'='*65}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    # ── BLS: State unemployment ───────────────────────────────────────────
    print("\n[BLS] State unemployment (LAUS)...")
    d = fetch_bls([f"LASST{f}0000000000003" for f in SAMPLE_STATES])
    if d and d.get("status") == "REQUEST_SUCCEEDED":
        for s in d.get("Results", {}).get("series", []):
            sid = s.get("seriesID", "?")
            results.append(process(
                f"bls_laus_{sid}", f"State unemployment — {sid}",
                "BLS", s.get("data", []), today))
    time.sleep(2)

    # ── BLS: State nonfarm payroll ────────────────────────────────────────
    print("\n[BLS] State nonfarm payroll (CES)...")
    d = fetch_bls([f"SMS{f}000000000000001" for f in SAMPLE_STATES])
    if d and d.get("status") == "REQUEST_SUCCEEDED":
        for s in d.get("Results", {}).get("series", []):
            sid = s.get("seriesID", "?")
            results.append(process(
                f"bls_ces_{sid}", f"State payroll — {sid}",
                "BLS", s.get("data", []), today))
    time.sleep(2)

    # ── BLS: Metro CPI ────────────────────────────────────────────────────
    print("\n[BLS] Metro CPI...")
    d = fetch_bls(["CUURS49ASA0", "CUURS12ASA0", "CUURS35ASA0", "CUURS23ASA0"])
    if d and d.get("status") == "REQUEST_SUCCEEDED":
        for s in d.get("Results", {}).get("series", []):
            sid = s.get("seriesID", "?")
            results.append(process(
                f"bls_cpi_{sid}", f"Metro CPI — {sid}",
                "BLS", s.get("data", []), today))
    time.sleep(2)

    # ── BEA: State GDP + personal income ──────────────────────────────────
    print("\n[BEA] State GDP + personal income...")
    for fips, name in zip(SAMPLE_STATES, SAMPLE_STATE_NAMES):
        results.append(process(
            f"bea_sgdp_{fips}", f"State GDP — {name}",
            "BEA", fetch_bea("SQGDP9", "1", fips + "000"), today))
        time.sleep(1)
        results.append(process(
            f"bea_pinc_{fips}", f"Personal income — {name}",
            "BEA", fetch_bea("CAINC1", "1", fips + "000"), today))
        time.sleep(1)

    # ── Census: ACS poverty ───────────────────────────────────────────────
    print(f"\n[Census] ACS poverty ({ACS_YEAR})...")
    results.append(process(
        f"census_acs_poverty_{ACS_YEAR}", f"ACS poverty — {ACS_YEAR}",
        "Census", fetch_census_acs(ACS_YEAR, "B17001_001E,B17001_002E,NAME", "state:*"), today))
    time.sleep(2)

    # ── Census: ACS median income ─────────────────────────────────────────
    print(f"\n[Census] ACS median income ({ACS_YEAR})...")
    results.append(process(
        f"census_acs_income_{ACS_YEAR}", f"ACS median income — {ACS_YEAR}",
        "Census", fetch_census_acs(ACS_YEAR, "B19013_001E,NAME", "state:*"), today))
    time.sleep(2)

    # ── Census: Population estimates (FIX: POP not POP_2023) ─────────────
    print("\n[Census] Population estimates (2023)...")
    key_p = f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else ""
    results.append(process(
        "census_pop_2023", "State population 2023",
        "Census",
        fetch_json(f"https://api.census.gov/data/2023/pep/population?get=POP,NAME&for=state:*{key_p}"),
        today))
    time.sleep(2)

    # ── CDC: Provisional drug overdose deaths ─────────────────────────────
    print("\n[CDC] Provisional drug overdose deaths...")
    results.append(process(
        "cdc_overdose_provisional", "Provisional drug overdose deaths",
        "CDC",
        fetch_cdc("xkb8-kh2a", {"$limit": "5000", "$order": "year DESC, month DESC"}),
        today))
    time.sleep(2)

    # ── CDC: Provisional respiratory mortality (FIX: build URL manually) ──
    print("\n[CDC] Provisional respiratory mortality...")
    results.append(process(
        "cdc_respiratory_provisional", "Provisional respiratory mortality",
        "CDC",
        fetch_json("https://data.cdc.gov/resource/muzy-jte6.json?$limit=5000&$order=end_date%20DESC"),
        today))
    time.sleep(2)

    # ── CDC: BRFSS behavioral risk ────────────────────────────────────────
    print("\n[CDC] BRFSS behavioral risk...")
    results.append(process(
        "cdc_brfss", "BRFSS behavioral risk estimates",
        "CDC",
        fetch_cdc("dttw-5yxu", {"$limit": "5000", "$order": "year DESC", "$where": "year>2020"}),
        today))
    time.sleep(2)

    # ── EPA: AQS PM2.5 (FIX: build URL manually to preserve @ in email) ──
    print("\n[EPA] AQS PM2.5...")
    if EPA_AQS_EMAIL and EPA_AQS_KEY:
        epa_url = (
            f"https://aqs.epa.gov/data/api/annualData/byState"
            f"?email={EPA_AQS_EMAIL}&key={EPA_AQS_KEY}"
            f"&param=88101&bdate=20230101&edate=20231231&state=06"
        )
        results.append(process(
            "epa_aqs_pm25_ca", "AQS PM2.5 — California",
            "EPA", fetch_json(epa_url), today))
    else:
        print("  [SKIP] set EPA_AQS_EMAIL + EPA_AQS_KEY secrets")
    time.sleep(2)

    # ── EPA: TRI toxic releases ───────────────────────────────────────────
    print("\n[EPA] TRI toxic releases...")
    results.append(process(
        "epa_tri_ca_2022", "TRI toxic releases — CA 2022",
        "EPA",
        fetch_json("https://data.epa.gov/efservice/tri_facility/state_abbr/=/CA/reporting_year/=/2022/rows/0:100/JSON"),
        today))
    time.sleep(2)

    # ── HUD: Fair Market Rents (state list) ──────────────────────────────
    print("\n[HUD] Fair Market Rents...")
    if HUD_API_TOKEN:
        results.append(process(
            "hud_fmr_states", "Fair Market Rents — states",
            "HUD",
            fetch_json("https://www.huduser.gov/hudapi/public/fmr/listStates",
                       headers={"Authorization": f"Bearer {HUD_API_TOKEN}"}),
            today))
    else:
        print("  [SKIP] set HUD_API_TOKEN")
    time.sleep(2)

    # ── HUD: Fair Market Rents (California detail) ────────────────────────
    print("\n[HUD] Fair Market Rents — California detail...")
    if HUD_API_TOKEN:
        results.append(process(
            "hud_fmr_ca_detail", "Fair Market Rents — California detail",
            "HUD",
            fetch_json("https://www.huduser.gov/hudapi/public/fmr/statedata/CA",
                       headers={"Authorization": f"Bearer {HUD_API_TOKEN}"}),
            today))
    else:
        print("  [SKIP] set HUD_API_TOKEN")
    time.sleep(2)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    revised   = [r for r in results if r["status"] == "REVISED"]
    failed    = [r for r in results if r["status"] == "fetch_failed"]
    new_      = [r for r in results if r.get("is_new")]
    unchanged = [r for r in results if r["status"] == "unchanged"]

    print(f"  Polled    : {len(results)}")
    print(f"  New       : {len(new_)}")
    print(f"  Unchanged : {len(unchanged)}")
    print(f"  REVISED ⚠️ : {len(revised)}")
    print(f"  Failed    : {len(failed)}")

    summary = {
        "date":      today,
        "total":     len(results),
        "new":       len(new_),
        "unchanged": len(unchanged),
        "revised":   len(revised),
        "failed":    len(failed),
        "revisions": [
            {"series": r["series_id"], "name": r["series_name"],
             "agency": r["agency"], "diffs": r["diff_count"]}
            for r in revised
        ],
        "results": results,
    }
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))

    meta = json.loads(META_FILE.read_text()) if META_FILE.exists() else {}
    if "started" not in meta:
        meta["started"] = today
    meta["last_run"] = today
    meta["total_runs"] = meta.get("total_runs", 0) + 1
    meta["total_revisions_detected"] = meta.get("total_revisions_detected", 0) + len(revised)
    META_FILE.write_text(json.dumps(meta, indent=2))

    print(f"\n✓ Done — {DATA_DIR}\n{'='*65}\n")


if __name__ == "__main__":
    run()
