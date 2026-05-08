"""
generate_dashboard.py — Builds docs/index.html from data/
"""

import json, datetime
from pathlib import Path

SUMMARY  = Path("data/latest_summary.json")
META     = Path("data/meta.json")
DIFF_LOG = Path("data/revision_log.csv")
OUTPUT   = Path("docs/index.html")


def load_revisions():
    """Load revision log CSV into list of dicts."""
    if not DIFF_LOG.exists():
        return []
    rows = []
    import csv
    with open(DIFF_LOG, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows[-50:]  # Last 50 revisions


def build():
    if not SUMMARY.exists():
        print("[!] No summary file found. Run tracker.py first.")
        return

    summary = json.loads(SUMMARY.read_text())
    meta = json.loads(META.read_text()) if META.exists() else {}
    revisions = load_revisions()

    today      = summary.get("date", "—")
    started    = meta.get("started", "—")
    total_runs = meta.get("total_runs", 0)
    total_revs = meta.get("total_revisions_detected", 0)

    try:
        days = (datetime.date.today() - datetime.date.fromisoformat(started)).days
    except:
        days = 0

    # Agency breakdown
    agency_counts = {}
    for r in summary.get("results", []):
        a = r.get("agency", "?")
        agency_counts.setdefault(a, {"ok": 0, "revised": 0, "failed": 0})
        if r["status"] == "REVISED":
            agency_counts[a]["revised"] += 1
        elif r["status"] == "fetch_failed":
            agency_counts[a]["failed"] += 1
        else:
            agency_counts[a]["ok"] += 1

    agency_rows = ""
    for agency, counts in sorted(agency_counts.items()):
        total = counts["ok"] + counts["revised"] + counts["failed"]
        rev_pct = round(counts["revised"] / total * 100) if total else 0
        bar_w = min(rev_pct * 3, 100)
        agency_rows += f"""
        <div class="agency-row">
          <div class="agency-name">{agency}</div>
          <div class="agency-stats">
            <span class="a-total">{total} series</span>
            <span class="a-rev" style="color:{'#f59e0b' if counts['revised'] else '#64748b'}">{counts['revised']} revised</span>
          </div>
          <div class="agency-bar"><div class="agency-bar-fill" style="width:{bar_w}%"></div></div>
        </div>"""

    # Recent revisions table
    rev_rows = ""
    for rev in reversed(revisions[-20:]):
        rev_rows += f"""
        <tr>
          <td class="td-mono">{rev.get('date','')}</td>
          <td><span class="agency-badge">{rev.get('agency','')}</span></td>
          <td>{rev.get('series_name','')[:60]}</td>
          <td class="td-mono td-rev">{rev.get('diff_count','')}</td>
          <td class="td-sample">{rev.get('sample_diff','')[:120]}</td>
        </tr>"""

    if not rev_rows:
        rev_rows = '<tr><td colspan="5" class="td-empty">No revisions detected yet — accumulating baseline vintages</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Government Statistics Vintage Tracker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#fafaf9;--surface:#fff;--border:#e7e5e4;
    --text:#1c1917;--muted:#78716c;--accent:#b45309;
    --warn:#d97706;--danger:#dc2626;--ok:#16a34a;
  }}
  body{{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;line-height:1.6}}
  .wrap{{max-width:960px;margin:0 auto;padding:48px 24px 80px}}

  .header{{margin-bottom:40px;border-bottom:2px solid var(--text);padding-bottom:24px}}
  .eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--accent);letter-spacing:.15em;text-transform:uppercase;margin-bottom:6px}}
  h1{{font-size:28px;font-weight:700;line-height:1.2;margin-bottom:6px}}
  .subtitle{{color:var(--muted);font-size:14px;max-width:600px}}

  .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);margin-bottom:40px}}
  .stat{{background:var(--surface);padding:16px 20px}}
  .stat-val{{font-family:'IBM Plex Mono',monospace;font-size:28px;font-weight:600}}
  .stat-val.warn{{color:var(--warn)}}
  .stat-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}}

  .section{{margin-bottom:36px}}
  .section-title{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}}

  .agency-row{{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #f5f5f4}}
  .agency-name{{font-weight:600;width:60px;font-size:13px}}
  .agency-stats{{display:flex;gap:12px;font-size:12px;width:180px}}
  .a-total{{color:var(--muted)}}
  .a-rev{{font-weight:600}}
  .agency-bar{{flex:1;height:6px;background:#f5f5f4;border-radius:3px;overflow:hidden}}
  .agency-bar-fill{{height:100%;background:var(--warn);border-radius:3px;transition:width 0.3s}}

  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;text-align:left;padding:8px 10px;border-bottom:2px solid var(--border)}}
  td{{padding:10px;border-bottom:1px solid #f5f5f4;vertical-align:top}}
  .td-mono{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted)}}
  .td-rev{{color:var(--warn);font-weight:600;text-align:center}}
  .td-sample{{font-size:11px;color:var(--muted);max-width:300px;word-break:break-all}}
  .td-empty{{text-align:center;color:var(--muted);padding:24px;font-style:italic}}
  .agency-badge{{background:#fef3c7;color:#92400e;font-size:10px;font-weight:600;padding:2px 8px;border-radius:3px;letter-spacing:.04em}}

  .footer{{margin-top:48px;padding-top:20px;border-top:2px solid var(--text);display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px}}
  .footer-note{{font-size:12px;color:var(--muted);max-width:500px;line-height:1.7}}
  .footer-mono{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);text-align:right}}

  @media(max-width:600px){{
    .stats{{grid-template-columns:repeat(2,1fr)}}
    .agency-row{{flex-wrap:wrap}}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="header">
    <div class="eyebrow">Public Dataset · Updated Daily · Automated</div>
    <h1>Government statistics vintage tracker</h1>
    <p class="subtitle">Capturing the numbers before they silently change. Daily snapshots of 20 federal data series across BLS, BEA, Census, CDC, EPA, and HUD — preserving revision history that would otherwise be lost.</p>
  </header>

  <div class="stats">
    <div class="stat"><div class="stat-val">{days}</div><div class="stat-label">Days running</div></div>
    <div class="stat"><div class="stat-val">{total_runs}</div><div class="stat-label">Total polls</div></div>
    <div class="stat"><div class="stat-val warn">{total_revs}</div><div class="stat-label">Revisions caught</div></div>
    <div class="stat"><div class="stat-val">{summary.get('total',0)}</div><div class="stat-label">Series tracked</div></div>
  </div>

  <div class="section">
    <div class="section-title">Coverage by agency</div>
    {agency_rows}
  </div>

  <div class="section">
    <div class="section-title">Revision log</div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr><th>Date</th><th>Agency</th><th>Series</th><th>Changes</th><th>Sample diff</th></tr></thead>
        <tbody>{rev_rows}</tbody>
      </table>
    </div>
  </div>

  <footer class="footer">
    <div class="footer-note">
      This dataset preserves the exact values published by US federal agencies at each polling date.
      When agencies silently revise historical figures, the revision is logged with before/after values.
      All data is from public government APIs. Not affiliated with any federal agency.<br><br>
      <strong>Why this matters:</strong> Silent revisions to government statistics shift federal funding allocations,
      change policy conclusions, and alter historical narratives — but are not systematically recorded anywhere.
    </div>
    <div class="footer-mono">
      Last poll: {today}<br>
      Started: {started}<br>
      github.com/YOUR_USERNAME/govt-stats-tracker
    </div>
  </footer>
</div>
</body>
</html>"""

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html)
    print(f"✓ Dashboard written to {OUTPUT}")


if __name__ == "__main__":
    build()
