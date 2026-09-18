/* ═══════════════════════════════════════════════════════════
   config.js — Configuration panel for Swing Scanner
═══════════════════════════════════════════════════════════ */

let _origConfig = null;
let _allIndices = [];

async function loadConfigPanel() {
  try {
    const [cfgRes, idxRes] = await Promise.all([
      fetch('/api/config'),
      fetch('/api/indices')
    ]);
    const cfgData = await cfgRes.json();
    const idxData = await idxRes.json();
    if (!cfgData.ok) throw new Error(cfgData.error);
    _origConfig = JSON.parse(JSON.stringify(cfgData.config));
    _allIndices = idxData.ok ? idxData.indices : Object.keys({
      NIFTY_50:1, NIFTY_NEXT_50:1, NIFTY_100:1, NIFTY_200:1, NIFTY_500:1,
      BANK_NIFTY:1, NIFTY_MIDCAP_100:1, NIFTY_SMALLCAP_100:1,
      NIFTY_IT:1, NIFTY_AUTO:1, NIFTY_PHARMA:1, NIFTY_FMCG:1,
      NIFTY_METAL:1, NIFTY_REALTY:1, NIFTY_ENERGY:1, NIFTY_INFRA:1
    });
    renderConfigForm(cfgData.config);
  } catch (e) {
    document.getElementById('config-form-wrap').innerHTML =
      `<div class="config-loading" style="color:#f87171">Failed to load config: ${e.message}</div>`;
  }
}

function renderConfigForm(cfg) {
  const wrap = document.getElementById('config-form-wrap');
  const u = cfg.universe, s = cfg.strategy, ind = cfg.indicators,
        sr = cfg.support_resistance, rm = cfg.risk_management;

  // Build index checkboxes
  const selectedIdx = new Set(u.indices || []);
  const idxBoxes = _allIndices.map(idx => `
    <label class="index-checkbox">
      <input type="checkbox" id="idx_${idx}" value="${idx}" ${selectedIdx.has(idx) ? 'checked' : ''}>
      <label for="idx_${idx}">${idx.replace(/_/g,' ')}</label>
    </label>
  `).join('');

  wrap.innerHTML = `
    <!-- UNIVERSE -->
    <div class="config-section">
      <div class="config-section-title">📡 Universe — Index Selection</div>
      <div class="indices-grid" id="indices-grid">${idxBoxes}</div>
      <div class="config-field" style="margin-top:16px">
        <label>Custom Symbols (comma separated, e.g. SWIGGY, IRFC)</label>
        <input type="text" id="cfg_custom_symbols" value="${(u.custom_symbols||[]).join(', ')}">
      </div>
      <div class="config-grid" style="margin-top:12px">
        ${rangeField('cfg_history_period','History Period','text',u.history_period||'1y')}
        ${rangeField('cfg_interval','Interval','text',u.interval||'1d')}
      </div>
    </div>

    <!-- STRATEGY -->
    <div class="config-section">
      <div class="config-section-title">🎯 Strategy — Filters & Scoring</div>
      <div class="config-grid">
        ${numField('cfg_min_price','Min Price (₹)',s.min_price,0,50000)}
        ${numField('cfg_max_price','Max Price (₹)',s.max_price,0,100000)}
        ${sliderField('cfg_rsi_buy_min','RSI Buy Min',s.rsi_buy_min,20,80,1)}
        ${sliderField('cfg_rsi_buy_max','RSI Buy Max',s.rsi_buy_max,20,80,1)}
        ${sliderField('cfg_rsi_overbought','RSI Overbought',s.rsi_overbought,50,90,1)}
        ${sliderField('cfg_volume_ratio_min','Volume Ratio Min',s.volume_ratio_min,0.5,5,0.1)}
        ${sliderField('cfg_buy_score_min','Buy Score Min',s.buy_score_min,1,10,0.5)}
        ${sliderField('cfg_watch_score_min','Watch Score Min',s.watch_score_min,1,10,0.5)}
      </div>
    </div>

    <!-- INDICATORS -->
    <div class="config-section">
      <div class="config-section-title">📊 Indicators</div>
      <div class="config-grid">
        ${sliderField('cfg_ema_fast','EMA Fast',ind.ema_fast,5,50,1)}
        ${sliderField('cfg_ema_slow','EMA Slow',ind.ema_slow,10,100,1)}
        ${sliderField('cfg_ema_long','EMA Long',ind.ema_long,50,300,1)}
        ${sliderField('cfg_rsi_period','RSI Period',ind.rsi_period,5,30,1)}
        ${sliderField('cfg_macd_fast','MACD Fast',ind.macd_fast,5,20,1)}
        ${sliderField('cfg_macd_slow','MACD Slow',ind.macd_slow,10,40,1)}
        ${sliderField('cfg_macd_signal','MACD Signal',ind.macd_signal,5,20,1)}
        ${sliderField('cfg_atr_period','ATR Period',ind.atr_period,5,30,1)}
        ${sliderField('cfg_vol_avg_period','Volume Avg Period',ind.volume_average_period,5,50,1)}
      </div>
    </div>

    <!-- RISK MANAGEMENT -->
    <div class="config-section">
      <div class="config-section-title">🛡️ Risk Management</div>
      <div class="config-grid">
        ${sliderField('cfg_stop_below_support','Stop Below Support %',rm.stop_below_support_percent,0.5,5,0.5)}
        ${sliderField('cfg_stop_atr_mult','Stop ATR Multiplier',rm.stop_atr_multiplier,0.5,5,0.5)}
        ${sliderField('cfg_max_low_risk','Max Low Risk %',rm.max_low_risk_percent,1,10,0.5)}
        ${sliderField('cfg_max_mod_risk','Max Moderate Risk %',rm.max_moderate_risk_percent,2,15,0.5)}
        ${sliderField('cfg_min_rr','Min Reward:Risk Ratio',rm.min_reward_risk_ratio,0.5,5,0.5)}
        ${sliderField('cfg_rsi_ob_warn','RSI Overbought Warning',rm.rsi_overbought_warning,50,85,1)}
      </div>
    </div>

    <!-- WEIGHTS -->
    <div class="config-section">
      <div class="config-section-title">⚖️ Signal Weights</div>
      <div class="config-grid">
        ${sliderField('cfg_w_price_fast','Price > Fast EMA',s.weights.price_above_fast_ema,0,3,0.5)}
        ${sliderField('cfg_w_fast_slow','Fast EMA > Slow EMA',s.weights.fast_ema_above_slow_ema,0,3,0.5)}
        ${sliderField('cfg_w_price_long','Price > Long EMA',s.weights.price_above_long_ema,0,3,0.5)}
        ${sliderField('cfg_w_rsi_zone','RSI in Buy Zone',s.weights.rsi_in_buy_zone,0,3,0.5)}
        ${sliderField('cfg_w_macd_bull','MACD Bullish',s.weights.macd_bullish,0,3,0.5)}
        ${sliderField('cfg_w_macd_zero','MACD > Zero',s.weights.macd_above_zero,0,3,0.5)}
        ${sliderField('cfg_w_volume','Volume Confirmation',s.weights.volume_confirmation,0,3,0.5)}
        ${sliderField('cfg_w_breakout','Breakout',s.weights.breakout,0,3,0.5)}
        ${sliderField('cfg_w_support','Near Support',s.weights.near_support,0,3,0.5)}
      </div>
    </div>
  `;
}

