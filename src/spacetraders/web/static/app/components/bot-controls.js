/**
 * Bot controls section — rendered inside the sidebar.
 * Shows global pause and per-feature toggles.
 */

async function setControl(key, value) {
  try {
    await fetch('/api/bot-control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    });
  } catch { /* ignore */ }
}

export function renderBotControls(container, flags) {
  if (!container) return;
  const paused = flags['global_pause'] === 'true';
  const mining = flags['mining_enabled'] !== 'false';
  const trading = flags['trading_enabled'] !== 'false';
  const discovery = flags['price_discovery_enabled'] !== 'false';

  container.innerHTML = `
    <div class="ctrl-section-label">Bot Controls</div>
    <div class="ctrl-btn-row">
      <button class="btn-ctrl ${paused ? 'ctrl-active' : ''}"
              data-ctrl="global_pause" data-val="${paused ? 'false' : 'true'}">
        ${paused ? '▶ Resume All' : '⏸ Pause All'}
      </button>
      <button class="btn-ctrl ${!mining ? 'ctrl-off' : ''}"
              data-ctrl="mining_enabled" data-val="${mining ? 'false' : 'true'}">
        ⛏ Mining: ${mining ? 'ON' : 'OFF'}
      </button>
      <button class="btn-ctrl ${!trading ? 'ctrl-off' : ''}"
              data-ctrl="trading_enabled" data-val="${trading ? 'false' : 'true'}">
        ⚖ Trading: ${trading ? 'ON' : 'OFF'}
      </button>
      <button class="btn-ctrl ${!discovery ? 'ctrl-off' : ''}"
              data-ctrl="price_discovery_enabled" data-val="${discovery ? 'false' : 'true'}">
        🔍 Discovery: ${discovery ? 'ON' : 'OFF'}
      </button>
    </div>`;

  container.querySelectorAll('.btn-ctrl').forEach((btn) => {
    btn.addEventListener('click', () => {
      setControl(btn.dataset.ctrl, btn.dataset.val);
    });
  });
}
