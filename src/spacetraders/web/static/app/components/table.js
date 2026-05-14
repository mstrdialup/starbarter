/**
 * Minimal sortable table component.
 * cols: [{key, label, render?}]
 * rows: array of objects
 * onRowClick?: (row) => void
 */
export function renderTable(container, cols, rows, { onRowClick, selectedKey, keyField } = {}) {
  const thead = cols.map((c) =>
    `<th data-key="${c.key}">${c.label}</th>`
  ).join('');

  const tbody = rows.map((row) => {
    const sel = keyField && row[keyField] === selectedKey ? ' class="selected"' : '';
    const cells = cols.map((c) => {
      const raw = row[c.key] ?? '';
      const rendered = c.render ? c.render(raw, row) : escHtml(String(raw));
      return `<td>${rendered}</td>`;
    }).join('');
    return `<tr${sel} data-key="${keyField ? row[keyField] : ''}">${cells}</tr>`;
  }).join('');

  container.innerHTML = `
    <table class="data-table">
      <thead><tr>${thead}</tr></thead>
      <tbody>${tbody}</tbody>
    </table>`;

  // Sort on header click
  container.querySelectorAll('th').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      const asc = !th.classList.contains('sort-asc');
      container.querySelectorAll('th').forEach((h) =>
        h.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(asc ? 'sort-asc' : 'sort-desc');
      const sorted = [...rows].sort((a, b) => {
        const av = a[key] ?? '', bv = b[key] ?? '';
        if (typeof av === 'number' && typeof bv === 'number')
          return asc ? av - bv : bv - av;
        return asc
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av));
      });
      renderTable(container, cols, sorted, { onRowClick, selectedKey, keyField });
    });
  });

  if (onRowClick) {
    container.querySelectorAll('tbody tr').forEach((tr) => {
      tr.addEventListener('click', () => {
        const k = tr.dataset.key;
        const row = keyField ? rows.find((r) => String(r[keyField]) === k) : null;
        if (row) onRowClick(row);
      });
    });
  }
}

export function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
