#!/usr/bin/env python3
"""
Flask Backend API — NSE Swing Scanner Web Application
Wraps swing_scanner.py as REST API endpoints with SSE progress streaming.

Output strategy (consolidated):
  scanner_results/
    master_scan.xlsx   <- ONE Excel workbook, 3 sheets, appended each scan
    latest_scan.html   <- ONE HTML report, overwritten each scan
    latest_scan.json   <- ONE JSON, overwritten each scan (for web API)
    swing_scan_<ts>.json <- per-scan JSON kept for web History panel
"""
import json
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, date

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

# ─── openpyxl imports ─────────────────────────────────────────────────────────
from openpyxl import load_workbook, Workbook
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side, GradientFill
)
from openpyxl.utils import get_column_letter
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import swing_scanner as scanner

app = Flask(__name__, static_folder=str(BASE_DIR / "web"), static_url_path="")

# ─── CORS ─────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path and (BASE_DIR / "web" / path).exists():
        return send_from_directory(str(BASE_DIR / "web"), path)
    return send_from_directory(str(BASE_DIR / "web"), "index.html")

# ─── Shared scan state ─────────────────────────────────────────────────────────
_scan_lock = threading.Lock()
_scan_state = {
    "running": False, "progress": 0, "total": 0,
    "current_symbol": "", "status": "idle", "message": "",
    "started_at": None, "finished_at": None, "result_file": None,
}
_scan_log = []

def _sse_event(data):
    return f"data: {json.dumps(data)}\n\n"

# ══════════════════════════════════════════════════════════════════════════════
# EXCEL WORKBOOK LOGIC
# ══════════════════════════════════════════════════════════════════════════════

# Colour fills
_FILL_GREEN  = PatternFill("solid", fgColor="0D3B2E")   # dark green bg
_FILL_YELLOW = PatternFill("solid", fgColor="3B2E0D")   # dark amber bg
_FILL_RED    = PatternFill("solid", fgColor="3B0D0D")   # dark red bg
_FILL_HEADER = PatternFill("solid", fgColor="0F1923")   # near-black header
_FILL_SUMMARY_TODAY = PatternFill("solid", fgColor="1A2840")  # highlight today

_FONT_HEADER  = Font(bold=True, color="A0C4FF", name="Calibri", size=10)
_FONT_GREEN   = Font(bold=True, color="34D399", name="Calibri", size=10)
_FONT_YELLOW  = Font(bold=True, color="FBBF24", name="Calibri", size=10)
_FONT_RED     = Font(bold=False, color="F87171", name="Calibri", size=10)
_FONT_NORMAL  = Font(color="E2E8F0", name="Calibri", size=10)
_FONT_MUTED   = Font(color="94A3B8", name="Calibri", size=10)
_FONT_TITLE   = Font(bold=True, color="60A5FA", name="Calibri", size=11)

_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=False)
_ALIGN_LEFT   = Alignment(horizontal="left",   vertical="center", wrap_text=False)
_ALIGN_RIGHT  = Alignment(horizontal="right",  vertical="center", wrap_text=False)
_ALIGN_WRAP   = Alignment(horizontal="left",   vertical="center", wrap_text=True)

_THIN_BORDER = Border(
    bottom=Side(style="thin", color="1E2D45"),
    right=Side(style="thin",  color="1E2D45"),
)

_EXCEL_FILE = "master_scan.xlsx"

# ── Sheet names ────────────────────────────────────────────────────────────────
SH_ALL     = "All Scans"
SH_DAILY   = "Daily Summary"
SH_PICKS   = "Top Picks History"

