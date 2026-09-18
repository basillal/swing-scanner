#!/usr/bin/env python3
import json, sys, time, argparse, io
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "swing_scanner_config.json"
CACHE_DIR = BASE_DIR / "cache" / "indices"

INDEX_MAPPINGS = {
    "NIFTY_50": "ind_nifty50list.csv",
    "NIFTY_NEXT_50": "ind_niftynext50list.csv",
    "NIFTY_100": "ind_nifty100list.csv",
    "NIFTY_200": "ind_nifty200list.csv",
    "NIFTY_500": "ind_nifty500list.csv",
    "BANK_NIFTY": "ind_niftybanklist.csv",
    "NIFTY_BANK": "ind_niftybanklist.csv",
    "NIFTY_MIDCAP_100": "ind_niftymidcap100list.csv",
    "NIFTY_SMALLCAP_100": "ind_niftysmallcap100list.csv",
    "NIFTY_IT": "ind_niftyitlist.csv",
    "NIFTY_AUTO": "ind_niftyautolist.csv",
    "NIFTY_PHARMA": "ind_niftypharmalist.csv",
    "NIFTY_FMCG": "ind_niftyfmcglist.csv",
    "NIFTY_METAL": "ind_niftymetallist.csv",
    "NIFTY_REALTY": "ind_niftyrealtylist.csv",
    "NIFTY_ENERGY": "ind_niftyenergylist.csv",
    "NIFTY_INFRA": "ind_niftyinfralist.csv",
}

