const FIELD_DEFS = {
  navigate:        [{ name: 'waypoint', label: 'Waypoint Symbol', type: 'text', placeholder: 'X1-DF55-B3' }],
  buy:             [{ name: 'symbol', label: 'Trade Symbol', type: 'text', placeholder: 'IRON_ORE' },
                   { name: 'units', label: 'Units', type: 'number', placeholder: '10' }],
  sell:            [{ name: 'symbol', label: 'Trade Symbol', type: 'text', placeholder: 'IRON_ORE' },
                   { name: 'units', label: 'Units', type: 'number', placeholder: '10' }],
  refuel:          [{ name: 'from_cargo', label: 'From cargo?', type: 'checkbox' }],
  accept_contract: [{ name: 'contract_id', label: 'Contract ID', type: 'text', readonly: true }],
  dock:            [],
  orbit:           [],
  extract:         [],
};

export function openCommandModal({ shipSymbol, command, prefill = {} } = {}) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('modal-overlay');
    overlay.removeAttribute('hidden');

    const fields = FIELD_DEFS[command] ?? [];
    const fieldsHtml = fields.map((f) => {
      if (f.type === 'checkbox') {
        return `
          <div class="form-row checkbox-row">
            <input type="checkbox" id="f_${f.name}" name="${f.name}">
            <label for="f_${f.name}">${f.label}</label>
          </div>`;
      }
      const val = prefill[f.name] ?? '';
      const ro = f.readonly ? 'readonly' : '';
      return `
        <div class="form-row">
          <label for="f_${f.name}">${f.label}</label>
          <input type="${f.type}" id="f_${f.name}" name="${f.name}"
                 value="${val}" placeholder="${f.placeholder ?? ''}" ${ro}>
        </div>`;
    }).join('');

    overlay.innerHTML = `
      <div class="modal">
        <h2>${command.replace(/_/g, ' ').toUpperCase()}</h2>
        <div class="form-row">
          <label>Ship</label>
          <input type="text" value="${shipSymbol ?? '—'}" readonly>
        </div>
        ${fieldsHtml}
        <div class="modal-error" id="modal-error"></div>
        <div class="modal-buttons">
          <button class="btn" id="modal-cancel">Cancel</button>
          <button class="btn btn-primary" id="modal-submit">Submit</button>
        </div>
      </div>`;

    const cleanup = (result) => {
      overlay.setAttribute('hidden', '');
      overlay.innerHTML = '';
      resolve(result);
    };

    overlay.querySelector('#modal-cancel').addEventListener('click', () => cleanup(null));

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) cleanup(null);
    }, { once: true });

    overlay.querySelector('#modal-submit').addEventListener('click', async () => {
      const errEl = overlay.querySelector('#modal-error');
      errEl.textContent = '';

      const params = {};
      for (const f of fields) {
        const el = overlay.querySelector(`#f_${f.name}`);
        if (!el) continue;
        if (f.type === 'checkbox') {
          params[f.name] = el.checked;
        } else if (f.type === 'number') {
          params[f.name] = parseInt(el.value, 10);
        } else {
          params[f.name] = el.value.trim();
        }
      }

      const submitBtn = overlay.querySelector('#modal-submit');
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span>Submitting…';

      try {
        const res = await fetch('/api/commands', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ship_symbol: shipSymbol, command, params }),
        });

        if (res.ok) {
          const data = await res.json();
          document.dispatchEvent(new CustomEvent('st:command_queued', { detail: data }));
          cleanup(data);
        } else {
          const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
          const msg = typeof err.detail === 'string'
            ? err.detail
            : JSON.stringify(err.detail);
          errEl.textContent = msg;
          submitBtn.disabled = false;
          submitBtn.textContent = 'Submit';
        }
      } catch (e) {
        errEl.textContent = 'Network error. Try again.';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit';
      }
    });
  });
}