function numField(id, label, val, min, max) {
  return `<div class="config-field">
    <label for="${id}">${label}</label>
    <input type="number" id="${id}" value="${val}" min="${min}" max="${max}">
  </div>`;
}

function rangeField(id, label, type, val) {
  return `<div class="config-field">
    <label for="${id}">${label}</label>
    <input type="text" id="${id}" value="${val}">
  </div>`;
}

function sliderField(id, label, val, min, max, step) {
  return `<div class="config-field">
    <label for="${id}">${label}</label>
    <div class="range-wrap">
      <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}"
        oninput="document.getElementById('${id}_val').textContent=parseFloat(this.value).toFixed(step < 1 ? 1 : 0)">
      <span class="range-val" id="${id}_val">${typeof val === 'number' ? (step < 1 ? val.toFixed(1) : val) : val}</span>
    </div>
  </div>`;
}

function collectConfig() {
  if (!_origConfig) return null;
  const cfg = JSON.parse(JSON.stringify(_origConfig));

  // Indices
  const checkedIndices = [];
  _allIndices.forEach(idx => {
    const el = document.getElementById(`idx_${idx}`);
    if (el && el.checked) checkedIndices.push(idx);
  });
  cfg.universe.indices = checkedIndices;

  // Custom symbols
  const customRaw = document.getElementById('cfg_custom_symbols')?.value || '';
  cfg.universe.custom_symbols = customRaw.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
  cfg.universe.history_period = document.getElementById('cfg_history_period')?.value || cfg.universe.history_period;
  cfg.universe.interval = document.getElementById('cfg_interval')?.value || cfg.universe.interval;

  // Strategy
  cfg.strategy.min_price = parseFloat(document.getElementById('cfg_min_price')?.value) || cfg.strategy.min_price;
  cfg.strategy.max_price = parseFloat(document.getElementById('cfg_max_price')?.value) || cfg.strategy.max_price;
  cfg.strategy.rsi_buy_min = parseFloat(document.getElementById('cfg_rsi_buy_min')?.value);
  cfg.strategy.rsi_buy_max = parseFloat(document.getElementById('cfg_rsi_buy_max')?.value);
  cfg.strategy.rsi_overbought = parseFloat(document.getElementById('cfg_rsi_overbought')?.value);
  cfg.strategy.volume_ratio_min = parseFloat(document.getElementById('cfg_volume_ratio_min')?.value);
  cfg.strategy.buy_score_min = parseFloat(document.getElementById('cfg_buy_score_min')?.value);
  cfg.strategy.watch_score_min = parseFloat(document.getElementById('cfg_watch_score_min')?.value);

  // Indicators
  cfg.indicators.ema_fast = parseInt(document.getElementById('cfg_ema_fast')?.value);
  cfg.indicators.ema_slow = parseInt(document.getElementById('cfg_ema_slow')?.value);
  cfg.indicators.ema_long = parseInt(document.getElementById('cfg_ema_long')?.value);
  cfg.indicators.rsi_period = parseInt(document.getElementById('cfg_rsi_period')?.value);
  cfg.indicators.macd_fast = parseInt(document.getElementById('cfg_macd_fast')?.value);
  cfg.indicators.macd_slow = parseInt(document.getElementById('cfg_macd_slow')?.value);
  cfg.indicators.macd_signal = parseInt(document.getElementById('cfg_macd_signal')?.value);
  cfg.indicators.atr_period = parseInt(document.getElementById('cfg_atr_period')?.value);
  cfg.indicators.volume_average_period = parseInt(document.getElementById('cfg_vol_avg_period')?.value);

  // Risk Management
  cfg.risk_management.stop_below_support_percent = parseFloat(document.getElementById('cfg_stop_below_support')?.value);
  cfg.risk_management.stop_atr_multiplier = parseFloat(document.getElementById('cfg_stop_atr_mult')?.value);
  cfg.risk_management.max_low_risk_percent = parseFloat(document.getElementById('cfg_max_low_risk')?.value);
  cfg.risk_management.max_moderate_risk_percent = parseFloat(document.getElementById('cfg_max_mod_risk')?.value);
  cfg.risk_management.min_reward_risk_ratio = parseFloat(document.getElementById('cfg_min_rr')?.value);
  cfg.risk_management.rsi_overbought_warning = parseFloat(document.getElementById('cfg_rsi_ob_warn')?.value);

  // Weights
  cfg.strategy.weights.price_above_fast_ema = parseFloat(document.getElementById('cfg_w_price_fast')?.value);
  cfg.strategy.weights.fast_ema_above_slow_ema = parseFloat(document.getElementById('cfg_w_fast_slow')?.value);
  cfg.strategy.weights.price_above_long_ema = parseFloat(document.getElementById('cfg_w_price_long')?.value);
  cfg.strategy.weights.rsi_in_buy_zone = parseFloat(document.getElementById('cfg_w_rsi_zone')?.value);
  cfg.strategy.weights.macd_bullish = parseFloat(document.getElementById('cfg_w_macd_bull')?.value);
  cfg.strategy.weights.macd_above_zero = parseFloat(document.getElementById('cfg_w_macd_zero')?.value);
  cfg.strategy.weights.volume_confirmation = parseFloat(document.getElementById('cfg_w_volume')?.value);
  cfg.strategy.weights.breakout = parseFloat(document.getElementById('cfg_w_breakout')?.value);
  cfg.strategy.weights.near_support = parseFloat(document.getElementById('cfg_w_support')?.value);

  return cfg;
}

async function saveConfig() {
  const cfg = collectConfig();
  if (!cfg) return showToast('No config loaded', 'error');
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg)
    });
    const data = await res.json();
    if (data.ok) {
      _origConfig = cfg;
      showToast('✅ Configuration saved successfully!', 'success');
    } else {
      showToast(`❌ Save failed: ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Network error: ${e.message}`, 'error');
  }
}

function resetConfig() {
  if (_origConfig) {
    renderConfigForm(_origConfig);
    showToast('↩ Config reset to last saved values', 'info');
  }
}
