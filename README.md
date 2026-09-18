# 🎯 NSE Swing Trading Scanner & Risk Intelligence Engine

An algorithmic end-of-day (EOD) swing trading scanner for Indian Equities (NSE). It scans index constituents (Nifty 50, Nifty 200, Bank Nifty, etc.), identifies high-probability momentum setups, calculates precise ATR/support-based stop losses, and applies **multi-factor risk filtering** with visual color highlights.

---

## 📌 NIFTY 50 Indication & Market Regime Engine

The scanner now automatically evaluates the parent **NIFTY 50 Index (`^NSEI`)** before scanning individual stocks to determine broad market health.

### Market Regimes:
* 🟢 **BULLISH REGIME**: Price $> 20\text{ EMA}$, $20\text{ EMA} > 50\text{ EMA}$, Price $> 200\text{ EMA}$, and $\text{RSI} \ge 50$.
  * *Guidance*: High-probability market tailwinds. Full position sizing on 🟢 Prime Buys.
* 🟡 **RANGEBOUND / CAUTIOUS**: Price consolidating between 20 & 50 EMA, or pullbacks near support.
  * *Guidance*: Trade selectively with reduced sizing and tighter trailing stops.
* 🔴 **BEARISH / CORRECTION**: Price $< 50\text{ EMA}$ or $< 200\text{ EMA}$, or $20\text{ EMA} < 50\text{ EMA}$.
  * *Guidance*: High risk of failed breakouts. Prioritize capital preservation or strict defense.

### Are We Showing All Stocks in `cache/indices`?
* **Default Scan**: Scans whatever indices are configured in `swing_scanner_config.json` (defaults to `NIFTY_200` + `BANK_NIFTY`, ~201 unique stocks).
* **Scan ALL Cached Stocks (`--indices ALL`)**:
  * You can scan **all 501 unique stocks** across all 16 cached index CSV files in `cache/indices/` simply by running:
    ```bash
    python swing_scanner.py --indices ALL
    ```
* **Price & Liquidity Filtering**: All stocks in the chosen universe that fall within the configured price boundary (₹50 to ₹10,000) and have valid trading history are analyzed and displayed in both the terminal and `latest_scan.html`.

---

## 🔍 How the Scanner Finds Better Stocks (The 9 Pillars)

Every stock passes through a multi-factor quantitative and price-action filter:

```
                  ┌─────────────────────────────────────┐
                  │          NSE Stock Universe         │
                  └──────────────────┬──────────────────┘
                                     │
                        [ 1. Price Boundary Filter ]
                          (₹50 to ₹10,000 per share)
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
       [ Trend & Structure ]                   [ Momentum & Volume ]
       • Price > 20 EMA                        • RSI (50 - 68 sweet spot)
       • 20 EMA > 50 EMA                       • MACD Bullish Crossover
       • Price > 200 EMA (Long-term)           • MACD Line > 0
       • 20-day Support / Resistance           • Volume > 1.2x 20-day Avg
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                     [ 2. Strategy Scoring (0 - 10) ]
                     Breakout (+1.5) | Support Bounce (+1.0)
                     EMA Alignment (+3.0) | Volume (+1.0) | MACD (+1.5)
                                     │
                    [ 3. Downside Risk Assessment ]
                     • Stop Loss = min(Support - 1%, Price - 1.5 ATR)
                     • Risk % = (Price - Stop Loss) / Price * 100
                     • Risk-to-Reward Ratio to Target 1 (≥ 1.5x)
                                     │
               ┌─────────────────────┼─────────────────────┐
               ▼                     ▼                     ▼
       🟢 PRIME BUY          🟡 WATCHLIST           🔴 HIGH RISK / AVOID
       • Score ≥ 7.0         • Score 5.0 - 6.9      • Downside Risk > 6.5%
       • Risk ≤ 4.0%         • Risk 4.0% - 6.5%     • RSI ≥ 72 (Overbought)
       • RSI ≤ 68            • Waiting for trigger  • Price < 200 EMA
       • Above 200 EMA                              • Weak Score (< 5.0)
```

---

