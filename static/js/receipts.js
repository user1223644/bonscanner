let labelColorMap = {};

function formatDate(dateStr) {
  if (!dateStr || dateStr === '-') return '-';
  
  // Try to parse various date formats and convert to DD.MM.YYYY
  let day, month, year;
  
  // Format: DD.MM.YYYY or DD/MM/YYYY
  let match = dateStr.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})$/);
  if (match) {
    day = match[1];
    month = match[2];
    year = match[3];
  } else {
    // Format: MM/DD/YYYY (US format)
    match = dateStr.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (match) {
      month = match[1];
      day = match[2];
      year = match[3];
    } else {
      // Format: YYYY-MM-DD (ISO)
      match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (match) {
        year = match[1];
        month = match[2];
        day = match[3];
      } else {
        // Can't parse, return as-is
        return dateStr;
      }
    }
  }
  
  // Pad with zeros and return DD.MM.YYYY
  return `${String(day).padStart(2, '0')}.${String(month).padStart(2, '0')}.${year}`;
}

async function loadReceipts() {
  try {
    const statsRes = await fetch(`${API_URL}/stats`);
    const stats = await statsRes.json();
    const categoryData = stats.category_totals || {};
    const sorted = Object.entries(categoryData).sort((a, b) => b[1] - a[1]);
    labelColorMap = {};
    sorted.forEach((e, i) => {
      labelColorMap[e[0]] = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
    });

    // Populate label filter dropdown
    const labelFilter = document.getElementById('label-filter');
    if (labelFilter && labelFilter.options.length === 1) {
      sorted.forEach(([label]) => {
        const option = document.createElement('option');
        option.value = label;
        option.textContent = label;
        labelFilter.appendChild(option);
      });
    }

    // Build query parameters from filters
    const params = new URLSearchParams();
    const storeFilter = document.getElementById('store-filter')?.value.trim();
    const dateFrom = document.getElementById('date-from-filter')?.value;
    const dateTo = document.getElementById('date-to-filter')?.value;
    const labelFilterValue = document.getElementById('label-filter')?.value;

    if (storeFilter) params.append('store', storeFilter);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (labelFilterValue) params.append('label', labelFilterValue);

    const queryString = params.toString();
    const url = `${API_URL}/receipts${queryString ? '?' + queryString : ''}`;
    
    const res = await fetch(url);
    const receipts = await res.json();
    const tbody = document.getElementById("receipts-body");

    if (receipts.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="5" class="empty-state">Keine Belege vorhanden</td></tr>';
      return;
    }

    tbody.innerHTML = receipts
      .map(
        (r) => `
        <tr data-id="${r.id}" data-labels='${JSON.stringify(r.labels || [])}' class="receipt-row">
          <td><span class="editable" onclick="editField(${r.id}, 'date', this)">${formatDate(r.date)}</span></td>
          <td><span class="editable" onclick="editField(${r.id}, 'store_name', this)">${r.store_name || "-"}</span></td>
          <td style="text-align: center;">
            <button class="detail-btn" onclick="toggleDetails(${r.id}, event)" title="Details anzeigen">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
          </td>
          <td>${renderCategories(r.id, r.labels)}</td>
          <td><span class="editable" onclick="editField(${r.id}, 'total', this)">${r.total ? r.total.toFixed(2) + " \u20ac" : "-"}</span></td>
        </tr>
        <tr id="details-${r.id}" class="detail-row" style="display: none;">
          <td colspan="5">
            <div class="detail-content">
              <div class="detail-section">
                <div class="detail-header">
                  <strong>Artikel:</strong>
                  <button class="add-item-btn" onclick="showAddItemForm(${r.id})" title="Artikel hinzufügen">+ Artikel</button>
                </div>
                <div id="items-${r.id}" class="items-list">
                  ${renderItemsDetailEditable(r.id, r.items)}
                </div>
                <div id="add-item-form-${r.id}" class="add-item-form" style="display: none;">
                  <input type="text" id="item-name-${r.id}" placeholder="Artikelname" class="item-input" />
                  <input type="number" id="item-price-${r.id}" placeholder="Preis" step="0.01" class="item-input" />
                  <button onclick="saveNewItem(${r.id})" class="save-btn">Speichern</button>
                  <button onclick="cancelAddItem(${r.id})" class="cancel-btn">Abbrechen</button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      `,
      )
      .join("");
  } catch (e) {
    document.getElementById("receipts-body").innerHTML =
      '<tr><td colspan="5" class="empty-state">Fehler beim Laden</td></tr>';
  }
}

// Debounce helper
let filterDebounceTimer;
function debounceFilter() {
  clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(loadReceipts, 500);
}

function clearFilters() {
  document.getElementById('store-filter').value = '';
  document.getElementById('date-from-filter').value = '';
  document.getElementById('date-to-filter').value = '';
  document.getElementById('label-filter').value = '';
  loadReceipts();
}

// Attach filter event listeners
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('store-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('date-from-filter')?.addEventListener('change', loadReceipts);
  document.getElementById('date-to-filter')?.addEventListener('change', loadReceipts);
  document.getElementById('label-filter')?.addEventListener('change', loadReceipts);
});

