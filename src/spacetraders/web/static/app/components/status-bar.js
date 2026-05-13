export function renderStatusBar(el, status) {
  if (!status) { el.textContent = 'Connecting…'; return; }

  const online = status.bot_online;
  const credits = (status.credits ?? 0).toLocaleString();
  const pending = status.pending_commands ?? 0;

  const botHtml = online
    ? `<span class="dot-online">● BOT ONLINE</span>`
    : `<span class="dot-offline">● BOT OFFLINE</span>`;

  const pendingHtml = pending > 0
    ? `<span class="status-pending">${pending} pending cmd${pending > 1 ? 's' : ''}</span>`
    : `<span class="status-dim">0 pending cmds</span>`;

  const resetHtml = status.reset_date
    ? `<span class="status-dim">[reset: ${status.reset_date}]</span>`
    : '';

  el.innerHTML = [
    `<span class="status-agent">${status.agent_symbol || '—'}</span>`,
    `<span class="status-sep">|</span>`,
    `<span class="status-credits">${credits} cr</span>`,
    `<span class="status-sep">|</span>`,
    `<span class="status-dim">${status.ship_count ?? 0} ships</span>`,
    `<span class="status-sep">|</span>`,
    botHtml,
    `<span class="status-sep">|</span>`,
    pendingHtml,
    resetHtml,
  ].join(' ');
}
