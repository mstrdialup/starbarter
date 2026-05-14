import { renderTable, escHtml } from '../components/table.js';
import { openCommandModal } from '../components/command-modal.js';

let _selectedSymbol = null;
let _ships = [];
let _container = null;

function secondsUntil(iso) {
  if (!iso) return 0;
  try {
    const diff = (new Date(iso) - Date.now()) / 1000;
    return Math.max(0, diff);
  } catch { return 0; }
}

function statusClass(ship) {
  const s = ship.nav_status || '';
  const fuelPct = (ship.fuel_current || 0) / Math.max(ship.fuel_capacity || 1, 1);
  const cooldown = secondsUntil(ship.cooldown_expires);
  if (cooldown > 0.5) return 'status-cooldown';
  if (fuelPct < 0.2 && (ship.fuel_capacity || 0) > 0) return 'status-critical';
  if (s === 'IN_TRANSIT') return 'status-transit';
  return 'status-ready';
}

function fmtStatus(ship) {
  const cls = statusClass(ship);
  let label = ship.nav_status || '?';
  if (ship.nav_status === 'IN_TRANSIT') {
    const wait = Math.round(secondsUntil(ship.arrival_time));
    label = `→ ${wait}s`;
  }
  return `<span class="${cls}">${escHtml(label)}</span>`;
}

function fmtCondition(val) {
  const pct = Math.round((val || 1) * 100);
  const cls = pct < 50 ? 'crit' : pct < 80 ? 'warn' : '';
  return `
    <span class="bar-track" title="${pct}%">
      <span class="bar-fill ${cls}" style="width:${pct}%"></span>
    </span>`;
}

function fmtLastActionTs(ts) {
  if (!ts) return '';
  try {
    return ` (${new Date(ts).toLocaleTimeString()})`;
  } catch { return ''; }
}

function renderDetail(ship) {
  if (!ship) return '<p class="status-dim">Select a ship</p>';

  const cargo = Array.isArray(ship.cargo_inventory) ? ship.cargo_inventory : [];
  const cooldownS = Math.round(secondsUntil(ship.cooldown_expires));
  const cooldownStr = cooldownS > 0 ? `${cooldownS}s` : 'Ready';
  const isTransit = ship.nav_status === 'IN_TRANSIT';
  const isPaused = ship.paused;

  const cargoHtml = cargo.length
    ? cargo.map((i) =>
        `<div class="cargo-item"><span>${escHtml(i.symbol)}</span><span>${i.units}</span></div>`
      ).join('')
    : '<div class="cargo-empty">(empty)</div>';

  const btnDefs = [
    { cmd: 'orbit',   label: 'Orbit',    disabled: isTransit || ship.nav_status === 'IN_ORBIT' },
    { cmd: 'dock',    label: 'Dock',     disabled: isTransit || ship.nav_status === 'DOCKED' },
    { cmd: 'navigate',label: 'Navigate', disabled: isTransit },
    { cmd: 'extract', label: 'Extract',  disabled: isTransit || ship.nav_status === 'DOCKED' },
    { cmd: 'sell',    label: 'Sell',     disabled: isTransit || ship.nav_status !== 'DOCKED' },
    { cmd: 'refuel',  label: 'Refuel',   disabled: isTransit || ship.nav_status !== 'DOCKED' },
  ];

  const btns = btnDefs.map((b) =>
    `<button class="btn" data-cmd="${b.cmd}" ${b.disabled ? 'disabled' : ''}>${b.label}</button>`
  ).join('');

  const lastActionHtml = ship.last_action
    ? `<div class="detail-row">
        <span class="detail-label">Action</span>
        <span>${escHtml(ship.last_action)}${fmtLastActionTs(ship.last_action_at)}</span>
      </div>`
    : '';

  const pauseLabel = isPaused ? '▶ Resume' : '⏸ Pause';

  return `
    <h3>${escHtml(ship.symbol)}</h3>
    <div class="detail-row">
      <span class="detail-label">Status</span>
      <span>${fmtStatus(ship)}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Location</span>
      <span>${escHtml(ship.nav_waypoint || '?')}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Fuel</span>
      <span>${ship.fuel_current || 0} / ${ship.fuel_capacity || 0}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Cooldown</span>
      <span>${cooldownStr}</span>
    </div>
    ${lastActionHtml}
    <div style="margin-top:10px">
      <div class="detail-label" style="margin-bottom:4px">Condition</div>
      <div class="condition-bar"><span class="detail-label" style="width:60px">Frame</span>${fmtCondition(ship.condition_frame)}</div>
      <div class="condition-bar"><span class="detail-label" style="width:60px">Engine</span>${fmtCondition(ship.condition_engine)}</div>
      <div class="condition-bar"><span class="detail-label" style="width:60px">Reactor</span>${fmtCondition(ship.condition_reactor)}</div>
    </div>
    <div style="margin-top:10px">
      <div class="detail-label" style="margin-bottom:4px">Cargo (${ship.cargo_units || 0}/${ship.cargo_capacity || 0})</div>
      <div class="cargo-list">${cargoHtml}</div>
    </div>
    <div class="cmd-buttons">${btns}</div>
    <div style="margin-top:8px">
      <button class="btn" data-pause-ship="${escHtml(ship.symbol)}" data-paused="${isPaused ? '1' : '0'}">${pauseLabel}</button>
    </div>
    <div id="ship-recent-cmds" style="margin-top:12px">
      <div class="detail-label" style="margin-bottom:4px">Recent Commands</div>
      <div class="status-dim" style="font-size:0.85em">Loading…</div>
    </div>`;
}

