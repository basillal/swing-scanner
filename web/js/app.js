/* ═══════════════════════════════════════════════════════════
   app.js — Core application logic for Swing Scanner Web App
═══════════════════════════════════════════════════════════ */

/* ─── State ──────────────────────────────────────────────── */
let _results = [];
let _activeFilter = 'ALL';
let _sortCol = 'score';
let _sortAsc = false;
let _sseSource = null;
let _pollTimer = null;

/* ─── Init ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  // Navigation
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      switchPanel(link.dataset.panel);
    });
  });
  document.getElementById('sidebar-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
  });

  // Load initial data
  await loadLatestResults();
  loadConfigPanel();
  loadHistory();

  // Check scan status on load (in case server restarted mid-scan)
  checkScanStatus();
});

/* ─── Panel Navigation ───────────────────────────────────── */
function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

  const panel = document.getElementById(`panel-${name}`);
  const link = document.getElementById(`nav-${name}`);
  if (panel) panel.classList.add('active');
  if (link) link.classList.add('active');

  const titles = {
    dashboard: 'Dashboard', results: 'Results',
    charts: 'Charts & Analytics', config: 'Configuration', history: 'Scan History'
  };
  document.getElementById('page-title').textContent = titles[name] || name;

  if (name === 'charts' && _results.length > 0) {
    setTimeout(() => renderAllCharts(_results), 50);
  }
  if (name === 'history') loadHistory();
}

/* ─── Load Latest Results ────────────────────────────────── */
async function loadLatestResults() {
  try {
    const res = await fetch('/api/results/latest');
    const data = await res.json();
    if (data.ok && data.data) {
      applyResultData(data.data);
    }
  } catch (e) {
    console.error('Failed to load results:', e);
  }
}

function applyResultData(data) {
  const results = data.results || [];
  _results = results;
  updateKPIs(data);
  updateRegimeCard(data.market_regime);
  renderResultsTable(results);
  renderTopPicks(results);
  updateTabCounts(results);
}

/* ─── KPI Update ─────────────────────────────────────────── */
function updateKPIs(data) {
  const results = data.results || [];
  document.getElementById('kpi-total').textContent = results.length || '—';
  document.getElementById('kpi-green').textContent = results.filter(r => r.color_tag === 'GREEN').length;
  document.getElementById('kpi-yellow').textContent = results.filter(r => r.color_tag === 'YELLOW').length;
  document.getElementById('kpi-red').textContent = results.filter(r => r.color_tag === 'RED').length;

  const ts = data.scanned_at || data.timestamp || '';
  if (ts) {
    try {
      const d = new Date(ts);
      document.getElementById('kpi-time').textContent = d.toLocaleString('en-IN', {
        month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'
      });
    } catch { document.getElementById('kpi-time').textContent = ts; }
  }
}

/* ─── Regime Card ────────────────────────────────────────── */
function updateRegimeCard(regime) {
  const card = document.getElementById('regime-card');
  if (!regime) { card.classList.add('hidden'); return; }

  card.classList.remove('hidden', 'regime-green', 'regime-yellow', 'regime-red');
  card.classList.add(`regime-${regime.color_tag.toLowerCase()}`);

  const badge = document.getElementById('regime-badge');
  badge.className = `regime-badge ${regime.color_tag.toLowerCase()}`;
  badge.textContent = regime.badge;

  document.getElementById('regime-price').textContent = `₹${regime.price.toLocaleString('en-IN', {minimumFractionDigits:2})}`;

  const chgEl = document.getElementById('regime-chg');
  const chg = regime.daily_change_pct;
  chgEl.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
  chgEl.className = `regime-chg ${chg >= 0 ? 'pos' : 'neg'}`;

  document.getElementById('regime-indicators').innerHTML = `
    <span class="ind-pill">RSI <strong>${regime.rsi}</strong></span>
    <span class="ind-pill">EMA20 ₹${regime.ema_20?.toLocaleString('en-IN')}</span>
    <span class="ind-pill">EMA50 ₹${regime.ema_50?.toLocaleString('en-IN')}</span>
    <span class="ind-pill">EMA200 ₹${regime.ema_200?.toLocaleString('en-IN')}</span>
  `;
  document.getElementById('regime-advice').textContent = regime.advice;
}