class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    BOLD_GREEN = "\033[1;92m"
    YELLOW = "\033[93m"
    BOLD_YELLOW = "\033[1;93m"
    RED = "\033[91m"
    BOLD_RED = "\033[1;91m"
    CYAN = "\033[96m"
    BOLD_CYAN = "\033[1;96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def fetch_index_symbols(index_name, force_refresh=False):
    """Fetch constituent symbols for a given NSE index with local caching."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    norm_name = index_name.strip().upper().replace(" ", "_").replace("-", "_")
    csv_file = INDEX_MAPPINGS.get(norm_name, f"ind_{norm_name.lower()}list.csv")
    cache_path = CACHE_DIR / csv_file

    max_cache_age_seconds = 7 * 86400  # 7 days
    cached_valid = cache_path.exists() and (
        (time.time() - cache_path.stat().st_mtime) < max_cache_age_seconds
    )

    if not cached_valid or force_refresh:
        url = f"https://archives.nseindia.com/content/indices/{csv_file}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and len(r.text) > 50:
                cache_path.write_text(r.text, encoding="utf-8")
            else:
                print(f"[Warning] Failed downloading {norm_name} from NSE (HTTP {r.status_code}).")
        except Exception as e:
            print(f"[Warning] Network error fetching {norm_name}: {e}")

    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path)
            sym_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
            if sym_col:
                symbols = [str(s).strip().upper() for s in df[sym_col].dropna() if str(s).strip()]
                return symbols
        except Exception as e:
            print(f"[Error] Failed reading cached CSV for {norm_name}: {e}")
    else:
        print(f"[Warning] No cache or data available for index '{index_name}'.")
    return []

def resolve_symbols(universe_cfg, override_indices=None, force_refresh=False):
    """Combine index constituents, custom symbols, and direct symbols into a deduplicated list."""
    symbols = []
    indices = override_indices if override_indices is not None else universe_cfg.get("indices", [])
    
    if any(str(idx).strip().upper() == "ALL" for idx in indices):
        print(f"Loading constituent symbols from ALL cached index lists in {CACHE_DIR}...")
        for csv_file in sorted(CACHE_DIR.glob("*.csv")):
            try:
                df = pd.read_csv(csv_file)
                sym_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
                if sym_col:
                    s_list = [str(s).strip().upper() for s in df[sym_col].dropna() if str(s).strip()]
                    symbols.extend(s_list)
            except Exception as ex:
                print(f"[Warning] Failed reading {csv_file.name}: {ex}")
    else:
        for idx in indices:
            idx_symbols = fetch_index_symbols(idx, force_refresh=force_refresh)
            if idx_symbols:
                print(f"Loaded {len(idx_symbols)} symbols from {idx}")
                symbols.extend(idx_symbols)
            else:
                print(f"0 symbols resolved for {idx}")

    custom = universe_cfg.get("custom_symbols", [])
    if custom:
        symbols.extend(custom)

    legacy = universe_cfg.get("symbols", [])
    if legacy:
        symbols.extend(legacy)

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for s in symbols:
        clean = str(s).strip().upper()
        if clean and clean not in seen:
            seen.add(clean)
            deduped.append(clean)
    return deduped

def rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    al = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return (100 - 100/(1 + ag/al.replace(0, np.nan))).fillna(50)

def atr(df, period):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def add_indicators(df, c):
    i = c["indicators"]
    df[f"EMA_{i['ema_fast']}"] = df["Close"].ewm(span=i["ema_fast"], adjust=False).mean()
    df[f"EMA_{i['ema_slow']}"] = df["Close"].ewm(span=i["ema_slow"], adjust=False).mean()
    df[f"EMA_{i['ema_long']}"] = df["Close"].ewm(span=i["ema_long"], adjust=False).mean()
    df["RSI"] = rsi(df["Close"], i["rsi_period"])
    fast = df["Close"].ewm(span=i["macd_fast"], adjust=False).mean()
    slow = df["Close"].ewm(span=i["macd_slow"], adjust=False).mean()
    df["MACD"] = fast - slow
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=i["macd_signal"], adjust=False).mean()
    df["ATR"] = atr(df, i["atr_period"])
    df["AVG_VOLUME"] = df["Volume"].rolling(i["volume_average_period"]).mean()
    df["VOLUME_RATIO"] = df["Volume"] / df["AVG_VOLUME"].replace(0, np.nan)
    return df

def analyze(symbol, raw, c):
    if raw is None or raw.empty:
        return None
    df = add_indicators(raw.copy(), c)
    s, i, r = c["strategy"], c["indicators"], c["risk_management"]
    sr = c["support_resistance"]
    need = max(i["ema_long"], i["macd_slow"] + i["macd_signal"],
               i["volume_average_period"], sr["lookback"]) + 5
    if len(df) < need:
        return None

    last, prev = df.iloc[-1], df.iloc[-2]
    p = float(last["Close"])
    if not s["min_price"] <= p <= s["max_price"]:
        return None

    ef, es, el = [float(last[f"EMA_{x}"]) for x in
                  (i["ema_fast"], i["ema_slow"], i["ema_long"])]
    rv, mv, ms = float(last["RSI"]), float(last["MACD"]), float(last["MACD_SIGNAL"])
    vr = float(last["VOLUME_RATIO"]) if np.isfinite(last["VOLUME_RATIO"]) else 0
    av = float(last["ATR"]) if np.isfinite(last["ATR"]) else 0

    recent = df.tail(sr["lookback"])
    support, resistance = float(recent["Low"].min()), float(recent["High"].max())

    score, reasons = 0.0, []
    w = s["weights"]
    if p > ef: score += w["price_above_fast_ema"]; reasons.append("Price > fast EMA")
    if ef > es: score += w["fast_ema_above_slow_ema"]; reasons.append("Fast EMA > slow EMA")
    if p > el: score += w["price_above_long_ema"]; reasons.append("Price > long EMA")
    if s["rsi_buy_min"] <= rv <= s["rsi_buy_max"]:
        score += w["rsi_in_buy_zone"]; reasons.append("RSI bullish zone")
    elif rv > s["rsi_overbought"]:
        score -= w["rsi_overbought_penalty"]; reasons.append("RSI overbought")
    if mv > ms: score += w["macd_bullish"]; reasons.append("MACD bullish")
    if mv > 0: score += w["macd_above_zero"]; reasons.append("MACD > zero")
    if vr >= s["volume_ratio_min"]:
        score += w["volume_confirmation"]; reasons.append(f"Volume {vr:.1f}x average")

    breakout = p >= resistance * (1 + s["breakout_buffer_percent"] / 100)
    if breakout:
        score += w["breakout"]; reasons.append("Resistance breakout")

    near_support = p <= support * (1 + s["support_entry_buffer_percent"] / 100)
    if near_support:
        score += w["near_support"]; reasons.append("Near support")

    daily_change = (p / float(prev["Close"]) - 1) * 100
    if daily_change >= s["daily_gain_confirmation_percent"]:
        score += w["daily_gain_confirmation"]; reasons.append("Positive daily momentum")

    score = max(0, min(score, s["max_score"]))
    stop = min(support * (1 - r["stop_below_support_percent"] / 100),
               p - av * r["stop_atr_multiplier"])
    if stop >= p:
        stop = p * (1 - r["fallback_stop_percent"] / 100)
    risk = max(p - stop, 0.01)
    targets = [p + risk * x for x in r["target_r_multiples"]]
    rr = (targets[0] - p) / risk

    risk_pct = round(((p - stop) / p) * 100, 2)
    t1_pct = round(((targets[0] - p) / p) * 100, 2)
    t2_pct = round(((targets[1] - p) / p) * 100, 2)
    t3_pct = round(((targets[2] - p) / p) * 100, 2)

    max_low_risk = float(r.get("max_low_risk_percent", 4.0))
    max_mod_risk = float(r.get("max_moderate_risk_percent", 6.5))
    min_rr = float(r.get("min_reward_risk_ratio", 1.5))
    rsi_ob_warn = float(r.get("rsi_overbought_warning", 68.0))
    rsi_high_risk = float(r.get("rsi_high_risk", 72.0))

    if score >= s["buy_score_min"] and (
        breakout or (p > ef and ef > es and rv >= s["rsi_buy_min"])
    ):
        base_signal = "BUY"
    elif score >= s["watch_score_min"]:
        base_signal = "WATCH"
    else:
        base_signal = "AVOID"

    # Multi-factor Risk & Condition Assessment
    risk_warnings = []
    if risk_pct > max_mod_risk:
        risk_warnings.append(f"Stop-loss distance {risk_pct}% exceeds max risk threshold ({max_mod_risk}%)")
    if rv >= rsi_high_risk:
        risk_warnings.append(f"RSI dangerously overbought ({rv:.1f} >= {rsi_high_risk})")
    if p < el:
        risk_warnings.append(f"Price below {i['ema_long']} EMA (downtrend)")
    if rr < 1.0:
        risk_warnings.append(f"Poor Risk/Reward ratio ({rr:.2f} < 1.0)")

    is_too_much_risk = len(risk_warnings) > 0
    is_low_risk = (not is_too_much_risk) and (risk_pct <= max_low_risk) and (rv <= rsi_ob_warn) and (rr >= min_rr) and (p > el)

    if is_too_much_risk:
        risk_level = "HIGH"
        color_tag = "RED"
        signal = "AVOID"
        action_status = "HIGH RISK (AVOID)"
        reasons.extend([f"TOO MUCH RISK: {w}" for w in risk_warnings])
    elif base_signal == "BUY":
        if is_low_risk:
            risk_level = "LOW"
            color_tag = "GREEN"
            signal = "BUY"
            action_status = "BUY NOW (PRIME SETUP)"
        else:
            risk_level = "MODERATE"
            color_tag = "YELLOW"
            signal = "BUY"
            action_status = "BUY (MODERATE RISK)"
    elif base_signal == "WATCH":
        risk_level = "LOW" if (risk_pct <= max_low_risk and p > el) else "MODERATE"
        color_tag = "YELLOW"
        signal = "WATCH"
        action_status = "WATCHLIST"
    else:
        risk_level = "LOW" if risk_pct <= max_low_risk else "MODERATE"
        color_tag = "RED"
        signal = "AVOID"
        action_status = "AVOID (LOW SCORE)"

    d = s["price_decimals"]
    rd = lambda x: round(float(x), d)

    # Calculate Practical Buying Range / Buy Zone:
    if breakout:
        # Breakout setup: Enter between breakout trigger (resistance) and current price / +0.5% buffer
        b_low = max(resistance, p * 0.995)
        b_high = max(p, resistance * (1 + s.get("breakout_buffer_percent", 0.5) / 100))
    elif near_support:
        # Support bounce setup: Enter near support floor up to support buffer (+1.5%)
        b_low = support
        b_high = min(p, support * (1 + s.get("support_entry_buffer_percent", 1.5) / 100))
    else:
        # Trend/EMA Momentum: Optimal entry on a mild dip towards fast EMA or up to current price
        b_low = max(ef, p * 0.985)
        b_high = p * 1.005

    if b_low > b_high:
        b_low, b_high = b_high, b_low
    b_low = max(b_low, stop)

    entry_low = rd(b_low)
    entry_high = rd(b_high)
    buy_range = f"₹{entry_low:,.2f} – ₹{entry_high:,.2f}"

    return {
        "symbol": symbol, "date": str(df.index[-1].date()), "price": rd(p),
        "daily_change_pct": round(daily_change, 2), "rsi": round(rv, 2),
        f"ema_{i['ema_fast']}": rd(ef), f"ema_{i['ema_slow']}": rd(es),
        f"ema_{i['ema_long']}": rd(el), "macd": round(mv, 4),
        "macd_signal": round(ms, 4), "volume_ratio": round(vr, 2),
        "support": rd(support), "resistance": rd(resistance), "atr": rd(av),
        "entry_low": entry_low, "entry_high": entry_high, "buy_range": buy_range,
        "stop_loss": rd(stop), "risk_pct": risk_pct,
        "target_1": rd(targets[0]), "target_1_pct": t1_pct,
        "target_2": rd(targets[1]), "target_2_pct": t2_pct,
        "target_3": rd(targets[2]), "target_3_pct": t3_pct,
        "risk_reward_to_target1": round(rr, 2), "score": round(score, 2),
        "max_score": s["max_score"], "signal": signal,
        "risk_level": risk_level, "action_status": action_status, "color_tag": color_tag,
        "breakout": breakout, "reasons": "; ".join(reasons)
    }

def fetch_batch_data(tickers, history_period, interval):
    """Download historical price data in a multi-threaded batch."""
    return yf.download(
        tickers,
        period=history_period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False
    )

def fetch_nifty_regime(universe_cfg):
    """Analyze NIFTY 50 (^NSEI) index to determine overall broad market trend & regime."""
    try:
        df = yf.download("^NSEI", period="1y", interval="1d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"]["^NSEI"]
        else:
            close = df["Close"]
        close = close.dropna()
        if len(close) < 50:
            return None

        p = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        chg_pct = (p / prev - 1) * 100
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 200 else ema50
        rsi_val = float(rsi(close, 14).iloc[-1])

        if p > ema20 and ema20 > ema50 and p > ema200 and rsi_val >= 50:
            status = "BULLISH"
            color_tag = "GREEN"
            badge = "🟢 BULLISH REGIME"
            advice = "Strong market tailwinds. High success rate for swing breakouts. Full position sizing on Prime Buys."
        elif (p > ema50 or p > ema20) and p > ema200:
            status = "CAUTIOUS"
            color_tag = "YELLOW"
            badge = "🟡 RANGEBOUND / CAUTIOUS"
            advice = "Market consolidating near moving averages. Trade selectively with tighter stops and reduced sizing."
        else:
            status = "BEARISH"
            color_tag = "RED"
            badge = "🔴 BEARISH / CORRECTION"
            advice = "Market below key EMAs. High risk of failed breakouts. Prioritize capital preservation or strict defense."

        return {
            "symbol": "NIFTY 50",
            "ticker": "^NSEI",
            "price": round(p, 2),
            "daily_change_pct": round(chg_pct, 2),
            "ema_20": round(ema20, 2),
            "ema_50": round(ema50, 2),
            "ema_200": round(ema200, 2),
            "rsi": round(rsi_val, 1),
            "status": status,
            "color_tag": color_tag,
            "badge": badge,
            "advice": advice
        }
    except Exception as e:
        print(f"[Warning] Unable to fetch NIFTY 50 index regime: {e}")
        return None

def print_terminal_report(df, config, nifty_regime=None):
    """Print beautifully styled, color-coded scan results in the terminal."""
    if df.empty:
        print("No stocks matched the configured price range or criteria.")
        return

    c = ANSI
    green_df = df[df["color_tag"] == "GREEN"]
    yellow_df = df[df["color_tag"] == "YELLOW"]
    red_df = df[df["color_tag"] == "RED"]

    print(f"\n{c.BOLD_CYAN}{'=' * 125}{c.RESET}")
    print(f"  🎯 {c.BOLD}NSE SWING SCANNER — RISK & OPPORTUNITY REPORT{c.RESET}")
    print(f"{c.BOLD_CYAN}{'=' * 125}{c.RESET}")

    if nifty_regime:
        n_col = c.BOLD_GREEN if nifty_regime["color_tag"] == "GREEN" else (c.BOLD_YELLOW if nifty_regime["color_tag"] == "YELLOW" else c.BOLD_RED)
        n_p = f"₹{nifty_regime['price']:,.2f}"
        n_chg = f"{nifty_regime['daily_change_pct']:+.2f}%"
        print(f"  🌐 {c.BOLD}NIFTY 50 REGIME:{c.RESET} {n_col}{nifty_regime['badge']}{c.RESET} | Price: {n_p} ({n_chg}) | RSI: {nifty_regime['rsi']} | 20 EMA: ₹{nifty_regime['ema_20']:,.2f} | 50 EMA: ₹{nifty_regime['ema_50']:,.2f}")
        print(f"     {c.DIM}Guidance: {nifty_regime['advice']}{c.RESET}")
        print(f"{c.DIM}{'-' * 125}{c.RESET}")

    print(
        f"  Total Filtered: {len(df)} | "
        f"{c.BOLD_GREEN}🟢 PRIME BUYS: {len(green_df)}{c.RESET} | "
        f"{c.BOLD_YELLOW}🟡 WATCHLIST: {len(yellow_df)}{c.RESET} | "
        f"{c.BOLD_RED}🔴 HIGH RISK / AVOID: {len(red_df)}{c.RESET}"
    )
    print(f"{c.BOLD_CYAN}{'=' * 125}{c.RESET}\n")

    def format_row(r):
        tag = r.get("color_tag", "RED")
        if tag == "GREEN":
            sym_str = f"{c.BOLD_GREEN}{r['symbol']:<11}{c.RESET}"
            status_str = f"{c.BOLD_GREEN}{r['action_status']:<23}{c.RESET}"
        elif tag == "YELLOW":
            sym_str = f"{c.BOLD_YELLOW}{r['symbol']:<11}{c.RESET}"
            status_str = f"{c.BOLD_YELLOW}{r['action_status']:<23}{c.RESET}"
        else:
            sym_str = f"{c.BOLD_RED}{r['symbol']:<11}{c.RESET}"
            status_str = f"{c.BOLD_RED}{r['action_status']:<23}{c.RESET}"

        chg = r["daily_change_pct"]
        chg_fmt = f"{chg:+.2f}%"
        chg_str = f"{c.GREEN if chg >= 0 else c.RED}{chg_fmt:<8}{c.RESET}"

        rsi_val = r["rsi"]
        if rsi_val >= 70:
            rsi_str = f"{c.BOLD_RED}{rsi_val:>5.1f}{c.RESET}  "
        elif 50 <= rsi_val <= 68:
            rsi_str = f"{c.GREEN}{rsi_val:>5.1f}{c.RESET}  "
        else:
            rsi_str = f"{rsi_val:>5.1f}  "

        risk_pct = r["risk_pct"]
        if risk_pct <= 4.0:
            risk_str = f"{c.BOLD_GREEN}{risk_pct:>5.2f}%{c.RESET}  "
        elif risk_pct <= 6.5:
            risk_str = f"{c.BOLD_YELLOW}{risk_pct:>5.2f}%{c.RESET}  "
        else:
            risk_str = f"{c.BOLD_RED}{risk_pct:>5.2f}%{c.RESET}  "

        p = f"{r['price']:>9.2f}"
        buy_rng = f"{r.get('buy_range', ''):<21}"
        sl = f"{r['stop_loss']:>9.2f}"
        t1 = f"{r['target_1']:>9.2f}"
        rr = f"{r['risk_reward_to_target1']:>5.2f}"
        score = f"{r['score']:>4.1f}/{r['max_score']:<3.0f}"

        return f"{sym_str} {p}  {chg_str} {rsi_str} {c.CYAN}{buy_rng}{c.RESET} {sl}  {risk_str} {t1}  {rr}  {score}  {status_str}"

    header = (
        f"{c.BOLD}{'Symbol':<11} {'Price (₹)':>9}  {'Chg %':<8} {'RSI':>6}  "
        f"{'Buy Range (₹)':<21} {'Stop (₹)':>9}  {'Risk %':>7}  {'Target 1':>9}  {'R:R':>5}  {'Score':>8}  {'Action Status':<23}{c.RESET}"
    )
    divider = f"{c.DIM}{'-' * 145}{c.RESET}"

    actionable = pd.concat([green_df, yellow_df]) if not (green_df.empty and yellow_df.empty) else pd.DataFrame()
    if not actionable.empty:
        print(f"{c.BOLD_GREEN}✨ ACTIONABLE SETUPS (PRIME BUY & WATCHLIST):{c.RESET}")
        print(header)
        print(divider)
        for _, row in actionable.iterrows():
            print(format_row(row))
        print(divider + "\n")
    else:
        print(f"{c.YELLOW}⚡ No Prime Buys or Watchlist setups met the entry criteria today.{c.RESET}\n")

    if not red_df.empty:
        print(f"{c.BOLD_RED}⚠️  HIGH RISK & AVOID SETUPS (Top Scored Screened Out):{c.RESET}")
        print(header)
        print(divider)
        top_reds = red_df.head(10)
        for _, row in top_reds.iterrows():
            print(format_row(row))
        print(divider)
        if len(red_df) > 10:
            print(f"{c.DIM}... and {len(red_df) - 10} more avoided setups (saved to CSV and HTML report).{c.RESET}\n")

def generate_html_dashboard(results, config, html_path, latest_html_path=None, nifty_regime=None):
    """Generate modern, interactive dark-theme HTML report with risk badges and filters."""
    green_count = sum(1 for r in results if r.get("color_tag") == "GREEN")
    yellow_count = sum(1 for r in results if r.get("color_tag") == "YELLOW")
    red_count = sum(1 for r in results if r.get("color_tag") == "RED")
    total_count = len(results)
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    regime_html = ""
    if nifty_regime:
        n_tag = nifty_regime.get("color_tag", "YELLOW").lower()
        chg_cls = "text-green" if nifty_regime["daily_change_pct"] >= 0 else "text-red"
        regime_html = f"""
