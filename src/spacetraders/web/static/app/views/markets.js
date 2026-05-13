import { renderTable } from '../components/table.js';

let _activeTab = 'prices';
let _system = '';

function fmtAge(seconds) {
  if (seconds == null) return '?';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function fmtAgeCell(seconds) {
  const cls = seconds > 300 ? 'status-stale' : seconds > 60 ? 'status-dim' : 'status-ready';
  return `<span class="${cls}">${fmtAge(seconds)}</span>`;
}

function fmtSpread(spread, pct) {
  const cls = pct > 30 ? 'sell-color' : pct > 10 ? 'status-transit' : '';
  return `<span class="${cls}">+${spread.toLocaleString()} (${pct}%)</span>`;
}

async function loadSystems() {
  try {
    const res = await fetch('/api/markets');
    const rows = res.ok ? await res.json() : [];
    const systems = [...new Set(rows.map((r) => (r.waypoint || '').split('-').slice(0, 2).join('-')))].filter(Boolean);
    return systems;
  } catch { return []; }
}

export function mountMarkets(container) {
  async function renderPrices(system) {
    try {
      const url = system ? `/api/markets?system=${encodeURIComponent(system)}` : '/api/markets';
      const res = await fetch(url);
      const rows = res.ok ? await res.json() : [];

      const cols = [
        { key: 'waypoint',      label: 'Waypoint' },
        { key: 'trade_symbol',  label: 'Good' },
        { key: 'type',          label: 'Type' },
        { key: 'supply',        label: 'Supply' },
        { key: 'activity',      label: 'Activity' },
        { key: 'purchase_price',label: 'Buy',    render: (v) => v != null ? `<span class="buy-color">${v}</span>` : '?' },
        { key: 'sell_price',    label: 'Sell',   render: (v) => v != null ? `<span class="sell-color">${v}</span>` : '?' },
        { key: 'trade_volume',  label: 'Vol' },
        { key: 'staleness_seconds', label: 'Age', render: (v) => fmtAgeCell(v) },
      ];

      const wrap = container.querySelector('#market-content');
      if (wrap) renderTable(wrap, cols, rows);
    } catch { /* ignore */ }
  }

  async function renderRoutes(system) {
    try {
      const url = system ? `/api/markets/routes?system=${encodeURIComponent(system)}` : '/api/markets/routes';
      const res = await fetch(url);
      const routes = res.ok ? await res.json() : [];

      const cols = [
        { key: 'trade_symbol',  label: 'Good' },
        { key: 'buy_waypoint',  label: 'Buy At' },
        { key: 'buy_price',     label: 'Buy Price', render: (v) => `<span class="buy-color">${v}</span>` },
        { key: 'sell_waypoint', label: 'Sell At' },
        { key: 'sell_price',    label: 'Sell Price', render: (v) => `<span class="sell-color">${v}</span>` },
        { key: 'spread',        label: 'Spread',
          render: (v, row) => fmtSpread(v, row.spread_pct) },
      ];

      const wrap = container.querySelector('#market-content');
      if (wrap) {
        if (routes.length) {
          renderTable(wrap, cols, routes);
        } else {
          wrap.innerHTML = '<p class="status-dim" style="padding:16px">No profitable routes found yet. Markets may need more data.</p>';
        }
      }
    } catch { /* ignore */ }
  }

  async function render() {
    const systems = await loadSystems();
    if (!_system && systems.length) _system = systems[0];

    const systemOptions = systems.map((s) =>
      `<option value="${s}" ${s === _system ? 'selected' : ''}>${s}</option>`
    ).join('');

    container.innerHTML = `
      <div class="view-header">
        <div class="view-title">Markets</div>
      </div>
      <div class="market-controls">
        <label for="system-sel">System</label>
        <select id="system-sel">${systemOptions}</select>
      </div>
      <div class="sub-tabs">
        <button class="sub-tab ${_activeTab === 'prices' ? 'active' : ''}" data-tab="prices">Prices</button>
        <button class="sub-tab ${_activeTab === 'routes' ? 'active' : ''}" data-tab="routes">Routes</button>
      </div>
      <div id="market-content"></div>`;

    container.querySelector('#system-sel')?.addEventListener('change', (e) => {
      _system = e.target.value;
      reload();
    });

    container.querySelectorAll('.sub-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        _activeTab = btn.dataset.tab;
        container.querySelectorAll('.sub-tab').forEach((b) =>
          b.classList.toggle('active', b.dataset.tab === _activeTab));
        reload();
      });
    });

    reload();
  }

  function reload() {
    if (_activeTab === 'routes') renderRoutes(_system);
    else renderPrices(_system);
  }

  const onUpdate = () => { if (window.ST.currentView === 'markets') reload(); };
  document.addEventListener('st:market_update', onUpdate);
  container.addEventListener('st:unmount', () =>
    document.removeEventListener('st:market_update', onUpdate));

  render();
}
