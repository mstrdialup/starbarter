import { renderTable } from '../components/table.js';

export function mountTransactions(container) {
  let _limit = 50;

  async function loadSummary() {
    try {
      const res = await fetch('/api/transactions/summary');
      return res.ok ? await res.json() : null;
    } catch { return null; }
  }

  async function loadTransactions() {
    try {
      const res = await fetch(`/api/transactions?limit=${_limit}`);
      return res.ok ? await res.json() : [];
    } catch { return []; }
  }

  async function render() {
    const [summary, rows] = await Promise.all([loadSummary(), loadTransactions()]);

    const summaryHtml = summary ? `
      <div class="panel" style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px">
        <div>
          <div class="detail-label">Total Revenue</div>
          <div class="sell-color" style="font-size:18px;font-weight:700">
            ${(summary.total_revenue || 0).toLocaleString()}
          </div>
        </div>
        <div>
          <div class="detail-label">Total Cost</div>
          <div class="buy-color" style="font-size:18px;font-weight:700">
            ${(summary.total_cost || 0).toLocaleString()}
          </div>
        </div>
        <div>
          <div class="detail-label">Net P&amp;L</div>
          <div class="${(summary.net_pnl || 0) >= 0 ? 'status-ready' : 'sell-color'}" style="font-size:18px;font-weight:700">
            ${(summary.net_pnl || 0) >= 0 ? '+' : ''}${(summary.net_pnl || 0).toLocaleString()}
          </div>
        </div>
        <div>
          <div class="detail-label">Transactions</div>
          <div style="font-size:18px;font-weight:700">${(summary.count || 0).toLocaleString()}</div>
        </div>
      </div>` : '';

    const cols = [
      { key: 'timestamp',    label: 'Time',
        render: (v) => v ? new Date(v).toISOString().slice(0, 19).replace('T', ' ') : '?' },
      { key: 'ship_symbol',  label: 'Ship' },
      { key: 'waypoint_symbol', label: 'Waypoint' },
      { key: 'trade_symbol', label: 'Good' },
      { key: 'type',         label: 'Type',
        render: (v) => {
          const cls = v === 'SELL' ? 'sell-color' : v === 'PURCHASE' ? 'buy-color' : '';
          return cls ? `<span class="${cls}">${v}</span>` : (v || '');
        }},
      { key: 'units',        label: 'Units' },
      { key: 'price_per_unit', label: 'Unit Price' },
      { key: 'total_price',  label: 'Total',
        render: (v, row) => {
          const cls = row.type === 'SELL' ? 'sell-color' : 'buy-color';
          return `<span class="${cls}">${(v || 0).toLocaleString()}</span>`;
        }},
    ];

    container.innerHTML = `
      <div class="view-header">
        <div class="view-title">Transactions</div>
        <div class="view-header-actions">
          <select id="limit-sel" style="font-size:12px;padding:4px 8px">
            <option value="50" ${_limit === 50 ? 'selected' : ''}>Last 50</option>
            <option value="100" ${_limit === 100 ? 'selected' : ''}>Last 100</option>
            <option value="500" ${_limit === 500 ? 'selected' : ''}>Last 500</option>
          </select>
        </div>
      </div>
      ${summaryHtml}
      <div id="tx-table"></div>`;

    const wrap = container.querySelector('#tx-table');
    if (wrap) renderTable(wrap, cols, rows);

    container.querySelector('#limit-sel')?.addEventListener('change', (e) => {
      _limit = parseInt(e.target.value, 10);
      render();
    });
  }

  const onUpdate = () => { if (window.ST.currentView === 'transactions') render(); };
  document.addEventListener('st:command_update', onUpdate);
  container.addEventListener('st:unmount', () =>
    document.removeEventListener('st:command_update', onUpdate));

  render();
}