### 1. Trend Alignment (20, 50, and 200 EMAs)
* **20 EMA (Fast)**: Measures short-term swing momentum. Price must trade above 20 EMA.
* **50 EMA (Slow)**: Measures medium-term trend. The 20 EMA must be above the 50 EMA.
* **200 EMA (Long-term Baseline)**: Separates bull markets from bear markets. Stocks below 200 EMA are automatically flagged as **High Risk / Downtrend**.

### 2. Relative Strength Index (RSI - 14 Periods)
* **Bullish Zone (50 to 68)**: Stock has bullish momentum with ample room to run (+1.0 point).
* **Overbought Warning (68 to 72)**: Caution zone; upside may be limited in the immediate term.
* **Severe Overbought (≥ 72)**: Chasing here carries high reversal risk; downgraded to 🔴 **High Risk / Avoid**.

### 3. MACD Momentum (12, 26, 9)
* **MACD Bullish Crossover**: MACD line above signal line confirms active buying pressure (+1.0 point).
* **Above Zero Baseline**: MACD line above 0 confirms that short-term moving average is higher than long-term (+0.5 point).

### 4. Volume Surge & Institutional Footprint
* Compares current volume to the **20-day rolling average volume**.
* A volume ratio $\ge 1.2\times$ confirms institutional participation and conviction (+1.0 point).

### 5. Price Action: Breakout vs. Support Entry
* **20-Day Resistance Breakout**: Price breaking above the 20-day high with a 0.5% buffer (+1.5 points).
* **Support Bounce / Pullback**: Price testing within 1.5% of 20-day support in an uptrend (+1.0 point).

### 6. Volatility & ATR (Average True Range - 14 Periods)
* Measures the stock's natural daily fluctuation.
* Used to ensure stop-losses are placed outside typical market noise (`1.5 * ATR`).

### 7. Precise Downside Risk Management
* Calculates structural stop-loss:
  $$\text{Stop Loss} = \min(\text{Support} \times 0.99, \text{Price} - 1.5 \times \text{ATR})$$
* Computes exact risk percentage:
  $$\text{Risk } \% = \frac{\text{Price} - \text{Stop Loss}}{\text{Price}} \times 100$$
* **If Risk % $> 6.5\%$**: The stock is flagged as **🔴 HIGH RISK**. Even if the score is high, entering with a large stop distance exposes your capital to severe drawdowns.

### 8. Actionable Buying Range (Buy Zone)
To avoid chasing extended stocks or buying too far from support, the scanner computes a tailored **Buy Zone (`buy_range`)**:
* **Breakout Setups**: Entry between the breakout pivot (Resistance) and current price / $+0.5\%$ buffer:
  $$\text{Buy Zone} = [\text{Resistance}, \text{Price} \times 1.005]$$
* **Support Bounce / Pullback**: Entry between the 20-day support floor and $+1.5\%$ above support:
  $$\text{Buy Zone} = [\text{Support}, \text{Support} \times 1.015]$$
* **Trend Momentum (20 EMA)**: Entry on a slight pullback towards the 20 EMA up to current price $+0.5\%$:
  $$\text{Buy Zone} = [\max(\text{EMA}_{20}, \text{Price} \times 0.985), \text{Price} \times 1.005]$$

### 9. Risk-to-Reward Ratio (R:R)
* Calculates 3 progressive profit targets based on $R$ multiples:
  * **Target 1**: Price $+ 1.5 \times \text{Risk}$ (Minimum 1.5:1 R:R required)
  * **Target 2**: Price $+ 2.5 \times \text{Risk}$ (2.5:1 R:R)
  * **Target 3**: Price $+ 3.5 \times \text{Risk}$ (3.5:1 R:R)

### 10. Composite Technical Score (0.0 to 10.0)
Weights are summed from all technical confirmations to yield an objective score out of 10.0.

---

## 🎨 Color-Coded Execution Engine

| Color Badge | Classification | What It Means | Action Plan |
| :---: | :--- | :--- | :--- |
| 🟢 | **BUY NOW (PRIME SETUP)** | Score $\ge 7.0$, Downside Risk $\le 4.0\%$, RSI $\le 68$, Price $> 200\text{ EMA}$ | **Best time to enter.** Tight risk, strong momentum, high reward potential. |
| 🟡 | **BUY (MODERATE RISK)** | Score $\ge 7.0$, but Downside Risk is between $4.0\%$ and $6.5\%$ | Valid setup. Enter with **smaller position size** to manage the wider stop. |
| 🟡 | **WATCHLIST** | Score $5.0 - 6.9$, Risk $\le 6.5\%$ | Setup is forming. Wait for volume surge or clear breakout before buying. |
| 🔴 | **HIGH RISK (AVOID)** | Risk $> 6.5\%$, RSI $\ge 72$, or Price $< 200\text{ EMA}$ | **Do not enter now.** Risk of sudden reversal or outsized loss is too high. |
| 🔴 | **AVOID (LOW SCORE)** | Score $< 5.0$ | Weak setup; lacks trend confirmation. |