function renderItemsDetail(items) {
  if (!items || items.length === 0) {
    return '<span style="color: var(--text-muted);">Keine Artikel</span>';
  }
  return (
    '<div style="margin-top: 0.5rem;">' +
    items
      .map(
        (item) =>
          `<div style="padding: 0.35rem 0; border-bottom: 1px solid var(--border-color);"><span style="font-weight: 500;">${item.name || "-"}</span> <span style="color: var(--text-muted); float: right;">${item.price || ""}</span></div>`,
      )
      .join("") +
    "</div>"
  );
}

function renderItemsDetailEditable(receiptId, items) {
  if (!items || items.length === 0) {
    return '<span style="color: var(--text-muted);">Keine Artikel</span>';
  }
  return (
    '<div style="margin-top: 0.5rem;">' +
    items
      .map(
        (item) =>
          `<div style="padding: 0.35rem 0; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: 500;">${item.name || "-"}</span>
            <div>
              <span style="color: var(--text-muted); margin-right: 1rem;">${item.price || ""}</span>
              <button class="delete-item-btn" onclick="deleteItem(${receiptId}, ${item.id})" title="Löschen">×</button>
            </div>
          </div>`,
      )
      .join("") +
    "</div>"
  );
}

function showAddItemForm(receiptId) {
  const form = document.getElementById(`add-item-form-${receiptId}`);
  form.style.display = "block";
  document.getElementById(`item-name-${receiptId}`).focus();
}

function cancelAddItem(receiptId) {
  const form = document.getElementById(`add-item-form-${receiptId}`);
  form.style.display = "none";
  document.getElementById(`item-name-${receiptId}`).value = "";
  document.getElementById(`item-price-${receiptId}`).value = "";
}

async function saveNewItem(receiptId) {
  const name = document.getElementById(`item-name-${receiptId}`).value.trim();
  const price = document.getElementById(`item-price-${receiptId}`).value;

  if (!name) {
    alert("Bitte Artikelname eingeben");
    return;
  }

  try {
    const res = await fetch(`${API_URL}/receipts/${receiptId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, price: parseFloat(price) || 0 }),
    });

    if (res.ok) {
      cancelAddItem(receiptId);
      await loadReceipts();
    }
  } catch (e) {
    alert("Fehler beim Hinzufügen des Artikels");
  }
}

async function deleteItem(receiptId, itemId) {
  if (!confirm("Artikel wirklich löschen?")) {
    return;
  }

  try {
    const res = await fetch(`${API_URL}/receipts/${receiptId}/items/${itemId}`, {
      method: "DELETE",
    });

    if (res.ok) {
      await loadReceipts();
    }
  } catch (e) {
    alert("Fehler beim Löschen des Artikels");
  }
}

function toggleDetails(id, event) {
  event.stopPropagation();
  const detailRow = document.getElementById(`details-${id}`);
  const btn = event.currentTarget;
  const svg = btn.querySelector("svg");

  if (detailRow.style.display === "none") {
    detailRow.style.display = "table-row";
    svg.style.transform = "rotate(180deg)";
  } else {
    detailRow.style.display = "none";
    svg.style.transform = "rotate(0deg)";
  }
}

function renderCategories(id, labels) {
  const tags = (labels || [])
    .map((l) => {
      const color = labelColorMap[l] || "#f5a623";
      return `<span class="category-tag" style="background: ${color}20; color: ${color}">${l} <button class="delete-tag-btn" onclick="deleteLabel(${id}, '${l.replace(/'/g, "\\'")}', event)" title="Entfernen">×</button></span>`;
    })
    .join("");
  return (
    tags +
    `<span class="add-category" onclick="addCategory(${id}, this)" title="Labels hinzufügen (kommagetrennt)">+</span>`
  );
}

function editField(id, field, el) {
  const currentValue = el.textContent.replace(" €", "").trim();
  const input = document.createElement("input");
  input.className = "edit-input";
  input.value = currentValue === "-" ? "" : currentValue;
  el.replaceWith(input);
  input.focus();
  input.select();

  const save = async () => {
    const payload = {};
    payload[field] = input.value.trim() || null;
    await fetch(`${API_URL}/receipts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    loadReceipts();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") loadReceipts();
  });
  input.addEventListener("blur", save);
}

function addCategory(id, el) {
  const row = document.querySelector(`tr[data-id="${id}"]`);
  const labelsData = row ? JSON.parse(row.dataset.labels || "[]") : [];

  const input = document.createElement("input");
  input.className = "edit-input";
  input.style.width = "150px";
  input.placeholder = "Labels (kommagetrennt)";
  el.replaceWith(input);
  input.focus();

  const save = async () => {
    if (input.value.trim()) {
      const newLabels = input.value
        .split(",")
        .map((l) => l.trim())
        .filter((l) => l);

      const allLabels = [...new Set([...labelsData, ...newLabels])];

      await fetch(`${API_URL}/receipts/${id}/labels`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labels: allLabels }),
      });
    }
    loadReceipts();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") loadReceipts();
  });
  input.addEventListener("blur", save);
}

async function deleteLabel(id, label, event) {
  event.stopPropagation();
  const row = document.querySelector(`tr[data-id="${id}"]`);
  const labelsData = row ? JSON.parse(row.dataset.labels || "[]") : [];

  const newLabels = labelsData.filter((l) => l !== label);

  await fetch(`${API_URL}/receipts/${id}/labels`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labels: newLabels }),
  });

  loadReceipts();
}

loadReceipts();
