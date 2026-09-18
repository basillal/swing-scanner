/* ═══════════════════════════════════════════════════════════
   charts.js — Chart.js visualizations for Swing Scanner
═══════════════════════════════════════════════════════════ */

const CHART_DEFAULTS = {
  color: '#94a3b8',
  gridColor: 'rgba(30,45,69,0.8)',
  fontFamily: "'Inter', system-ui, sans-serif",
};

Chart.defaults.color = CHART_DEFAULTS.color;
Chart.defaults.font.family = CHART_DEFAULTS.fontFamily;
Chart.defaults.font.size = 12;

let _charts = {};

function destroyChart(id) {
  if (_charts[id]) {
    _charts[id].destroy();
    delete _charts[id];
  }
}

function renderAllCharts(results) {
  if (!results || results.length === 0) return;
  renderSignalChart(results);
  renderScoreChart(results);
  renderRsiChart(results);
  renderTop10Chart(results);
}

/* ─── 1. Signal Distribution Doughnut ─────────────────── */
function renderSignalChart(results) {
  destroyChart('signals');
  const green = results.filter(r => r.color_tag === 'GREEN').length;
  const yellow = results.filter(r => r.color_tag === 'YELLOW').length;
  const red = results.filter(r => r.color_tag === 'RED').length;

  const ctx = document.getElementById('chart-signals').getContext('2d');
  _charts['signals'] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['🟢 Prime Buy', '🟡 Watchlist', '🔴 High Risk / Avoid'],
      datasets: [{
        data: [green, yellow, red],
        backgroundColor: ['rgba(16,185,129,0.8)', 'rgba(245,158,11,0.8)', 'rgba(239,68,68,0.8)'],
        borderColor: ['#059669', '#d97706', '#dc2626'],
        borderWidth: 2,
        hoverOffset: 8,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 16, usePointStyle: true, pointStyleWidth: 10, font: { size: 12 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${ctx.parsed} (${Math.round(ctx.parsed / results.length * 100)}%)`
          }
        }
      },
      animation: { animateRotate: true, duration: 700, easing: 'easeOutQuart' }
    }
  });
}

/* ─── 2. Score Distribution Bar ────────────────────────── */
function renderScoreChart(results) {
  destroyChart('scores');
  const buckets = { '0-2': 0, '2-4': 0, '4-6': 0, '6-7': 0, '7-8': 0, '8-9': 0, '9-10': 0 };
  results.forEach(r => {
    const s = r.score;
    if (s < 2) buckets['0-2']++;
    else if (s < 4) buckets['2-4']++;
    else if (s < 6) buckets['4-6']++;
    else if (s < 7) buckets['6-7']++;
    else if (s < 8) buckets['7-8']++;
    else if (s < 9) buckets['8-9']++;
    else buckets['9-10']++;
  });

  const colors = buckets['0-2'] >= 0 ? [
    'rgba(100,116,139,0.7)', 'rgba(100,116,139,0.7)',
    'rgba(245,158,11,0.6)', 'rgba(245,158,11,0.8)',
    'rgba(16,185,129,0.6)', 'rgba(16,185,129,0.8)', 'rgba(16,185,129,1)',
  ] : [];

  const ctx = document.getElementById('chart-scores').getContext('2d');
  _charts['scores'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: Object.keys(buckets),
      datasets: [{
        label: 'Stocks',
        data: Object.values(buckets),
        backgroundColor: colors,
        borderColor: colors.map(c => c.replace('0.7', '1').replace('0.6', '1').replace('0.8', '1')),
        borderWidth: 1,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: t => `Score ${t[0].label}` } } },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.gridColor }, title: { display: true, text: 'Score Range', color: CHART_DEFAULTS.color } },
        y: { grid: { color: CHART_DEFAULTS.gridColor }, beginAtZero: true, ticks: { stepSize: 1 }, title: { display: true, text: 'Count', color: CHART_DEFAULTS.color } }
      },
      animation: { duration: 600, easing: 'easeOutQuart' }
    }
  });
}

/* ─── 3. RSI Distribution Histogram ────────────────────── */
function renderRsiChart(results) {
  destroyChart('rsi');
  const buckets = {};
  for (let i = 20; i <= 85; i += 5) {
    buckets[`${i}-${i+5}`] = 0;
  }
  results.forEach(r => {
    const rsi = r.rsi;
    for (let i = 20; i <= 85; i += 5) {
      if (rsi >= i && rsi < i + 5) {
        buckets[`${i}-${i+5}`]++;
        break;
      }
    }
  });

  const labels = Object.keys(buckets);
  const colors = labels.map(label => {
    const low = parseInt(label.split('-')[0]);
    if (low >= 70) return 'rgba(239,68,68,0.8)';
    if (low >= 50 && low < 70) return 'rgba(16,185,129,0.75)';
    return 'rgba(100,116,139,0.6)';
  });

  const ctx = document.getElementById('chart-rsi').getContext('2d');
  _charts['rsi'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Stocks',
        data: Object.values(buckets),
        backgroundColor: colors,
        borderColor: colors.map(c => c.replace('0.8', '1').replace('0.75', '1').replace('0.6', '1')),
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: t => `RSI ${t[0].label}` } },
        annotation: {}
      },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.gridColor }, title: { display: true, text: 'RSI Range', color: CHART_DEFAULTS.color } },
        y: { grid: { color: CHART_DEFAULTS.gridColor }, beginAtZero: true, ticks: { stepSize: 1 }, title: { display: true, text: 'Count', color: CHART_DEFAULTS.color } }
      },
      animation: { duration: 600 }
    }
  });
}

/* ─── 4. Top 10 Setups Horizontal Bar ──────────────────── */
function renderTop10Chart(results) {
  destroyChart('top10');
  const top = results
    .filter(r => r.color_tag !== 'RED')
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);

  if (top.length === 0) return;

  const labels = top.map(r => r.symbol);
  const scores = top.map(r => r.score);
  const bgColors = top.map(r =>
    r.color_tag === 'GREEN' ? 'rgba(16,185,129,0.75)' : 'rgba(245,158,11,0.7)'
  );
  const borderColors = top.map(r =>
    r.color_tag === 'GREEN' ? '#059669' : '#d97706'
  );

  const ctx = document.getElementById('chart-top10').getContext('2d');
  _charts['top10'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Score',
        data: scores,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 6,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const r = top[ctx.dataIndex];
              return [` Score: ${r.score}`, ` RSI: ${r.rsi}`, ` R:R: ${r.risk_reward_to_target1}`];
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: CHART_DEFAULTS.gridColor },
          min: 0, max: 10,
          title: { display: true, text: 'Score (max 10)', color: CHART_DEFAULTS.color }
        },
        y: { grid: { display: false }, ticks: { font: { weight: '700', size: 12 } } }
      },
      animation: { duration: 700, easing: 'easeOutQuart' }
    }
  });
}