---

## 🚀 How to Run the Scanner

### 1. Basic Scan (Default Indices from config)
```bash
python swing_scanner.py
```

### 2. Scan Specific Indices
```bash
# Scan Bank Nifty only
python swing_scanner.py --indices BANK_NIFTY

# Scan Nifty 50 and Nifty Midcap 100
python swing_scanner.py --indices NIFTY_50 NIFTY_MIDCAP_100
```

### 3. Filter by Custom Price Range
```bash
python swing_scanner.py --min-price 100 --max-price 3000
```

### 4. Continuous Scanning Loop Mode (Real-Time Auto-Update)
You can run the scanner in a continuous loop to automatically rescan market data and update the HTML dashboard and CSV every $N$ seconds:
```bash
# Continuous scan every 3 minutes (default: 180 seconds)
python swing_scanner.py --loop

# Continuous scan every 60 seconds (1 minute)
python swing_scanner.py --loop 60

# Continuous scan with Bank Nifty every 2 minutes
python swing_scanner.py --indices BANK_NIFTY --loop 120
```

### 5. Force Refresh of NSE Index Constituent Lists
```bash
python swing_scanner.py --refresh-indices
```

---

## 📊 Viewing Scanner Results

Every scan generates three output formats in `scanner_results/`:

1. **Terminal ANSI Color Table**:
   * Color-highlighted CLI summary showing Prime Buys, Watchlists, and High Risk warnings.
2. **Interactive HTML Dashboard (`latest_scan.html`)**:
   * Open `scanner_results/latest_scan.html` in any web browser.
   * Features dark-mode theme, KPI stat cards, interactive filter buttons (`🟢 Prime Buy`, `🟡 Watchlist`, `🔴 High Risk`), live search bar, and one-click TradingView chart links (`Chart ↗`).
3. **Data Exports (`latest_scan.csv` & timestamped JSON)**:
   * Contains all indicator columns, risk percentages, and action statuses for spreadsheets or automation.

---

## ⚙️ Configuration (`swing_scanner_config.json`)

All risk boundaries and strategy weights are fully customizable:

```json
{
  "universe": {
    "indices": ["NIFTY_200", "BANK_NIFTY"],
    "custom_symbols": ["SWIGGY"]
  },
  "strategy": {
    "min_price": 50,
    "max_price": 10000,
    "rsi_buy_min": 50,
    "rsi_buy_max": 68,
    "volume_ratio_min": 1.2,
    "buy_score_min": 7.0,
    "watch_score_min": 5.0
  },
  "risk_management": {
    "max_low_risk_percent": 4.0,
    "max_moderate_risk_percent": 6.5,
    "min_reward_risk_ratio": 1.5,
    "rsi_overbought_warning": 68.0,
    "rsi_high_risk": 72.0
  }
}
```

---

## 💡 Practical Swing Trading Workflow

1. **Run the scan after market close** (around 4:00 PM IST).
2. **Open `latest_scan.html`** and click on **🟢 Prime Buy (Low Risk)**.
3. **Open the TradingView chart** for each green candidate using the `Chart ↗` button.
4. **Verify the chart pattern**:
   * Clean consolidation or cup-and-handle / flag pattern.
   * Clear support or resistance level matching the scanner's stop-loss.
5. **Position Sizing**:
   * Never risk more than 1–2% of your total trading capital on a single stock:
     $$\text{Shares to Buy} = \frac{\text{Account Capital} \times 0.01}{\text{Entry Price} - \text{Stop Loss Price}}$$
6. **Execution**:
   * Place a GTT (Good-Till-Triggered) or limit order near the entry zone with the designated stop-loss.
   * Book partial profits at **Target 1** (1.5R) and trail stop-loss to cost.