# ── All Scans columns ──────────────────────────────────────────────────────────
ALL_COLS = [
    ("Scan DateTime",     18), ("Date",            11), ("Symbol",         12),
    ("Signal",             8), ("Action Status",   22), ("Price ₹",        10),
    ("Daily Chg %",        9), ("RSI",              7), ("Buy Range",      22),
    ("Entry Low ₹",       10), ("Entry High ₹",    10), ("Stop Loss ₹",   10),
    ("Risk %",             8), ("Target 1 ₹",      10), ("T1 %",           7),
    ("Target 2 ₹",        10), ("T2 %",             7), ("Target 3 ₹",    10),
    ("T3 %",               7), ("R:R",              6), ("Score",           6),
    ("Max Score",          8), ("Risk Level",       10), ("EMA20",          9),
    ("EMA50",              9), ("EMA200",           9),  ("MACD",           9),
    ("MACD Signal",        9), ("Volume Ratio",    10),  ("Support ₹",      9),
    ("Resistance ₹",       9), ("ATR",              7),  ("Breakout",       8),
    ("NIFTY Regime",      14), ("Reasons",          60),
]

# ── Daily Summary columns ──────────────────────────────────────────────────────
DAILY_COLS = [
    ("Date",              11), ("Scan Count",       9),  ("Total Results",  12),
    ("🟢 Prime Buys",      11), ("🟡 Watchlist",    10),  ("🔴 Avoided",     10),
    ("NIFTY Regime",      14), ("NIFTY Price ₹",   12),  ("NIFTY RSI",      9),
    ("NIFTY EMA20",       10), ("NIFTY EMA50",     10),
    ("Prime Buy Symbols", 55), ("Watchlist Symbols",55),
]

# ── Top Picks columns ──────────────────────────────────────────────────────────
PICKS_COLS = [
    ("Scan DateTime",     18), ("Date",            11), ("Symbol",         12),
    ("Action Status",     22), ("Price ₹",         10), ("Daily Chg %",     9),
    ("RSI",                7), ("Buy Range",       22),  ("Stop Loss ₹",   10),
    ("Risk %",             8), ("Target 1 ₹",      10), ("T1 %",            7),
    ("Target 2 ₹",        10), ("Target 3 ₹",      10), ("R:R",             6),
    ("Score",              6), ("NIFTY Regime",    14),  ("Reasons",        60),
]


def _style_header_row(ws, cols):
    """Apply dark header styling to row 1."""
    for col_idx, (name, width) in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.value = name
        cell.font = _FONT_HEADER
        cell.fill = _FILL_HEADER
        cell.alignment = _ALIGN_CENTER
        cell.border = _THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _row_style(tag):
    """Return (fill, font) for a color_tag."""
    if tag == "GREEN":
        return _FILL_GREEN, _FONT_GREEN
    if tag == "YELLOW":
        return _FILL_YELLOW, _FONT_YELLOW
    return _FILL_RED, _FONT_RED


def _style_data_row(ws, row_idx, ncols, tag):
    fill, font = _row_style(tag)
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = fill
        if col == 1:
            cell.font = _FONT_MUTED   # datetime muted
        elif col in (3,):             # symbol bold
            cell.font = Font(bold=True, color=font.color, name="Calibri", size=10)
        else:
            cell.font = font
        cell.border = _THIN_BORDER
        align = _ALIGN_RIGHT if col >= 6 and col <= 22 else _ALIGN_LEFT
        cell.alignment = align
    ws.row_dimensions[row_idx].height = 18


def _get_or_create_wb(excel_path: Path) -> Workbook:
    """Load existing workbook or create a fresh one with headers."""
    if excel_path.exists():
        wb = load_workbook(excel_path)
        # Ensure all sheets exist
        for sh_name in (SH_ALL, SH_DAILY, SH_PICKS):
            if sh_name not in wb.sheetnames:
                ws = wb.create_sheet(sh_name)
                if sh_name == SH_ALL:
                    _style_header_row(ws, ALL_COLS)
                elif sh_name == SH_DAILY:
                    _style_header_row(ws, DAILY_COLS)
                else:
                    _style_header_row(ws, PICKS_COLS)
    else:
        wb = Workbook()
        # Remove default sheet
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        for sh_name, cols in ((SH_ALL, ALL_COLS), (SH_DAILY, DAILY_COLS), (SH_PICKS, PICKS_COLS)):
            ws = wb.create_sheet(sh_name)
            _style_header_row(ws, cols)
    return wb


