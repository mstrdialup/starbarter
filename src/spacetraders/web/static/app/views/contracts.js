import { escHtml } from '../components/table.js';
import { openCommandModal } from '../components/command-modal.js';

function deadlineClass(deadline) {
  if (!deadline) return '';
  const diff = (new Date(deadline) - Date.now()) / 3600000; // hours
  if (diff < 1) return 'deadline-crit';
  if (diff < 6) return 'deadline-warn';
  return '';
}

function fmtDeadline(iso) {
  if (!iso) return '—';
  const cls = deadlineClass(iso);
  const d = new Date(iso);
  const label = d.toISOString().slice(0, 16).replace('T', ' ');
  return cls ? `<span class="${cls}">${label}</span>` : label;
}

function renderContract(c) {
  const statusLabel = c.fulfilled ? 'Fulfilled' : c.accepted ? 'In Progress' : 'Not Accepted';
  const statusCls = c.fulfilled ? 'status-ready' : c.accepted ? 'status-transit' : 'status-dim';
  const payment = c.terms?.payment || {};
  const deliverRows = (c.deliver_progress || []).map((d) => {
    const pct = d.required ? (d.fulfilled / d.required) * 100 : 0;
    return `
      <div style="margin-top:8px">
        <div style="font-size:11px;color:var(--text-label);margin-bottom:3px">
          ${escHtml(d.trade_symbol)} → ${escHtml(d.destination)}
        </div>
        <div class="progress-wrap">
          <progress value="${d.fulfilled}" max="${d.required}"></progress>
          <span>${d.fulfilled} / ${d.required}</span>
        </div>
      </div>`;
  }).join('');

  const acceptBtn = !c.accepted && !c.fulfilled
    ? `<button class="btn btn-primary accept-btn" data-id="${escHtml(c.id)}" style="margin-top:10px">
         Accept Contract
       </button>`
    : '';

  return `
    <div class="panel" data-contract-id="${escHtml(c.id)}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <span style="font-weight:700;font-size:13px">${escHtml(c.id.slice(0, 14))}…</span>
          <span class="status-dim" style="margin-left:8px;font-size:11px">${escHtml(c.type || '')}</span>
          <span class="status-dim" style="margin-left:8px;font-size:11px">${escHtml(c.faction || '')}</span>
        </div>
        <span class="${statusCls}" style="font-size:11px">${statusLabel}</span>
      </div>
      <div style="font-size:11px;color:var(--text-label)">
        Deadline: ${fmtDeadline(c.deadline)}
      </div>
      <div style="font-size:11px;color:var(--text-label);margin-top:2px">
        Payment: <span class="sell-color">${(payment.onAccepted || 0).toLocaleString()} on accept</span>
        + <span class="sell-color">${(payment.onFulfilled || 0).toLocaleString()} on fulfill</span>
      </div>
      ${deliverRows}
      ${acceptBtn}
    </div>`;
}

export function mountContracts(container) {
  let contracts = [];

  async function load() {
    try {
      const res = await fetch('/api/contracts');
      contracts = res.ok ? await res.json() : [];
    } catch { contracts = []; }
    render();
  }

  function render() {
    container.innerHTML = `
      <div class="view-header">
        <div class="view-title">Contracts</div>
      </div>
      ${contracts.length
        ? contracts.map(renderContract).join('')
        : '<p class="status-dim">No contracts found.</p>'}`;

    container.querySelectorAll('.accept-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        await openCommandModal({
          shipSymbol: null,
          command: 'accept_contract',
          prefill: { contract_id: id },
        });
      });
    });
  }

  document.addEventListener('st:command_update', load);
  container.addEventListener('st:unmount', () =>
    document.removeEventListener('st:command_update', load));

  load();
}
