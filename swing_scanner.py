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

    if score >= s["buy_score_min"] and (
        breakout or (p > ef and ef > es and rv >= s["rsi_buy_min"])
    ):
        signal = "BUY"
    elif score >= s["watch_score_min"]:
        signal = "WATCH"
    else:
        signal = "AVOID"
    if rv >= s["hard_overbought"] and signal == "BUY":
        signal = "WATCH"

    d = s["price_decimals"]
    rd = lambda x: round(float(x), d)
    return {
        "symbol": symbol, "date": str(df.index[-1].date()), "price": rd(p),
        "daily_change_pct": round(daily_change, 2), "rsi": round(rv, 2),
        f"ema_{i['ema_fast']}": rd(ef), f"ema_{i['ema_slow']}": rd(es),
        f"ema_{i['ema_long']}": rd(el), "macd": round(mv, 4),
        "macd_signal": round(ms, 4), "volume_ratio": round(vr, 2),
        "support": rd(support), "resistance": rd(resistance), "atr": rd(av),
        "entry_low": rd(max(s["min_price"], min(p, support * (1 + s["support_entry_buffer_percent"] / 100)))),
        "entry_high": rd(p), "stop_loss": rd(stop),
        "target_1": rd(targets[0]), "target_2": rd(targets[1]), "target_3": rd(targets[2]),
        "risk_reward_to_target1": round(rr, 2), "score": round(score, 2),
        "max_score": s["max_score"], "signal": signal, "breakout": breakout,
        "reasons": "; ".join(reasons)
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

    symbols = resolve_symbols(u, override_indices=args.indices, force_refresh=args.refresh_indices)
    if not symbols:
        print("No symbols found to scan. Please check your configuration or indices.")
        return 1

    print(f"Total Universe: {len(symbols)} symbols")
    print(f"Price Filter Range: ₹{s['min_price']} to ₹{s['max_price']}")
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

    results.sort(key=lambda x: (x["score"], x["risk_reward_to_target1"]), reverse=True)
    out = BASE_DIR / o["directory"]
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(results)

    if not df.empty:
        cols = ["symbol", "price", "daily_change_pct", "rsi",
                f"ema_{c['indicators']['ema_fast']}",
                f"ema_{c['indicators']['ema_slow']}",
                f"ema_{c['indicators']['ema_long']}",
                "volume_ratio", "support", "resistance", "entry_low", "entry_high",
                "stop_loss", "target_1", "target_2", "target_3",
                "risk_reward_to_target1", "score", "signal", "breakout"]
        df[cols].to_csv(out / f"swing_scan_{stamp}.csv", index=False)
        df.to_csv(out / o["latest_csv_name"], index=False)
        (out / f"swing_scan_{stamp}.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8")

        # Display summary
        buy_count = len(df[df["signal"] == "BUY"])
        watch_count = len(df[df["signal"] == "WATCH"])
        avoid_count = len(df[df["signal"] == "AVOID"])
        print(f"\nScan Summary: {len(df)} passed price filter | BUY: {buy_count} | WATCH: {watch_count} | AVOID: {avoid_count}")
        
        # Show top candidates (all BUY and WATCH, and top AVOID)
        actionable = df[df["signal"].isin(["BUY", "WATCH"])]
        if not actionable.empty:
            print("\nActionable Setups (BUY / WATCH):")
            print(actionable[cols].to_string(index=False))
        else:
            print("\nNo BUY or WATCH setups found today. Top scored stocks:")
            print(df[cols].head(15).to_string(index=False))
    else:
        print("No stocks matched the configured price range or criteria.")

    if errors:
        (out / f"errors_{stamp}.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
        print(f"Logged {len(errors)} errors to errors_{stamp}.json")

    return 0

if __name__ == "__main__":
    sys.exit(main())