/* ─── Results Table ─────────────────────────────────────── */
function renderResultsTable(results) {
  const sorted = sortResults(results);
  const tbody = document.getElementById('results-tbody');
  if (results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="12" class="empty-state-sm">No results. Run a scan first.</td></tr>`;
    return;
  }

  tbody.innerHTML = sorted.map(r => {
    const tagL = r.color_tag.toLowerCase();
    const chgCls = r.daily_change_pct >= 0 ? 'text-green' : 'text-red';
    const chgStr = `${r.daily_change_pct >= 0 ? '+' : ''}${r.daily_change_pct.toFixed(2)}%`;
    const rsiCls = r.rsi >= 70 ? 'rsi-hot' : (r.rsi >= 50 ? 'rsi-good' : 'rsi-neutral');
    const riskCls = r.risk_pct <= 4 ? 'risk-low' : (r.risk_pct <= 6.5 ? 'risk-mod' : 'risk-high');
    const riskLabel = r.risk_pct <= 4 ? 'Low' : (r.risk_pct <= 6.5 ? 'Moderate' : 'High');
    const scorePct = Math.min(100, Math.round((r.score / (r.max_score || 10)) * 100));
    const tvUrl = `https://in.tradingview.com/chart/?symbol=NSE:${r.symbol}`;

    const reasons = (r.reasons || '').split(';').map(s => s.trim()).filter(Boolean);
    const reasonPills = reasons.map(s =>
      `<span class="reason-pill ${s.includes('TOO MUCH') || s.includes('RISK') ? 'risk-reason' : ''}">${s}</span>`
    ).join('');

    return `
      <tr class="result-row" data-color="${r.color_tag}" data-symbol="${r.symbol}"
          onclick="showStockModal(${JSON.stringify(JSON.stringify(r))})">
        <td><span class="status-badge badge-${tagL}">${r.action_status}</span></td>
        <td>
          <div class="symbol-cell">
            <span class="symbol-name">${r.symbol}</span>
            <a href="${tvUrl}" target="_blank" rel="noopener" class="tv-btn"
               onclick="event.stopPropagation()">Chart ↗</a>
          </div>
        </td>
        <td class="num-cell">₹${fmtNum(r.price)}</td>
        <td class="num-cell ${chgCls} fw-bold">${chgStr}</td>
        <td class="num-cell"><span class="rsi-badge ${rsiCls}">${r.rsi.toFixed(1)}</span></td>
        <td class="num-cell"><span class="buy-range-pill">${r.buy_range || `₹${fmtNum(r.entry_low)} – ₹${fmtNum(r.entry_high)}`}</span></td>
        <td class="num-cell">₹${fmtNum(r.stop_loss)}</td>
        <td class="num-cell"><span class="risk-badge ${riskCls}">${r.risk_pct.toFixed(2)}% (${riskLabel})</span></td>
        <td class="num-cell text-green fw-bold">
          ₹${fmtNum(r.target_1)}
          <span class="target-pct">+${r.target_1_pct?.toFixed(1)}%</span>
        </td>
        <td class="num-cell">${r.risk_reward_to_target1.toFixed(2)}</td>
        <td class="num-cell">
          <div class="score-wrap">
            <span class="score-num">${r.score.toFixed(1)}</span>
            <div class="score-bar-bg"><div class="score-bar-fill" style="width:${scorePct}%"></div></div>
          </div>
        </td>
        <td><div class="reasons-wrap">${reasonPills}</div></td>
      </tr>
    `;
  }).join('');

  applyTableFilters();
}