def append_to_excel(results: list, nifty_regime: dict, scan_dt_str: str, out_dir: Path):
    """
    Append scan results to master_scan.xlsx:
      - Sheet 'All Scans'      : append all result rows with scan datetime
      - Sheet 'Daily Summary'  : upsert today's aggregate row
      - Sheet 'Top Picks History': append only GREEN (Prime Buy) rows
    """
    excel_path = out_dir / _EXCEL_FILE
    wb = _get_or_create_wb(excel_path)

    # Parse scan datetime
    try:
        scan_dt = datetime.strptime(scan_dt_str, "%Y%m%d_%H%M%S")
    except Exception:
        scan_dt = datetime.now()
    scan_dt_label = scan_dt.strftime("%Y-%m-%d %H:%M:%S")
    scan_date_label = scan_dt.strftime("%Y-%m-%d")
    today_str = scan_dt.strftime("%Y-%m-%d")

    regime_badge = nifty_regime.get("badge", "—") if nifty_regime else "—"

    # ── Sheet 1: All Scans ────────────────────────────────────────────────────
    ws_all = wb[SH_ALL]
    for r in results:
        tag = r.get("color_tag", "RED")
        row_num = ws_all.max_row + 1
        vals = [
            scan_dt_label, scan_date_label, r.get("symbol",""),
            r.get("signal",""), r.get("action_status",""),
            r.get("price", 0), r.get("daily_change_pct", 0),
            r.get("rsi", 0), r.get("buy_range",""),
            r.get("entry_low", 0), r.get("entry_high", 0),
            r.get("stop_loss", 0), r.get("risk_pct", 0),
            r.get("target_1", 0), r.get("target_1_pct", 0),
            r.get("target_2", 0), r.get("target_2_pct", 0),
            r.get("target_3", 0), r.get("target_3_pct", 0),
            r.get("risk_reward_to_target1", 0), r.get("score", 0),
            r.get("max_score", 10), r.get("risk_level",""),
            r.get(f"ema_{r.get('ema_fast',20)}", r.get("ema_20",0)),
            r.get(f"ema_{r.get('ema_slow',50)}", r.get("ema_50",0)),
            r.get(f"ema_{r.get('ema_long',200)}", r.get("ema_200",0)),
            r.get("macd", 0), r.get("macd_signal", 0),
            r.get("volume_ratio", 0),
            r.get("support", 0), r.get("resistance", 0),
            r.get("atr", 0), r.get("breakout", False),
            regime_badge, r.get("reasons",""),
        ]
        for col_idx, val in enumerate(vals, start=1):
            ws_all.cell(row=row_num, column=col_idx, value=val)
        _style_data_row(ws_all, row_num, len(ALL_COLS), tag)

    # ── Sheet 2: Daily Summary ────────────────────────────────────────────────
    ws_daily = wb[SH_DAILY]
    green_results  = [r for r in results if r.get("color_tag") == "GREEN"]
    yellow_results = [r for r in results if r.get("color_tag") == "YELLOW"]
    red_results    = [r for r in results if r.get("color_tag") == "RED"]

    green_syms  = ", ".join(r["symbol"] for r in green_results)
    yellow_syms = ", ".join(r["symbol"] for r in yellow_results)

    regime_price = nifty_regime.get("price", "") if nifty_regime else ""
    regime_rsi   = nifty_regime.get("rsi", "")   if nifty_regime else ""
    regime_ema20 = nifty_regime.get("ema_20", "") if nifty_regime else ""
    regime_ema50 = nifty_regime.get("ema_50", "") if nifty_regime else ""

    # Find existing row for today
    today_row = None
    for row in ws_daily.iter_rows(min_row=2):
        cell_val = row[0].value
        if cell_val and str(cell_val)[:10] == today_str:
            today_row = row[0].row
            break

    if today_row:
        # Upsert: update existing row
        existing_count = ws_daily.cell(row=today_row, column=2).value or 0
        ws_daily.cell(row=today_row, column=2).value = int(existing_count) + 1
        ws_daily.cell(row=today_row, column=3).value = len(results)
        ws_daily.cell(row=today_row, column=4).value = len(green_results)
        ws_daily.cell(row=today_row, column=5).value = len(yellow_results)
        ws_daily.cell(row=today_row, column=6).value = len(red_results)
        ws_daily.cell(row=today_row, column=7).value = regime_badge
        ws_daily.cell(row=today_row, column=8).value = regime_price
        ws_daily.cell(row=today_row, column=9).value = regime_rsi
        ws_daily.cell(row=today_row, column=10).value = regime_ema20
        ws_daily.cell(row=today_row, column=11).value = regime_ema50
        ws_daily.cell(row=today_row, column=12).value = green_syms
        ws_daily.cell(row=today_row, column=13).value = yellow_syms
    else:
        # Insert new row for today
        row_num = ws_daily.max_row + 1
        daily_vals = [
            today_str, 1, len(results),
            len(green_results), len(yellow_results), len(red_results),
            regime_badge, regime_price, regime_rsi, regime_ema20, regime_ema50,
            green_syms, yellow_syms,
        ]
        for col_idx, val in enumerate(daily_vals, start=1):
            cell = ws_daily.cell(row=row_num, column=col_idx, value=val)
            cell.font = _FONT_NORMAL
            cell.fill = _FILL_SUMMARY_TODAY
            cell.border = _THIN_BORDER
            cell.alignment = _ALIGN_LEFT if col_idx in (1, 7, 12, 13) else _ALIGN_CENTER

        # Style the counts with colors
        ws_daily.cell(row=row_num, column=4).font = _FONT_GREEN
        ws_daily.cell(row=row_num, column=5).font = _FONT_YELLOW
        ws_daily.cell(row=row_num, column=6).font = _FONT_RED
        ws_daily.row_dimensions[row_num].height = 20

    # Refresh auto-filter range
    ws_daily.auto_filter.ref = f"A1:{get_column_letter(len(DAILY_COLS))}{ws_daily.max_row}"

    # ── Sheet 3: Top Picks History ────────────────────────────────────────────
    ws_picks = wb[SH_PICKS]
    for r in green_results:
        row_num = ws_picks.max_row + 1
        pick_vals = [
            scan_dt_label, scan_date_label, r.get("symbol",""),
            r.get("action_status",""), r.get("price", 0),
            r.get("daily_change_pct", 0), r.get("rsi", 0),
            r.get("buy_range",""), r.get("stop_loss", 0),
            r.get("risk_pct", 0), r.get("target_1", 0),
            r.get("target_1_pct", 0), r.get("target_2", 0),
            r.get("target_3", 0), r.get("risk_reward_to_target1", 0),
            r.get("score", 0), regime_badge, r.get("reasons",""),
        ]
        for col_idx, val in enumerate(pick_vals, start=1):
            ws_picks.cell(row=row_num, column=col_idx, value=val)
        _style_data_row(ws_picks, row_num, len(PICKS_COLS), "GREEN")

    ws_picks.auto_filter.ref = f"A1:{get_column_letter(len(PICKS_COLS))}{ws_picks.max_row}"

    wb.save(excel_path)
    return excel_path


# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND SCAN
# ══════════════════════════════════════════════════════════════════════════════

def _run_scan_background(config_override=None):
    global _scan_log
    _scan_log = []

    def log(msg, typ="info"):
        _scan_log.append({"type": typ, "message": msg, "ts": datetime.now().strftime("%H:%M:%S")})

    try:
        with _scan_lock:
            _scan_state.update({
                "running": True, "status": "running", "progress": 0, "total": 0,
                "current_symbol": "", "message": "Initializing scan...",
                "started_at": datetime.now().isoformat(), "finished_at": None, "result_file": None
            })

        log("Loading configuration...")
        c = config_override if config_override else scanner.load_config()
        u, s, o = c["universe"], c["strategy"], c["output"]

        log("Resolving symbol universe...")
        symbols = scanner.resolve_symbols(u)
        if not symbols:
            raise ValueError("No symbols resolved. Check config indices.")

        with _scan_lock:
            _scan_state["total"] = len(symbols)
            _scan_state["message"] = f"Resolved {len(symbols)} symbols. Fetching NIFTY 50 regime..."

        log(f"Resolved {len(symbols)} symbols.", "progress")

        nifty_regime = scanner.fetch_nifty_regime(u)
        if nifty_regime:
            log(f"NIFTY 50: {nifty_regime['badge']} | Rs.{nifty_regime['price']:,.2f} | RSI {nifty_regime['rsi']}", "regime")

        with _scan_lock:
            _scan_state["message"] = f"Downloading market data for {len(symbols)} stocks..."

        import yfinance as yf
        import pandas as pd

        batch_size = 75
        results, errors = [], []
        start_time = time.time()
        analyzed = 0
        total_batches = (len(symbols) + batch_size - 1) // batch_size

        for start_idx in range(0, len(symbols), batch_size):
            chunk = symbols[start_idx:start_idx + batch_size]
            ticker_map = {sym: (sym if "." in sym else sym + u["exchange_suffix"]) for sym in chunk}
            download_list = list(ticker_map.values())
            batch_num = start_idx // batch_size + 1

            log(f"Downloading batch {batch_num}/{total_batches} ({len(chunk)} symbols)...", "progress")
            with _scan_lock:
                _scan_state["message"] = f"Downloading batch {batch_num}/{total_batches}..."

            try:
                batch_df = scanner.fetch_batch_data(download_list, u["history_period"], u["interval"])
                for sym, ticker in ticker_map.items():
                    try:
                        if isinstance(batch_df.columns, pd.MultiIndex):
                            raw_df = batch_df[ticker].dropna(how="all") if ticker in batch_df.columns.levels[0] else pd.DataFrame()
                        elif ticker in batch_df:
                            raw_df = batch_df[ticker].dropna(how="all")
                        else:
                            raw_df = batch_df.dropna(how="all")
                        if not raw_df.empty and "Close" in raw_df.columns:
                            x = scanner.analyze(sym, raw_df, c)
                            if x:
                                results.append(x)
                    except Exception as ex:
                        errors.append({"symbol": sym, "error": str(ex)})
                    analyzed += 1
                    with _scan_lock:
                        _scan_state["progress"] = analyzed
                        _scan_state["current_symbol"] = sym
            except Exception as batch_ex:
                log(f"Batch {batch_num} failed, using fallback: {batch_ex}", "warning")
                for sym, ticker in ticker_map.items():
                    try:
                        raw_df = yf.Ticker(ticker).history(period=u["history_period"], interval=u["interval"], auto_adjust=False)
                        x = scanner.analyze(sym, raw_df, c)
                        if x:
                            results.append(x)
                    except Exception as ex:
                        errors.append({"symbol": sym, "error": str(ex)})
                    analyzed += 1
                    with _scan_lock:
                        _scan_state["progress"] = analyzed
                        _scan_state["current_symbol"] = sym

        elapsed = time.time() - start_time
        log(f"Scan completed in {elapsed:.1f}s — {len(results)} results passed filters.", "done")

        # Sort: GREEN > YELLOW > RED, then score desc
        results.sort(key=lambda x: (
            0 if x["color_tag"] == "GREEN" else (1 if x["color_tag"] == "YELLOW" else 2),
            -x["score"], -x["risk_reward_to_target1"]
        ))

        out = BASE_DIR / o["directory"]
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        scan_payload = {
            "timestamp": stamp,
            "scanned_at": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "market_regime": nifty_regime,
            "total_screened": len(results),
            "total_errors": len(errors),
            "results": results
        }

        # ── 1. Always-overwrite JSON (web API reads this) ──────────────────
        (out / "latest_scan.json").write_text(json.dumps(scan_payload, indent=2), encoding="utf-8")

        # ── 2. Per-scan JSON only (for History panel — small, no CSV/HTML) ──
        json_fname = f"swing_scan_{stamp}.json"
        (out / json_fname).write_text(json.dumps(scan_payload, indent=2), encoding="utf-8")
        log(f"Saved JSON snapshot: {json_fname}", "progress")

        # ── 3. Always-overwrite HTML report ───────────────────────────────
        import pandas as pd
        df = pd.DataFrame(results)
        if not df.empty:
            scanner.generate_html_dashboard(
                results, c,
                str(out / "latest_scan.html"),   # ← only this one file, no timestamped copy
                None,                             # ← no "latest" copy needed (same file)
                nifty_regime=nifty_regime
            )
            log("Updated latest_scan.html", "progress")

            # ── 4. Append to master Excel workbook (3 sheets) ─────────────
            log("Writing to master_scan.xlsx (3 sheets)...", "progress")
            excel_path = append_to_excel(results, nifty_regime, stamp, out)
            log(f"Excel updated: {excel_path.name} — All Scans, Daily Summary, Top Picks", "done")

        if errors:
            err_fname = f"errors_{stamp}.json"
            (out / err_fname).write_text(json.dumps(errors, indent=2), encoding="utf-8")
            log(f"Logged {len(errors)} errors to {err_fname}", "warning")

        with _scan_lock:
            _scan_state.update({
                "running": False, "status": "done",
                "message": f"Scan complete! {len(results)} results in {elapsed:.1f}s. Excel updated.",
                "finished_at": datetime.now().isoformat(),
                "result_file": json_fname,
                "progress": len(symbols),
            })

    except Exception as e:
        import traceback
        err_msg = f"Scan error: {e}"
        log(err_msg, "error")
        log(traceback.format_exc(), "error")
        with _scan_lock:
            _scan_state.update({
                "running": False, "status": "error", "message": err_msg,
                "finished_at": datetime.now().isoformat()
            })


