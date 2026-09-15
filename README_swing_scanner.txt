NSE SWING SCANNER

1. Create environment:
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

2. Run:
   python swing_scanner.py

3. CONFIGURATION (swing_scanner_config.json):
   - "indices": Select any popular NSE index or combination:
     "NIFTY_200", "BANK_NIFTY", "NIFTY_50", "NIFTY_100", "NIFTY_500",
     "NIFTY_MIDCAP_100", "NIFTY_SMALLCAP_100", "NIFTY_IT", "NIFTY_AUTO", etc.
   - "custom_symbols": Any individual stocks (e.g. "SWIGGY") you want to include.
   - "min_price" / "max_price": ₹ price boundaries for swing trading candidates.
   - Strategy parameters: RSI, EMAs, MACD, volume thresholds, stop-loss, targets.

4. CLI OVERRIDES (Optional):
   - python swing_scanner.py --indices NIFTY_50 BANK_NIFTY
   - python swing_scanner.py --indices NIFTY_MIDCAP_100 --min-price 100 --max-price 5000
   - python swing_scanner.py --refresh-indices   (forces fresh download of NSE index CSVs)

5. Results are saved in scanner_results/, including latest_scan.csv.
   Index CSVs are cached locally in cache/indices/ for fast startup and offline reliability.

6. Yahoo Finance data may be delayed/missing. Confirm the final trade using
   your broker/NSE before placing an order.

Cron example (after market close):
15 16 * * 1-5 cd /absolute/path/to/scanner && /absolute/path/to/scanner/.venv/bin/python swing_scanner.py >> scanner.log 2>&1