<div class="regime-card regime-{n_tag}">
  <div class="regime-header">
    <div class="regime-title-group">
      <span class="regime-pill pill-{n_tag}">{nifty_regime['badge']}</span>
      <span class="regime-symbol">NIFTY 50 (^NSEI)</span>
      <span class="regime-price">₹{nifty_regime['price']:,.2f} <span class="{chg_cls} font-bold">({nifty_regime['daily_change_pct']:+.2f}%)</span></span>
    </div>
    <div class="regime-indicators">
      <span class="ind-pill">RSI: <strong>{nifty_regime['rsi']}</strong></span>
      <span class="ind-pill">20 EMA: <strong>₹{nifty_regime['ema_20']:,.2f}</strong></span>
      <span class="ind-pill">50 EMA: <strong>₹{nifty_regime['ema_50']:,.2f}</strong></span>
      <span class="ind-pill">200 EMA: <strong>₹{nifty_regime['ema_200']:,.2f}</strong></span>
    </div>
  </div>
  <div class="regime-advice">
    <strong>Market Trend Context:</strong> {nifty_regime['advice']}
  </div>
</div>
"""

    rows_html = []
    for r in results:
        tag = r.get("color_tag", "RED")
        status = r.get("action_status", "AVOID")
        badge_class = f"badge-{tag.lower()}"

        chg = r.get("daily_change_pct", 0.0)
        chg_class = "text-green" if chg >= 0 else "text-red"
        chg_str = f"{chg:+.2f}%"

        risk_pct = r.get("risk_pct", 0.0)
        if risk_pct <= 4.0:
            risk_class = "risk-low"
            risk_label = "Low"
        elif risk_pct <= 6.5:
            risk_class = "risk-mod"
            risk_label = "Moderate"
        else:
            risk_class = "risk-high"
            risk_label = "High Risk"

        rsi_val = r.get("rsi", 50.0)
        if rsi_val >= 70:
            rsi_class = "rsi-hot"
        elif 50 <= rsi_val <= 68:
            rsi_class = "rsi-good"
        else:
            rsi_class = "rsi-neutral"

        reasons = r.get("reasons", "")
        reasons_pills = "".join([f'<span class="reason-pill">{item.strip()}</span>' for item in reasons.split(";") if item.strip()])

        score = r.get("score", 0.0)
        max_score = r.get("max_score", 10.0)
        score_pct = min(100, int((score / max_score) * 100))

        sym = r.get("symbol", "")
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

        rows_html.append(f"""
        <tr class="scan-row" data-color="{tag}" data-symbol="{sym.upper()}">
            <td>
                <span class="status-badge {badge_class}">{status}</span>
            </td>
            <td>
                <div class="symbol-cell">
                    <span class="symbol-name">{sym}</span>
                    <a href="{tv_url}" target="_blank" rel="noopener noreferrer" class="tv-btn" title="Open TradingView Chart">Chart ↗</a>
                </div>
            </td>
            <td class="num-cell">₹{r.get('price', 0):,.2f}</td>
            <td class="num-cell {chg_class} font-bold">{chg_str}</td>
            <td class="num-cell">
                <span class="rsi-badge {rsi_class}">{rsi_val:.1f}</span>
            </td>
            <td class="num-cell">
                <span class="buy-range-pill">{r.get('buy_range', f'₹{r.get("entry_low", 0):,.2f} – ₹{r.get("entry_high", 0):,.2f}')}</span>
            </td>
            <td class="num-cell">₹{r.get('stop_loss', 0):,.2f}</td>
            <td class="num-cell">
                <span class="risk-badge {risk_class}">{risk_pct:.2f}% ({risk_label})</span>
            </td>
            <td class="num-cell text-green font-bold">
                ₹{r.get('target_1', 0):,.2f}
                <span class="target-pct">+{r.get('target_1_pct', 0):.1f}%</span>
            </td>
            <td class="num-cell">{r.get('risk_reward_to_target1', 0):.2f}</td>
            <td class="num-cell">
                <div class="score-container">
                    <span class="score-val">{score:.1f}</span>
                    <div class="score-bar-bg"><div class="score-bar-fill" style="width: {score_pct}%;"></div></div>
                </div>
            </td>
            <td>
                <div class="reasons-container">{reasons_pills}</div>
            </td>
        </tr>
        """)

    table_body = "\n".join(rows_html)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Swing Scanner | Risk & Opportunity Intelligence</title>
<style>
  :root {{
    --bg: #090d16;
    --card-bg: #131b2e;
    --card-hover: #18223a;
    --border: #232f48;
    --text-main: #f1f5f9;
    --text-muted: #94a3b8;
    --green: #10b981;
    --green-bg: rgba(16, 185, 129, 0.15);
    --green-border: #059669;
    --yellow: #f59e0b;
    --yellow-bg: rgba(245, 158, 11, 0.15);
    --yellow-border: #d97706;
    --red: #ef4444;
    --red-bg: rgba(239, 68, 68, 0.15);
    --red-border: #dc2626;
    --cyan: #06b6d4;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background-color: var(--bg);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    padding: 24px;
    line-height: 1.5;
  }}

  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 24px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }}

  .header-left h1 {{
    font-size: 24px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .header-left p {{
    color: var(--text-muted);
    font-size: 13px;
    margin-top: 4px;
  }}

  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}

  .kpi-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    transition: transform 0.2s, border-color 0.2s;
  }}
  .kpi-card:hover {{
    transform: translateY(-2px);
    border-color: #3b82f6;
  }}

  .kpi-title {{
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .kpi-val {{
    font-size: 28px;
    font-weight: 800;
  }}

  .kpi-val.green {{ color: var(--green); }}
  .kpi-val.yellow {{ color: var(--yellow); }}
  .kpi-val.red {{ color: var(--red); }}

  .controls {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 14px;
    margin-bottom: 20px;
  }}

  .tabs {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}

  .tab-btn {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    color: var(--text-muted);
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }}

  .tab-btn:hover {{
    color: var(--text-main);
    border-color: #475569;
  }}

  .tab-btn.active {{
    background: #1e293b;
    color: var(--text-main);
    border-color: #3b82f6;
  }}

  .tab-btn.tab-green.active {{
    border-color: var(--green);
    color: #34d399;
    background: var(--green-bg);
  }}

  .tab-btn.tab-yellow.active {{
    border-color: var(--yellow);
    color: #fbbf24;
    background: var(--yellow-bg);
  }}

  .tab-btn.tab-red.active {{
    border-color: var(--red);
    color: #f87171;
    background: var(--red-bg);
  }}

  .search-box {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 14px;
    color: var(--text-main);
    font-size: 13px;
    width: 260px;
    outline: none;
    transition: border-color 0.2s;
  }}
  .search-box:focus {{
    border-color: #3b82f6;
  }}

  .table-container {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow-x: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    text-align: left;
  }}

  th {{
    background: #0f172a;
    color: var(--text-muted);
    font-weight: 600;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    user-select: none;
  }}

  td {{
    padding: 12px 16px;
    border-bottom: 1px solid #1a253a;
    vertical-align: middle;
  }}

  tr.scan-row:hover td {{
    background-color: var(--card-hover);
  }}

  .num-cell {{
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  th.num-cell {{ text-align: right; }}

  .symbol-cell {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .symbol-name {{
    font-weight: 700;
    font-size: 14px;
    color: #ffffff;
    letter-spacing: 0.5px;
  }}

  .tv-btn {{
    font-size: 11px;
    color: #38bdf8;
    background: rgba(56, 189, 248, 0.1);
    border: 1px solid rgba(56, 189, 248, 0.3);
    padding: 2px 7px;
    border-radius: 4px;
    text-decoration: none;
    font-weight: 600;
    transition: all 0.2s;
  }}
  .tv-btn:hover {{
    background: rgba(56, 189, 248, 0.25);
  }}

  .status-badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    white-space: nowrap;
  }}

  .badge-green {{
    background: var(--green-bg);
    color: #34d399;
    border: 1px solid var(--green-border);
  }}

  .badge-yellow {{
    background: var(--yellow-bg);
    color: #fbbf24;
    border: 1px solid var(--yellow-border);
  }}

  .badge-red {{
    background: var(--red-bg);
    color: #f87171;
    border: 1px solid var(--red-border);
  }}

  .risk-badge {{
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
  }}

  .risk-low {{
    background: rgba(16, 185, 129, 0.15);
    color: #34d399;
  }}

  .risk-mod {{
    background: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
  }}

  .risk-high {{
    background: rgba(239, 68, 68, 0.15);
    color: #f87171;
  }}

  .rsi-badge {{
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
  }}
  .rsi-good {{ color: #34d399; background: rgba(16, 185, 129, 0.12); }}
  .rsi-hot {{ color: #f87171; background: rgba(239, 68, 68, 0.15); font-weight: 700; }}
  .rsi-neutral {{ color: #cbd5e1; }}

  .score-container {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
  }}
  .score-val {{ font-weight: 700; }}
  .score-bar-bg {{
    width: 44px;
    height: 6px;
    background: #1e293b;
    border-radius: 3px;
    overflow: hidden;
  }}
  .score-bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, #3b82f6, #10b981);
    border-radius: 3px;
  }}

  .target-pct {{
    display: block;
    font-size: 11px;
    color: #34d399;
    font-weight: 500;
  }}

  .reasons-container {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    max-width: 400px;
  }}

  .reason-pill {{
    font-size: 11px;
    background: #1e293b;
    color: #94a3b8;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #334155;
    white-space: nowrap;
  }}

  .text-green {{ color: #34d399; }}
  .text-red {{ color: #f87171; }}
  .font-bold {{ font-weight: 700; }}

  .empty-state {{
    text-align: center;
    padding: 48px 16px;
    color: var(--text-muted);
    font-size: 15px;
    display: none;
  }}

  .buy-range-pill {{
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(6, 182, 212, 0.12);
    color: #38bdf8;
    border: 1px solid rgba(6, 182, 212, 0.3);
    white-space: nowrap;
  }}

  .regime-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 24px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .regime-card.regime-green {{ border-color: var(--green-border); background: rgba(16, 185, 129, 0.08); }}
  .regime-card.regime-yellow {{ border-color: var(--yellow-border); background: rgba(245, 158, 11, 0.08); }}
  .regime-card.regime-red {{ border-color: var(--red-border); background: rgba(239, 68, 68, 0.08); }}

  .regime-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .regime-title-group {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .regime-pill {{
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.5px;
  }}
  .pill-green {{ background: var(--green-bg); color: #34d399; border: 1px solid var(--green-border); }}
  .pill-yellow {{ background: var(--yellow-bg); color: #fbbf24; border: 1px solid var(--yellow-border); }}
  .pill-red {{ background: var(--red-bg); color: #f87171; border: 1px solid var(--red-border); }}

  .regime-symbol {{ font-size: 15px; font-weight: 700; color: #fff; }}
  .regime-price {{ font-size: 15px; font-weight: 600; color: #e2e8f0; }}

  .regime-indicators {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .ind-pill {{
    background: #0f172a;
    border: 1px solid var(--border);
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 12px;
    color: var(--text-muted);
  }}
  .ind-pill strong {{ color: var(--text-main); }}
  .regime-advice {{
    font-size: 13px;
    color: #cbd5e1;
    border-top: 1px solid rgba(255,255,255,0.08);
    padding-top: 8px;
  }}

  .header-right {{
    display: flex;
    align-items: center;
    gap: 16px;
  }}

  .refresh-panel {{
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    padding: 8px 16px;
    border-radius: 10px;
    font-size: 12px;
  }}

  .scan-time {{
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
  }}
  .scan-time strong {{ color: #f1f5f9; }}

  .live-dot {{
    width: 8px;
    height: 8px;
    background: #10b981;
    border-radius: 50%;
    box-shadow: 0 0 8px #10b981;
    display: inline-block;
    animation: pulse 2s infinite;
  }}
  @keyframes pulse {{
    0% {{ transform: scale(0.95); opacity: 0.8; }}
    50% {{ transform: scale(1.2); opacity: 1; }}
    100% {{ transform: scale(0.95); opacity: 0.8; }}
  }}

  .auto-refresh-wrap {{
    display: flex;
    align-items: center;
    gap: 8px;
    border-left: 1px solid var(--border);
    padding-left: 12px;
  }}

  .toggle-switch {{
    position: relative;
    display: inline-block;
    width: 32px;
    height: 18px;
  }}
  .toggle-switch input {{ opacity: 0; width: 0; height: 0; }}
  .toggle-slider {{
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background-color: #334155;
    transition: .3s;
    border-radius: 18px;
  }}
  .toggle-slider:before {{
    position: absolute;
    content: "";
    height: 12px;
    width: 12px;
    left: 3px;
    bottom: 3px;
    background-color: white;
    transition: .3s;
    border-radius: 50%;
  }}
  input:checked + .toggle-slider {{ background-color: #10b981; }}
  input:checked + .toggle-slider:before {{ transform: translateX(14px); }}
  .refresh-label {{ font-weight: 600; color: #cbd5e1; }}
  .refresh-label span {{ color: #38bdf8; font-variant-numeric: tabular-nums; }}

  .manual-reload-btn {{
    background: #1e293b;
    border: 1px solid #334155;
    color: var(--text-main);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }}
  .manual-reload-btn:hover {{ background: #334155; border-color: #475569; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>⚡ NSE Swing Trading Scanner</h1>
    <p>Risk-Adjusted Technical Scanner • Color-Coded Execution Engine</p>
  </div>
  <div class="header-right">
    <div class="refresh-panel">
      <div class="scan-time">
        <span class="live-dot"></span> Last Scan: <strong>{scan_time}</strong>
      </div>
      <div class="auto-refresh-wrap">
        <label class="toggle-switch">
          <input type="checkbox" id="autoRefreshCheck" checked onchange="toggleAutoRefresh(this)">
          <span class="toggle-slider"></span>
        </label>
        <span class="refresh-label">Auto-Update: <span id="refreshTimer">30s</span></span>
        <button class="manual-reload-btn" onclick="location.reload()" title="Refresh Page Now">🔄 Refresh</button>
      </div>
    </div>
  </div>
</div>

{regime_html}

<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-title">Total Analyzed</div>
    <div class="kpi-val">{total_count}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-title">🟢 Prime Buys (Low Risk)</div>
    <div class="kpi-val green">{green_count}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-title">🟡 Watchlist Setups</div>
    <div class="kpi-val yellow">{yellow_count}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-title">🔴 High Risk / Avoid</div>
    <div class="kpi-val red">{red_count}</div>
  </div>
</div>

<div class="controls">
  <div class="tabs">
    <button class="tab-btn active" onclick="filterColor('ALL', this)">All Stocks ({total_count})</button>
    <button class="tab-btn tab-green" onclick="filterColor('GREEN', this)">🟢 Prime Buy ({green_count})</button>
    <button class="tab-btn tab-yellow" onclick="filterColor('YELLOW', this)">🟡 Watchlist ({yellow_count})</button>
    <button class="tab-btn tab-red" onclick="filterColor('RED', this)">🔴 High Risk / Avoid ({red_count})</button>
  </div>
  <input type="text" id="searchInput" class="search-box" placeholder="Search symbol (e.g. RELIANCE)..." oninput="applyFilters()">
</div>

<div class="table-container">
  <table id="scanTable">
    <thead>
      <tr>
        <th>Action Status</th>
        <th>Symbol</th>
        <th class="num-cell">Price (₹)</th>
        <th class="num-cell">24h Chg</th>
        <th class="num-cell">RSI</th>
        <th class="num-cell">Buying Range</th>
        <th class="num-cell">Stop Loss</th>
        <th class="num-cell">Risk % (Distance)</th>
        <th class="num-cell">Target 1</th>
        <th class="num-cell">R:R</th>
        <th class="num-cell">Score</th>
        <th>Setup Signals & Reasons</th>
      </tr>
    </thead>
    <tbody id="tableBody">
      {table_body}
    </tbody>
  </table>
  <div id="emptyState" class="empty-state">No stocks matched the active filter or search query.</div>
</div>

<script>
  let activeColor = 'ALL';

  function filterColor(color, btn) {{
    activeColor = color;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  }}

  function applyFilters() {{
    const query = document.getElementById('searchInput').value.trim().toUpperCase();
    const rows = document.querySelectorAll('.scan-row');
    let visibleCount = 0;

    rows.forEach(row => {{
      const rowColor = row.getAttribute('data-color');
      const rowSymbol = row.getAttribute('data-symbol');

      const matchesColor = (activeColor === 'ALL' || rowColor === activeColor);
      const matchesSearch = (!query || rowSymbol.includes(query));

      if (matchesColor && matchesSearch) {{
        row.style.display = '';
        visibleCount++;
      }} else {{
        row.style.display = 'none';
      }}
    }});

    const empty = document.getElementById('emptyState');
    empty.style.display = visibleCount === 0 ? 'block' : 'none';
  }}

  // Auto-refresh countdown logic
  let countdown = 30;
  let autoRefresh = localStorage.getItem('auto_refresh') !== 'false';
  const checkEl = document.getElementById('autoRefreshCheck');
  if (checkEl) checkEl.checked = autoRefresh;

  function toggleAutoRefresh(el) {{
    autoRefresh = el.checked;
    localStorage.setItem('auto_refresh', autoRefresh);
    const label = document.getElementById('refreshTimer');
    if (!autoRefresh) {{
      if (label) label.textContent = 'Paused';
    }} else {{
      countdown = 30;
      if (label) label.textContent = countdown + 's';
    }}
  }}

  setInterval(() => {{
    if (!autoRefresh) return;
    countdown--;
    const label = document.getElementById('refreshTimer');
    if (label) label.textContent = countdown + 's';
    if (countdown <= 0) {{
      location.reload();
    }}
  }}, 1000);
</script>

</body>
</html>"""

    Path(html_path).write_text(html_content, encoding="utf-8")
    if latest_html_path:
        Path(latest_html_path).write_text(html_content, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="NSE Swing Trading Scanner")
    parser.add_argument("--indices", nargs="+", help="Override indices to scan (e.g. NIFTY_200 BANK_NIFTY)")
    parser.add_argument("--min-price", type=float, help="Override min price filter")
    parser.add_argument("--max-price", type=float, help="Override max price filter")
    parser.add_argument("--refresh-indices", action="store_true", help="Force refresh of index CSV cache")
    args = parser.parse_args()

    c = load_config()
    u, s, o = c["universe"], c["strategy"], c["output"]

    if args.min_price is not None:
        s["min_price"] = args.min_price
    if args.max_price is not None:
        s["max_price"] = args.max_price