# ══════════════════════════════════════════════════════════════════════════════
# REST API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ─── CONFIG ────────────────────────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        return jsonify({"ok": True, "config": scanner.load_config()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config", methods=["POST", "OPTIONS"])
def save_config():
    if request.method == "OPTIONS":
        return "", 204
    try:
        new_cfg = request.get_json(force=True)
        if not new_cfg:
            return jsonify({"ok": False, "error": "Empty body"}), 400
        with scanner.CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(new_cfg, f, indent=2)
        return jsonify({"ok": True, "message": "Config saved successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─── INDICES ──────────────────────────────────────────────────────────────────
@app.route("/api/indices", methods=["GET"])
def list_indices():
    return jsonify({"ok": True, "indices": list(scanner.INDEX_MAPPINGS.keys())})

# ─── NIFTY REGIME ─────────────────────────────────────────────────────────────
@app.route("/api/nifty-regime", methods=["GET"])
def nifty_regime_api():
    try:
        cfg = scanner.load_config()
        regime = scanner.fetch_nifty_regime(cfg["universe"])
        return jsonify({"ok": True, "regime": regime})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─── SCAN ─────────────────────────────────────────────────────────────────────
@app.route("/api/scan", methods=["POST", "OPTIONS"])
def trigger_scan():
    if request.method == "OPTIONS":
        return "", 204
    with _scan_lock:
        if _scan_state["running"]:
            return jsonify({"ok": False, "error": "A scan is already running."}), 409
    config_override = None
    body = request.get_json(force=True, silent=True)
    if body and "config" in body:
        config_override = body["config"]
    t = threading.Thread(target=_run_scan_background, args=(config_override,), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Scan started"})


@app.route("/api/scan/status", methods=["GET"])
def scan_status():
    with _scan_lock:
        state_copy = dict(_scan_state)
    state_copy["log"] = list(_scan_log[-50:])
    return jsonify({"ok": True, "scan": state_copy})


@app.route("/api/scan/stream", methods=["GET"])
def scan_stream():
    def generate():
        last_len = 0
        while True:
            with _scan_lock:
                state = dict(_scan_state)
            new_logs = _scan_log[last_len:]
            last_len = len(_scan_log)
            yield _sse_event({"state": state, "new_logs": new_logs})
            if state["status"] in ("done", "error") and not state["running"]:
                yield _sse_event({"state": state, "new_logs": [], "done": True})
                break
            time.sleep(1)
    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

# ─── RESULTS ──────────────────────────────────────────────────────────────────
@app.route("/api/results/latest", methods=["GET"])
def get_latest_results():
    try:
        latest = BASE_DIR / "scanner_results" / "latest_scan.json"
        if not latest.exists():
            return jsonify({"ok": True, "data": None, "message": "No scan results yet."})
        return jsonify({"ok": True, "data": json.loads(latest.read_text(encoding="utf-8"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/results/history", methods=["GET"])
def get_history():
    try:
        results_dir = BASE_DIR / "scanner_results"
        files = sorted(results_dir.glob("swing_scan_*.json"), reverse=True)
        history = []
        for f in files[:30]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rs = data.get("results", [])
                history.append({
                    "filename": f.name,
                    "timestamp": data.get("timestamp", f.stem),
                    "scanned_at": data.get("scanned_at", ""),
                    "total": data.get("total_screened", len(rs)),
                    "green": sum(1 for r in rs if r.get("color_tag") == "GREEN"),
                    "yellow": sum(1 for r in rs if r.get("color_tag") == "YELLOW"),
                    "red": sum(1 for r in rs if r.get("color_tag") == "RED"),
                    "elapsed": data.get("elapsed_seconds", 0)
                })
            except Exception:
                pass
        return jsonify({"ok": True, "history": history})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/results/<filename>", methods=["GET"])
def get_result_file(filename):
    try:
        fpath = BASE_DIR / "scanner_results" / filename
        if not fpath.exists() or not filename.endswith(".json"):
            return jsonify({"ok": False, "error": "File not found"}), 404
        return jsonify({"ok": True, "data": json.loads(fpath.read_text(encoding="utf-8"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/results/export/csv", methods=["GET"])
def export_csv():
    """Return the latest_scan.csv if it exists, else the Excel file."""
    try:
        csv_path = BASE_DIR / "scanner_results" / "latest_scan.csv"
        if csv_path.exists():
            return send_from_directory(str(BASE_DIR / "scanner_results"), "latest_scan.csv",
                                       as_attachment=True, download_name="swing_scan_latest.csv")
        return jsonify({"ok": False, "error": "No CSV available. Use the Excel file."}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/results/export/excel", methods=["GET"])
def export_excel():
    """Download the master Excel workbook."""
    try:
        xlsx_path = BASE_DIR / "scanner_results" / _EXCEL_FILE
        if not xlsx_path.exists():
            return jsonify({"ok": False, "error": "No Excel file yet. Run a scan first."}), 404
        return send_from_directory(str(BASE_DIR / "scanner_results"), _EXCEL_FILE,
                                   as_attachment=True, download_name="NSE_SwingScan_Master.xlsx")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 60)
    print("  ⚡ NSE Swing Scanner — Web Application Server")
    print("  Open: http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