function fmtNum(n) {
  if (!n && n !== 0) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ─── Filter & Sort ──────────────────────────────────────── */
function setFilter(color, btn) {
  _activeFilter = color;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyTableFilters();
}

function applyTableFilters() {
  const query = (document.getElementById('symbol-search')?.value || '').trim().toUpperCase();
  const rows = document.querySelectorAll('#results-tbody .result-row');
  let visible = 0;

  rows.forEach(row => {
    const colorMatch = _activeFilter === 'ALL' || row.dataset.color === _activeFilter;
    const symbolMatch = !query || row.dataset.symbol.includes(query);
    if (colorMatch && symbolMatch) {
      row.classList.remove('hidden-row'); visible++;
    } else {
      row.classList.add('hidden-row');
    }
  });

  const empty = document.getElementById('results-empty');
  if (empty) empty.classList.toggle('hidden', visible > 0);
}

function updateTabCounts(results) {
  document.getElementById('tab-count-green').textContent = results.filter(r => r.color_tag === 'GREEN').length;
  document.getElementById('tab-count-yellow').textContent = results.filter(r => r.color_tag === 'YELLOW').length;
  document.getElementById('tab-count-red').textContent = results.filter(r => r.color_tag === 'RED').length;
}

function sortResults(results) {
  return [...results].sort((a, b) => {
    let va = a[_sortCol], vb = b[_sortCol];
    if (typeof va === 'string') va = va.toLowerCase(), vb = vb.toLowerCase();
    if (va < vb) return _sortAsc ? -1 : 1;
    if (va > vb) return _sortAsc ? 1 : -1;
    return 0;
  });
}

function sortTable(col) {
  if (_sortCol === col) { _sortAsc = !_sortAsc; }
  else { _sortCol = col; _sortAsc = col === 'symbol'; }
  renderResultsTable(_results);
}

/* ─── Top Picks Preview ──────────────────────────────────── */
function renderTopPicks(results) {
  const top = results.filter(r => r.color_tag === 'GREEN').slice(0, 8);
  const container = document.getElementById('top-picks-body');

  if (top.length === 0) {
    container.innerHTML = `<div class="empty-state-sm">No Prime Buy setups in last scan. Try running a new scan.</div>`;
    return;
  }

  container.innerHTML = `
    <table class="top-picks-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th class="r">Price</th>
          <th class="r">RSI</th>
          <th class="r">Buy Range</th>
          <th class="r">Stop Loss</th>
          <th class="r">Target 1</th>
          <th class="r">R:R</th>
          <th class="r">Score</th>
        </tr>
      </thead>
      <tbody>
        ${top.map(r => `
          <tr onclick="showStockModal(${JSON.stringify(JSON.stringify(r))})" style="cursor:pointer">
            <td><span class="symbol-name">${r.symbol}</span></td>
            <td class="num-cell">₹${fmtNum(r.price)}</td>
            <td class="num-cell"><span class="rsi-badge rsi-good">${r.rsi.toFixed(1)}</span></td>
            <td class="num-cell"><span class="buy-range-pill" style="font-size:10px">${r.buy_range||'—'}</span></td>
            <td class="num-cell">₹${fmtNum(r.stop_loss)}</td>
            <td class="num-cell text-green fw-bold">₹${fmtNum(r.target_1)}</td>
            <td class="num-cell">${r.risk_reward_to_target1.toFixed(2)}</td>
            <td class="num-cell fw-bold">${r.score.toFixed(1)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

/* ─── Stock Detail Modal ─────────────────────────────────── */
function showStockModal(rJson) {
  const r = JSON.parse(rJson);
  const tagL = r.color_tag.toLowerCase();
  document.getElementById('modal-title').textContent = r.symbol;
  document.getElementById('modal-badge').className = `status-badge badge-${tagL}`;
  document.getElementById('modal-badge').textContent = r.action_status;

  const chgStr = `${r.daily_change_pct >= 0 ? '+' : ''}${r.daily_change_pct?.toFixed(2)}%`;
  const chgCls = r.daily_change_pct >= 0 ? 'text-green' : 'text-red';

  const reasons = (r.reasons || '').split(';').map(s => s.trim()).filter(Boolean);
  const reasonPills = reasons.map(s =>
    `<span class="reason-pill ${s.includes('TOO MUCH')||s.includes('RISK')?'risk-reason':''}">${s}</span>`
  ).join('');

  document.getElementById('modal-body').innerHTML = `
    <div class="detail-grid">
      <div class="detail-item">
        <div class="detail-label">Current Price</div>
        <div class="detail-val">₹${fmtNum(r.price)} <small class="${chgCls}" style="font-size:14px">${chgStr}</small></div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Buy Range</div>
        <div class="detail-val" style="font-size:15px; color:#38bdf8">${r.buy_range || '—'}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Stop Loss</div>
        <div class="detail-val" style="color:#f87171">₹${fmtNum(r.stop_loss)} <small style="font-size:12px;color:#f87171">(${r.risk_pct?.toFixed(2)}% risk)</small></div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Target 1 · Target 2 · Target 3</div>
        <div class="detail-val" style="font-size:13px; color:#34d399">
          ₹${fmtNum(r.target_1)} (+${r.target_1_pct?.toFixed(1)}%) &nbsp;|&nbsp;
          ₹${fmtNum(r.target_2)} (+${r.target_2_pct?.toFixed(1)}%) &nbsp;|&nbsp;
          ₹${fmtNum(r.target_3)} (+${r.target_3_pct?.toFixed(1)}%)
        </div>
      </div>
      <div class="detail-item">
        <div class="detail-label">RSI</div>
        <div class="detail-val">${r.rsi?.toFixed(1)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Risk : Reward (T1)</div>
        <div class="detail-val">${r.risk_reward_to_target1?.toFixed(2)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Score</div>
        <div class="detail-val">${r.score?.toFixed(1)} / ${r.max_score}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">MACD / Signal</div>
        <div class="detail-val" style="font-size:14px">${r.macd?.toFixed(3)} / ${r.macd_signal?.toFixed(3)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Support / Resistance</div>
        <div class="detail-val" style="font-size:14px">₹${fmtNum(r.support)} / ₹${fmtNum(r.resistance)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Volume Ratio</div>
        <div class="detail-val">${r.volume_ratio?.toFixed(2)}x</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">ATR</div>
        <div class="detail-val">₹${fmtNum(r.atr)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Date</div>
        <div class="detail-val" style="font-size:14px">${r.date || '—'}</div>
      </div>
    </div>
    <div style="margin-top:16px">
      <div class="detail-label" style="margin-bottom:8px">Setup Signals & Reasons</div>
      <div class="reasons-wrap">${reasonPills}</div>
    </div>
    <div style="margin-top:16px; display:flex; gap:10px;">
      <a href="https://in.tradingview.com/chart/?symbol=NSE:${r.symbol}" target="_blank" rel="noopener"
         class="btn btn-primary" style="text-decoration:none">📈 Open TradingView Chart</a>
      <a href="https://www.nseindia.com/get-quotes/equity?symbol=${r.symbol}" target="_blank" rel="noopener"
         class="btn" style="text-decoration:none">🔗 NSE Quote</a>
    </div>
  `;

  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ─── Scan Trigger ───────────────────────────────────────── */
async function triggerScan() {
  const btn = document.getElementById('scan-btn');
  btn.disabled = true;
  btn.innerHTML = '⏳ Starting...';

  try {
    const res = await fetch('/api/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await res.json();
    if (data.ok) {
      showToast('🚀 Scan started! Watch progress below.', 'info');
      showProgressCard();
      startSseListener();
    } else {
      showToast(`❌ ${data.error}`, 'error');
      resetScanBtn();
    }
  } catch (e) {
    showToast(`❌ Failed to start scan: ${e.message}`, 'error');
    resetScanBtn();
  }
}

function showProgressCard() {
  const card = document.getElementById('scan-progress-card');
  card.classList.remove('hidden');
  document.getElementById('scan-log').innerHTML = '';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-text').textContent = 'Initializing...';
  document.getElementById('progress-count').textContent = '0 / 0';
  updateStatusPill('running', 'Scanning...');

  // Switch to dashboard if not already
  const activePanel = document.querySelector('.panel.active');
  if (activePanel && activePanel.id !== 'panel-dashboard') {
    switchPanel('dashboard');
  }
}

function startSseListener() {
  if (_sseSource) { _sseSource.close(); _sseSource = null; }
  _sseSource = new EventSource('/api/scan/stream');

  _sseSource.onmessage = (e) => {
    const payload = JSON.parse(e.data);
    const state = payload.state;
    const newLogs = payload.new_logs || [];

    // Update progress bar
    if (state.total > 0) {
      const pct = Math.round((state.progress / state.total) * 100);
      document.getElementById('progress-bar').style.width = `${pct}%`;
      document.getElementById('progress-count').textContent = `${state.progress} / ${state.total}`;
    }
    document.getElementById('progress-text').textContent = state.message || '';

    // Append log entries
    const logEl = document.getElementById('scan-log');
    newLogs.forEach(entry => {
      const div = document.createElement('div');
      div.className = `log-entry ${entry.type}`;
      div.innerHTML = `<span class="log-ts">${entry.ts}</span>${escHtml(entry.message)}`;
      logEl.appendChild(div);
      logEl.scrollTop = logEl.scrollHeight;
    });

    if (payload.done || state.status === 'done') {
      _sseSource.close();
      _sseSource = null;
      onScanComplete(state);
    } else if (state.status === 'error') {
      _sseSource.close();
      _sseSource = null;
      onScanError(state.message);
    }
  };

  _sseSource.onerror = () => {
    // SSE failed, fall back to polling
    if (_sseSource) { _sseSource.close(); _sseSource = null; }
    startPolling();
  };
}

function startPolling() {
  if (_pollTimer) return;
  _pollTimer = setInterval(async () => {
    await checkScanStatus();
  }, 2000);
}

async function checkScanStatus() {
  try {
    const res = await fetch('/api/scan/status');
    const data = await res.json();
    if (!data.ok) return;
    const state = data.scan;

    if (state.status === 'running') {
      showProgressCard();
      const btn = document.getElementById('scan-btn');
      btn.disabled = true; btn.innerHTML = '⏳ Scanning...';
      updateStatusPill('running', 'Scanning...');

      if (state.total > 0) {
        const pct = Math.round((state.progress / state.total) * 100);
        document.getElementById('progress-bar').style.width = `${pct}%`;
        document.getElementById('progress-count').textContent = `${state.progress} / ${state.total}`;
      }
      document.getElementById('progress-text').textContent = state.message || '';

      // Append new logs
      const logEl = document.getElementById('scan-log');
      const logs = state.log || [];
      const current = logEl.children.length;
      const newLogs = logs.slice(current);
      newLogs.forEach(entry => {
        const div = document.createElement('div');
        div.className = `log-entry ${entry.type}`;
        div.innerHTML = `<span class="log-ts">${entry.ts}</span>${escHtml(entry.message)}`;
        logEl.appendChild(div);
      });
      logEl.scrollTop = logEl.scrollHeight;

    } else if (state.status === 'done') {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
      onScanComplete(state);
    } else if (state.status === 'error') {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
      onScanError(state.message);
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

async function onScanComplete(state) {
  resetScanBtn();
  updateStatusPill('done', 'Done');
  document.getElementById('progress-bar').style.width = '100%';
  document.getElementById('progress-text').textContent = state.message || 'Scan complete!';
  showToast(`✅ ${state.message}`, 'success');

  // Reload results
  await loadLatestResults();

  // Hide progress after a delay
  setTimeout(() => {
    document.getElementById('scan-progress-card').classList.add('hidden');
  }, 4000);
}

function onScanError(msg) {
  resetScanBtn();
  updateStatusPill('error', 'Error');
  showToast(`❌ Scan failed: ${msg}`, 'error');
}

function resetScanBtn() {
  const btn = document.getElementById('scan-btn');
  btn.disabled = false;
  btn.innerHTML = '🚀 Run Scan';
}

function updateStatusPill(status, text) {
  const dot = document.getElementById('status-dot');
  dot.className = `status-dot ${status}`;
  document.getElementById('status-text').textContent = text;
}

/* ─── History ────────────────────────────────────────────── */
async function loadHistory() {
  try {
    const res = await fetch('/api/results/history');
    const data = await res.json();
    const container = document.getElementById('history-list');
    if (!data.ok || !data.history || data.history.length === 0) {
      container.innerHTML = `<div class="config-loading">No scan history yet. Run your first scan!</div>`;
      return;
    }

    container.innerHTML = `
      <div class="history-list">
        ${data.history.map(h => `
          <div class="history-item" onclick="loadHistoryScan('${h.filename}')">
            <span class="history-ts">${formatTs(h.scanned_at || h.timestamp)}</span>
            <div class="history-counts">
              <span class="hcount g">🟢 ${h.green}</span>
              <span class="hcount y">🟡 ${h.yellow}</span>
              <span class="hcount r">🔴 ${h.red}</span>
              <span style="font-size:12px;color:#94a3b8">Total: ${h.total}</span>
            </div>
            <span class="history-elapsed">${h.elapsed}s</span>
            <span class="history-load-btn">Load →</span>
          </div>
        `).join('')}
      </div>
    `;
  } catch (e) {
    document.getElementById('history-list').innerHTML =
      `<div class="config-loading" style="color:#f87171">Failed to load history: ${e.message}</div>`;
  }
}

async function loadHistoryScan(filename) {
  try {
    const res = await fetch(`/api/results/${filename}`);
    const data = await res.json();
    if (data.ok && data.data) {
      applyResultData(data.data);
      switchPanel('dashboard');
      showToast(`📂 Loaded: ${filename}`, 'info');
    }
  } catch (e) {
    showToast(`❌ Failed to load: ${e.message}`, 'error');
  }
}

function formatTs(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-IN', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' });
  } catch { return ts; }
}

/* ─── Exports ────────────────────────────────────────────── */
function exportCSV() {
  window.open('/api/results/export/csv', '_blank');
}

function exportExcel() {
  window.open('/api/results/export/excel', '_blank');
}

/* ─── Toast ──────────────────────────────────────────────── */
function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.4s';
    setTimeout(() => toast.remove(), 400);
  }, 4000);
}

/* ─── Helpers ────────────────────────────────────────────── */
function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