def run_scan_cycle(symbols, c, args, iteration=1):
    u, s, o = c["universe"], c["strategy"], c["output"]
    print(f"Total Universe: {len(symbols)} symbols")
    print(f"Price Filter Range: ₹{s['min_price']} to ₹{s['max_price']}")
    
    # Check NIFTY 50 broad market trend & regime
    print("Checking NIFTY 50 broad market trend & regime...")
    nifty_regime = fetch_nifty_regime(u)
    if nifty_regime:
        print(f"NIFTY 50 Regime: {nifty_regime['badge']} (Price: ₹{nifty_regime['price']:,.2f} | RSI: {nifty_regime['rsi']})")

    print("Downloading market data and running scan...")

    batch_size = 75
    results, errors = [], []
    start_time = time.time()

    for start_idx in range(0, len(symbols), batch_size):
        chunk = symbols[start_idx:start_idx + batch_size]
        ticker_map = {sym: (sym if "." in sym else sym + u["exchange_suffix"]) for sym in chunk}
        download_list = list(ticker_map.values())

        try:
            batch_df = fetch_batch_data(download_list, u["history_period"], u["interval"])
            for sym, ticker in ticker_map.items():
                try:
                    if isinstance(batch_df.columns, pd.MultiIndex):
                        if ticker in batch_df.columns.levels[0]:
                            raw_df = batch_df[ticker].dropna(how="all")
                        else:
                            raw_df = pd.DataFrame()
                    elif ticker in batch_df:
                        raw_df = batch_df[ticker].dropna(how="all")
                    else:
                        raw_df = batch_df.dropna(how="all")

                    if not raw_df.empty and "Close" in raw_df.columns:
                        x = analyze(sym, raw_df, c)
                        if x:
                            results.append(x)
                except Exception as ex:
                    errors.append({"symbol": sym, "error": str(ex)})
        except Exception as batch_ex:
            # Fallback to single requests for this batch
            print(f"[Warning] Batch download failed ({batch_ex}). Falling back to individual requests.")
            for sym, ticker in ticker_map.items():
                try:
                    raw_df = yf.Ticker(ticker).history(period=u["history_period"],
                                                        interval=u["interval"], auto_adjust=False)
                    x = analyze(sym, raw_df, c)
                    if x:
                        results.append(x)
                except Exception as ex:
                    errors.append({"symbol": sym, "error": str(ex)})

    elapsed = time.time() - start_time
    print(f"Completed scanning {len(symbols)} symbols in {elapsed:.2f} seconds.")

    results.sort(key=lambda x: (
        0 if x["color_tag"] == "GREEN" else (1 if x["color_tag"] == "YELLOW" else 2),
        -x["score"],
        -x["risk_reward_to_target1"]
    ))
    out = BASE_DIR / o["directory"]
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(results)

    if not df.empty:
        cols = ["symbol", "price", "daily_change_pct", "buy_range", "entry_low", "entry_high", "rsi",
                f"ema_{c['indicators']['ema_fast']}",
                f"ema_{c['indicators']['ema_slow']}",
                f"ema_{c['indicators']['ema_long']}",
                "volume_ratio", "support", "resistance",
                "stop_loss", "risk_pct", "target_1", "target_1_pct", "target_2", "target_3",
                "risk_reward_to_target1", "score", "signal", "risk_level",
                "action_status", "color_tag", "breakout"]
        
        # Save CSV exports
        df[cols].to_csv(out / f"swing_scan_{stamp}.csv", index=False)
        df.to_csv(out / o["latest_csv_name"], index=False)
        
        # Save JSON exports
        scan_payload = {
            "timestamp": stamp,
            "market_regime": nifty_regime,
            "total_screened": len(results),
            "results": results
        }
        (out / f"swing_scan_{stamp}.json").write_text(
            json.dumps(scan_payload, indent=2), encoding="utf-8")

        # Render Terminal Color Report
        print_terminal_report(df, c, nifty_regime=nifty_regime)

        # Generate Interactive HTML Report
        latest_html = out / o.get("latest_html_name", "latest_scan.html")
        generate_html_dashboard(results, c, out / f"swing_scan_{stamp}.html", latest_html, nifty_regime=nifty_regime)
        print(f"{ANSI.BOLD_CYAN}📊 Interactive Visual Dashboard:{ANSI.RESET} {latest_html.resolve()}")
        print(f"{ANSI.BOLD_CYAN}📁 Latest CSV Data Export:{ANSI.RESET} {(out / o['latest_csv_name']).resolve()}\n")
    else:
        print("No stocks matched the configured price range or criteria.")

    if errors:
        (out / f"errors_{stamp}.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
        print(f"Logged {len(errors)} errors to errors_{stamp}.json")

def main():
    parser = argparse.ArgumentParser(description="NSE Swing Trading Scanner")
    parser.add_argument("--indices", nargs="+", help="Override indices to scan (e.g. NIFTY_200 BANK_NIFTY)")
    parser.add_argument("--min-price", type=float, help="Override min price filter")
    parser.add_argument("--max-price", type=float, help="Override max price filter")
    parser.add_argument("--refresh-indices", action="store_true", help="Force refresh of index CSV cache")
    parser.add_argument("--loop", type=int, nargs="?", const=180, default=None,
                        help="Run scanner continuously every N seconds (default: 180s / 3m)")
    args = parser.parse_args()

    c = load_config()
    u, s = c["universe"], c["strategy"]

    if args.min_price is not None:
        s["min_price"] = args.min_price
    if args.max_price is not None:
        s["max_price"] = args.max_price

    symbols = resolve_symbols(u, override_indices=args.indices, force_refresh=args.refresh_indices)
    if not symbols:
        print("No symbols found to scan. Please check your configuration or indices.")
        return 1

    if args.loop is not None:
        loop_interval = max(30, args.loop)
        print(f"\n{ANSI.BOLD_CYAN}🔄 Continuous Auto-Scanner Active:{ANSI.RESET} Scanning every {loop_interval}s ({loop_interval//60}m {loop_interval%60}s).")
        print(f"{ANSI.DIM}HTML dashboard and CSV will continuously update. Press Ctrl+C to stop.{ANSI.RESET}\n")
        iteration = 1
        try:
            while True:
                print(f"{ANSI.BOLD}══════════════════════ Scan Iteration #{iteration} ({datetime.now().strftime('%H:%M:%S')}) ══════════════════════{ANSI.RESET}")
                run_scan_cycle(symbols, c, args, iteration=iteration)
                print(f"{ANSI.DIM}Next scan in {loop_interval} seconds... (Press Ctrl+C to stop){ANSI.RESET}\n")
                time.sleep(loop_interval)
                iteration += 1
        except KeyboardInterrupt:
            print(f"\n{ANSI.YELLOW}Continuous scanning stopped by user.{ANSI.RESET}")
            return 0
    else:
        run_scan_cycle(symbols, c, args, iteration=1)
        return 0

if __name__ == "__main__":
    sys.exit(main())
