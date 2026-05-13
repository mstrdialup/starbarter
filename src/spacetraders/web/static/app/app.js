import { mountFleet } from './views/fleet.js';
import { mountContracts } from './views/contracts.js';
import { mountMarkets } from './views/markets.js';
import { mountTransactions } from './views/transactions.js';
import { renderStatusBar } from './components/status-bar.js';

// ── Global state ────────────────────────────────────────────────────────────
window.ST = {
  ships: [],
  agent: null,
  contracts: [],
  status: null,
  currentView: null,
};

// ── Router ───────────────────────────────────────────────────────────────────
const VIEWS = {
  fleet:        mountFleet,
  contracts:    mountContracts,
  markets:      mountMarkets,
  transactions: mountTransactions,
};

function navigate(viewName) {
  if (!VIEWS[viewName]) viewName = 'fleet';
  document.querySelectorAll('.nav-item').forEach((el) =>
    el.classList.toggle('active', el.dataset.view === viewName)
  );
  const container = document.getElementById('view-container');
  container.innerHTML = '';
  window.ST.currentView = viewName;
  VIEWS[viewName](container);
}

window.addEventListener('hashchange', () =>
  navigate(location.hash.slice(1) || 'fleet')
);

// ── SSE client ───────────────────────────────────────────────────────────────
function connectSSE() {
  const sse = new EventSource('/events');

  sse.addEventListener('agent_update', (e) => {
    window.ST.agent = JSON.parse(e.data);
    document.dispatchEvent(new CustomEvent('st:agent_update', { detail: window.ST.agent }));
  });

  sse.addEventListener('ship_update', (e) => {
    const ship = JSON.parse(e.data);
    try { ship.cargo_inventory = JSON.parse(ship.cargo_inventory || '[]'); } catch { ship.cargo_inventory = []; }
    const idx = window.ST.ships.findIndex((s) => s.symbol === ship.symbol);
    if (idx >= 0) window.ST.ships[idx] = ship; else window.ST.ships.push(ship);
    document.dispatchEvent(new CustomEvent('st:ship_update', { detail: ship }));
  });

  sse.addEventListener('command_update', (e) => {
    document.dispatchEvent(new CustomEvent('st:command_update', { detail: JSON.parse(e.data) }));
  });

  sse.addEventListener('market_update', () => {
    document.dispatchEvent(new CustomEvent('st:market_update'));
  });

  sse.addEventListener('keepalive', () => {});

  sse.onerror = () => {
    sse.close();
    setTimeout(connectSSE, 5000);
  };
}

// ── Status bar ───────────────────────────────────────────────────────────────
async function refreshStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    window.ST.status = await res.json();
    renderStatusBar(document.getElementById('status-bar'), window.ST.status);
  } catch { /* network error */ }
}

document.addEventListener('st:agent_update', refreshStatus);
document.addEventListener('st:command_update', refreshStatus);
setInterval(refreshStatus, 10_000);

// ── Service worker ───────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ── Boot ─────────────────────────────────────────────────────────────────────
connectSSE();
refreshStatus();
navigate(location.hash.slice(1) || 'fleet');
