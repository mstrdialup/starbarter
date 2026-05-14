import { escHtml } from '../components/table.js';

let _container = null;

function fmtTs(ts) {
  if (!ts) return '?';
  try {
    return new Date(ts).toLocaleTimeString();
  } catch { return ts; }
}

const EVENT_ICONS = {
  extracted: '⛏',
  sold:       '💰',
  bought:     '🛒',
  trade_route:'📊',
  navigating: '→',
  discovery:  '🔍',
  refueled:   '⛽',
  warning:    '⚠',
  error:      '✗',
};

function renderActivity(rows) {
  if (!_container) return;
  if (!rows.length) {
    _container.querySelector('#activity-body').innerHTML =
      '<tr><td colspan="4" class="status-dim" style="text-align:center">No activity yet</td></tr>';
    return;
  }
  _container.querySelector('#activity-body').innerHTML = rows.map((r) => {
    const icon = EVENT_ICONS[r.event] || '•';
    return `<tr>
      <td class="status-dim" style="white-space:nowrap">${fmtTs(r.ts)}</td>
      <td>${escHtml(r.ship_symbol || '–')}</td>
      <td>${icon} ${escHtml(r.event)}</td>
      <td>${escHtml(r.detail || '')}</td>
    </tr>`;
  }).join('');
}

async function load(limit = 100) {
  try {
    const res = await fetch(`/api/activity?limit=${limit}`);
    const rows = res.ok ? await res.json() : [];
    renderActivity(rows);
  } catch { /* ignore */ }
}

export function mountActivity(container) {
  _container = container;

  container.innerHTML = `
    <div class="view-header">
      <div class="view-title">Activity Log</div>
    </div>
    <div style="overflow:auto;flex:1">
      <table class="data-table" style="width:100%">
        <thead>
          <tr>
            <th>Time</th>
            <th>Ship</th>
            <th>Event</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody id="activity-body"></tbody>
      </table>
    </div>`;

  const onUpdate = () => {
    if (window.ST.currentView !== 'activity') return;
    load();
  };

  document.addEventListener('st:activity_update', onUpdate);
  container.addEventListener('st:unmount', () => {
    document.removeEventListener('st:activity_update', onUpdate);
    _container = null;
  });

  load();
}