async function loadRecentCmds(container, shipSymbol) {
  const el = container.querySelector('#ship-recent-cmds');
  if (!el) return;
  try {
    const res = await fetch(`/api/commands?limit=20`);
    if (!res.ok) { el.querySelector('div').textContent = '—'; return; }
    const all = await res.json();
    const cmds = all.filter((c) => c.ship_symbol === shipSymbol).slice(0, 5);
    if (!cmds.length) {
      el.innerHTML = '<div class="detail-label" style="margin-bottom:4px">Recent Commands</div><div class="status-dim" style="font-size:0.85em">None</div>';
      return;
    }
    const rows = cmds.map((c) => {
      const statusCls = c.status === 'done' ? 'status-ready' : c.status === 'failed' ? 'status-critical' : 'status-dim';
      return `<div style="font-size:0.85em;margin-bottom:2px">
        <span class="${statusCls}">[${escHtml(c.status)}]</span>
        ${escHtml(c.command)}
        ${c.result ? `<span class="status-dim"> → ${escHtml(JSON.stringify(JSON.parse(c.result)).slice(0, 60))}</span>` : ''}
      </div>`;
    }).join('');
    el.innerHTML = `<div class="detail-label" style="margin-bottom:4px">Recent Commands</div>${rows}`;
  } catch {
    el.innerHTML = '<div class="detail-label" style="margin-bottom:4px">Recent Commands</div>';
  }
}

function renderFleet(container) {
  const cols = [
    { key: 'symbol',     label: 'Ship' },
    { key: 'role',       label: 'Role' },
    { key: '_status',    label: 'Status',   render: (_, row) => fmtStatus(row) },
    { key: 'nav_waypoint', label: 'Location' },
    { key: '_fuel',      label: 'Fuel',     render: (_, row) =>
        `${row.fuel_current || 0}/${row.fuel_capacity || 0}` },
    { key: '_cargo',     label: 'Cargo',    render: (_, row) =>
        `${row.cargo_units || 0}/${row.cargo_capacity || 0}` },
    { key: 'condition_frame', label: 'Frame',  render: (v) => fmtCondition(v) },
  ];

  const ships = _ships;
  const selected = ships.find((s) => s.symbol === _selectedSymbol) || ships[0] || null;

  container.innerHTML = `
    <div class="view-header">
      <div class="view-title">Fleet</div>
    </div>
    <div class="fleet-layout">
      <div id="fleet-table-wrap"></div>
      <div class="detail-pane" id="fleet-detail">${renderDetail(selected)}</div>
    </div>`;

  const tableWrap = container.querySelector('#fleet-table-wrap');
  renderTable(tableWrap, cols, ships, {
    keyField: 'symbol',
    selectedKey: _selectedSymbol || (ships[0] && ships[0].symbol),
    onRowClick(ship) {
      _selectedSymbol = ship.symbol;
      container.querySelector('#fleet-detail').innerHTML = renderDetail(ship);
      wireDetailButtons(container, ship);
      loadRecentCmds(container, ship.symbol);
    },
  });

  wireDetailButtons(container, selected);
  if (selected) loadRecentCmds(container, selected.symbol);
}

function wireDetailButtons(container, ship) {
  if (!ship) return;
  container.querySelectorAll('.cmd-buttons .btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const cmd = btn.dataset.cmd;
      const prefill = cmd === 'sell' && Array.isArray(ship.cargo_inventory) && ship.cargo_inventory[0]
        ? { symbol: ship.cargo_inventory[0].symbol, units: ship.cargo_inventory[0].units }
        : {};
      await openCommandModal({ shipSymbol: ship.symbol, command: cmd, prefill });
    });
  });

  // Per-ship pause button
  container.querySelectorAll('[data-pause-ship]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const sym = btn.dataset.pauseShip;
      const currentlyPaused = btn.dataset.paused === '1';
      btn.disabled = true;
      try {
        await fetch(`/api/bot-control/ship/${encodeURIComponent(sym)}/pause`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ paused: !currentlyPaused }),
        });
      } catch { /* ignore */ } finally {
        btn.disabled = false;
      }
    });
  });
}

export function mountFleet(container) {
  _container = container;

  async function load() {
    try {
      const res = await fetch('/api/ships');
      _ships = res.ok ? await res.json() : [];
    } catch { _ships = []; }
    renderFleet(container);
  }

  const onUpdate = () => {
    if (window.ST.currentView !== 'fleet') return;
    _ships = window.ST.ships;
    renderFleet(container);
  };

  document.addEventListener('st:ship_update', onUpdate);
  document.addEventListener('st:agent_update', onUpdate);
  container.addEventListener('st:unmount', () => {
    document.removeEventListener('st:ship_update', onUpdate);
    document.removeEventListener('st:agent_update', onUpdate);
  });

  load();

  // Live cooldown countdown
  const tick = setInterval(() => {
    if (!container.isConnected) { clearInterval(tick); return; }
    if (window.ST.currentView !== 'fleet') return;
    _ships = window.ST.ships;
    const selected = _ships.find((s) => s.symbol === _selectedSymbol) || _ships[0];
    const detail = container.querySelector('#fleet-detail');
    if (detail && selected) {
      detail.innerHTML = renderDetail(selected);
      wireDetailButtons(container, selected);
    }
  }, 1000);
}
