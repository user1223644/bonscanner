let labelColorMap = {};
let currentPage = 1;
const pageSize = 25;
let itemCache = {};
const api = window.API;

function sanitizeNumericInput(value) {
  if (value === null || value === undefined) return "";
  let cleaned = String(value).replace(/[^\d,.\-]/g, "");
  if (cleaned === "") return "";

  const isNegative = cleaned.startsWith("-");
  cleaned = cleaned.replace(/-/g, "");
  const sign = isNegative ? "-" : "";

  let unsigned = cleaned;
  const lastComma = unsigned.lastIndexOf(",");
  const lastDot = unsigned.lastIndexOf(".");
  const sepIndex = Math.max(lastComma, lastDot);
  if (sepIndex !== -1) {
    const sepChar = unsigned[sepIndex];
    const intPart = unsigned.slice(0, sepIndex).replace(/[.,]/g, "");
    const fracPart = unsigned.slice(sepIndex + 1).replace(/[.,]/g, "");
    unsigned = intPart + sepChar + fracPart;
  } else {
    unsigned = unsigned.replace(/[.,]/g, "");
  }

  return sign + unsigned;
}

function normalizeDecimal(value) {
  return sanitizeNumericInput(value).replace(",", ".");
}

function isNumericString(value) {
  if (value === "" || value === "-" || value === "." || value === "-.") return false;
  return !Number.isNaN(Number.parseFloat(value));
}

function bindNumericInput(input) {
  if (!input || input.dataset.numericBound === "true") return;
  input.dataset.numericBound = "true";
  input.setAttribute("inputmode", "decimal");
  input.setAttribute("pattern", "[0-9]*[\\.,]?[0-9]*");
  input.addEventListener("input", () => {
    const cleaned = sanitizeNumericInput(input.value);
    if (cleaned !== input.value) input.value = cleaned;
  });
}

function bindNumericInputs(root = document) {
  root
    .querySelectorAll('input[data-numeric="true"]')
    .forEach((input) => bindNumericInput(input));
}

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
    const categories = await api.get("/categories");
    const palette = CATEGORY_COLORS.length ? CATEGORY_COLORS : ["#f5a623"];
    labelColorMap = {};
    categories.forEach((cat, i) => {
      labelColorMap[cat.name] = cat.color || palette[i % palette.length];
    });

    // Populate label filter dropdown
    const labelFilter = document.getElementById('label-filter');
    if (labelFilter) {
      const currentValue = labelFilter.value;
      labelFilter.innerHTML = '<option value="">Alle Kategorien</option>';
      categories.forEach((cat) => {
        const option = document.createElement('option');
        option.value = cat.name;
        option.textContent = cat.name;
        if (cat.name === currentValue) option.selected = true;
        labelFilter.appendChild(option);
      });
    }

    // Build query parameters from filters
    const params = new URLSearchParams();
    const textFilter = document.getElementById('text-filter')?.value.trim();
    const storeFilter = document.getElementById('store-filter')?.value.trim();
    const dateFrom = document.getElementById('date-from-filter')?.value;
    const dateTo = document.getElementById('date-to-filter')?.value;
    const amountMinRaw = document.getElementById('amount-min-filter')?.value;
    const amountMaxRaw = document.getElementById('amount-max-filter')?.value;
    const paymentFilter = document.getElementById('payment-filter')?.value.trim();
    const labelFilterValue = document.getElementById('label-filter')?.value;

    if (textFilter) params.append('text', textFilter);
    if (storeFilter) params.append('store', storeFilter);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    const amountMin = normalizeDecimal(amountMinRaw);
    if (isNumericString(amountMin)) params.append('amount_min', amountMin);
    const amountMax = normalizeDecimal(amountMaxRaw);
    if (isNumericString(amountMax)) params.append('amount_max', amountMax);
    if (paymentFilter) params.append('payment_method', paymentFilter);
    if (labelFilterValue) params.append('label', labelFilterValue);
    params.append('page', String(currentPage));
    params.append('page_size', String(pageSize));

    const queryString = params.toString();
    const url = `/receipts${queryString ? '?' + queryString : ''}`;

    const { data: receipts, res } = await api.requestWithResponse(url);
    const totalCountHeader = res.headers.get("X-Total-Count");
    const totalCount = totalCountHeader ? Number(totalCountHeader) : receipts.length;
    const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;
    const tbody = document.getElementById("receipts-body");

    itemCache = {};
    receipts.forEach((r) => {
      (r.items || []).forEach((item) => {
        if (item.id) itemCache[item.id] = { ...item, receipt_id: r.id };
      });
    });

    if (receipts.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="empty-state">Keine Belege vorhanden</td></tr>';
      updatePagination(totalPages, totalCount);
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
          <td><span class="editable" onclick="editField(${r.id}, 'payment_method', this)">${r.payment_method || "-"}</span></td>
          <td><span class="editable" onclick="editField(${r.id}, 'total', this)">${r.total ? r.total.toFixed(2) + " \u20ac" : "-"}</span></td>
        </tr>
        <tr id="details-${r.id}" class="detail-row" style="display: none;">
          <td colspan="6">
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
                  <input type="text" id="item-price-${r.id}" placeholder="Preis" class="item-input" data-numeric="true" />
                  <button onclick="saveNewItem(${r.id})" class="save-btn">Speichern</button>
                  <button onclick="cancelAddItem(${r.id})" class="cancel-btn">Abbrechen</button>
                </div>
              </div>
              <div class="detail-section">
                <div class="detail-header">
                  <strong>Steuern:</strong>
                </div>
                <div class="taxes-list">${renderTaxes(r.taxes)}</div>
              </div>
            </div>
          </td>
        </tr>
      `,
      )
      .join("");
    bindNumericInputs();
    updatePagination(totalPages, totalCount);
  } catch (e) {
    document.getElementById("receipts-body").innerHTML =
      '<tr><td colspan="6" class="empty-state">Fehler beim Laden</td></tr>';
    updatePagination(1, 0);
  }
}

// Debounce helper
let filterDebounceTimer;
function debounceFilter() {
  clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(() => {
    currentPage = 1;
    loadReceipts();
  }, 500);
}

function resetPageAndLoad() {
  currentPage = 1;
  loadReceipts();
}

function clearFilters() {
  document.getElementById('text-filter').value = '';
  document.getElementById('store-filter').value = '';
  document.getElementById('date-from-filter').value = '';
  document.getElementById('date-to-filter').value = '';
  document.getElementById('amount-min-filter').value = '';
  document.getElementById('amount-max-filter').value = '';
  document.getElementById('payment-filter').value = '';
  document.getElementById('label-filter').value = '';
  currentPage = 1;
  loadReceipts();
}

// Attach filter event listeners
document.addEventListener('DOMContentLoaded', () => {
  bindNumericInputs();
  document.getElementById('text-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('store-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('date-from-filter')?.addEventListener('change', resetPageAndLoad);
  document.getElementById('date-to-filter')?.addEventListener('change', resetPageAndLoad);
  document.getElementById('amount-min-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('amount-max-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('payment-filter')?.addEventListener('input', debounceFilter);
  document.getElementById('label-filter')?.addEventListener('change', resetPageAndLoad);
  document.getElementById('prev-page')?.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage -= 1;
      loadReceipts();
    }
  });
  document.getElementById('next-page')?.addEventListener('click', () => {
    currentPage += 1;
    loadReceipts();
  });
});

function updatePagination(totalPages, totalCount) {
  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  const info = document.getElementById('page-info');

  if (!prevBtn || !nextBtn || !info) return;

  const safeTotalPages = Math.max(1, totalPages);
  if (currentPage > safeTotalPages) currentPage = safeTotalPages;

  prevBtn.disabled = currentPage <= 1;
  nextBtn.disabled = currentPage >= safeTotalPages;
  info.textContent = `Seite ${currentPage} von ${safeTotalPages} · ${totalCount} Belege`;
}

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
        (item) => {
          const hasId = item.id !== undefined && item.id !== null;
          const actionButtons = hasId
            ? `<button class="item-category-btn" onclick="editItemCategories(${receiptId}, ${item.id})" title="Kategorien">Kategorien</button>
               <button class="delete-item-btn" onclick="deleteItem(${receiptId}, ${item.id})" title="Löschen">×</button>`
            : '';
          return `<div style="padding: 0.35rem 0; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="font-weight: 500;">${item.name || "-"}</div>
              ${formatItemMeta(item)}
              ${renderItemCategories(item)}
            </div>
            <div>
              <span style="color: var(--text-muted); margin-right: 1rem;">${item.price || ""}</span>
              ${actionButtons}
            </div>
          </div>`;
        },
      )
      .join("") +
    "</div>"
  );
}

function formatItemMeta(item) {
  const qty = item.quantity && item.quantity !== 1 ? item.quantity : null;
  const unit = item.unit ? ` ${item.unit}` : "";
  const unitPrice =
    typeof item.unit_price === "number"
      ? `${item.unit_price.toFixed(2)} €`
      : null;
  const parts = [];
  if (qty) parts.push(`${qty}${unit}`);
  if (unitPrice) parts.push(unitPrice);
  if (parts.length === 0 && item.is_discount) {
    parts.push("Rabatt");
  }
  if (parts.length === 0) return "";
  return `<div class="item-meta">${parts.join(" × ")}</div>`;
}

function renderItemCategories(item) {
  const categories = item.categories || [];
  if (!categories.length) {
    return '<div class="item-categories"><span class="category-tag none">Keine Kategorien</span></div>';
  }
  const tags = categories
    .map((cat) => {
      const color = cat.category_color || labelColorMap[cat.category_name] || "#f5a623";
      let suffix = "";
      if (cat.allocation_ratio) {
        suffix = ` (${Math.round(cat.allocation_ratio * 100)}%)`;
      } else if (cat.allocation_amount) {
        suffix = ` (${cat.allocation_amount.toFixed(2)} €)`;
      }
      return `<span class="category-tag" style="background: ${color}20; color: ${color}">${cat.category_name}${suffix}</span>`;
    })
    .join("");
  return `<div class="item-categories">${tags}</div>`;
}

function renderTaxes(taxes) {
  if (!taxes || taxes.length === 0) {
    return '<span style="color: var(--text-muted);">Keine Steuerangaben</span>';
  }
  return taxes
    .map((tax) => {
      const rate = tax.tax_rate ? `${tax.tax_rate}%` : "";
      const amount =
        typeof tax.tax_amount === "number" ? `${tax.tax_amount.toFixed(2)} €` : "";
      return `<div>${rate} ${amount}</div>`;
    })
    .join("");
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
  const priceRaw = document.getElementById(`item-price-${receiptId}`).value;
  const priceValue = normalizeDecimal(priceRaw);
  const price = Number.parseFloat(priceValue);

  if (!name) {
    alert("Bitte Artikelname eingeben");
    return;
  }

  try {
    await api.post(`/receipts/${receiptId}/items`, {
      name,
      price: Number.isNaN(price) ? 0 : price,
    });
    cancelAddItem(receiptId);
    await loadReceipts();
  } catch (e) {
    alert("Fehler beim Hinzufügen des Artikels");
  }
}

async function deleteItem(receiptId, itemId) {
  if (!confirm("Artikel wirklich löschen?")) {
    return;
  }

  try {
    await api.delete(`/receipts/${receiptId}/items/${itemId}`);
    await loadReceipts();
  } catch (e) {
    alert("Fehler beim Löschen des Artikels");
  }
}

function parseCategoryAllocations(value) {
  if (!value) return [];
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((entry) => {
      const bits = entry.split(/[:=]/).map((p) => p.trim());
      const name = bits[0];
      const raw = bits[1];
      const allocation = { category_name: name, source: "manual" };
      if (!raw) return allocation;
      const num = Number(raw.replace("%", "").replace(",", "."));
      if (Number.isFinite(num)) {
        if (raw.includes("%")) {
          allocation.allocation_ratio = num / 100;
        } else if (num <= 1) {
          allocation.allocation_ratio = num;
        } else {
          allocation.allocation_amount = num;
        }
      }
      return allocation;
    });
}

async function editItemCategories(receiptId, itemId) {
  const item = itemCache[itemId];
  const existing = (item?.categories || [])
    .map((cat) => {
      if (cat.allocation_ratio) {
        return `${cat.category_name}=${Math.round(cat.allocation_ratio * 100)}%`;
      }
      if (cat.allocation_amount) {
        return `${cat.category_name}=${cat.allocation_amount}`;
      }
      return cat.category_name;
    })
    .join(", ");
  const input = prompt(
    "Kategorien (z.B. Lebensmittel=60%, Haushalt=40%)",
    existing,
  );
  if (input === null) return;
  const categories = parseCategoryAllocations(input);
  try {
    await api.patch(`/receipts/${receiptId}/items/${itemId}/categories`, {
      categories,
    });
    await loadReceipts();
  } catch (e) {
    alert("Fehler beim Speichern der Kategorien");
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
  const cell = el.closest("td") || el.parentElement;
  if (!cell || cell.querySelector("input.edit-input")) return;

  const currentValue = el.textContent.replace(" €", "").trim();
  const input = document.createElement("input");
  input.className = "edit-input";
  if (field === "total") {
    input.type = "text";
    input.dataset.numeric = "true";
    bindNumericInput(input);
  }
  input.value = currentValue === "-" ? "" : currentValue;

  const cellRect = cell.getBoundingClientRect();
  const anchorRect = el.getBoundingClientRect();
  const cellStyle = window.getComputedStyle(cell);
  const cellPaddingRight = Number.parseFloat(cellStyle.paddingRight) || 0;

  const offsetLeft = Math.max(0, anchorRect.left - cellRect.left);
  const offsetTop = Math.max(0, anchorRect.top - cellRect.top);
  const inputWidth = Math.max(
    40,
    cellRect.width - offsetLeft - cellPaddingRight,
  );
  const inputHeight = Math.max(24, anchorRect.height);

  const previousPosition = cell.style.position;
  cell.style.position = "relative";
  el.style.visibility = "hidden";

  input.style.position = "absolute";
  input.style.left = `${offsetLeft}px`;
  input.style.top = `${offsetTop}px`;
  input.style.width = `${inputWidth}px`;
  input.style.height = `${inputHeight}px`;
  input.style.zIndex = "2";

  cell.appendChild(input);
  input.focus();
  input.select();

  let didCleanup = false;
  let isSaving = false;
  const cleanup = () => {
    if (didCleanup) return;
    didCleanup = true;
    input.remove();
    el.style.visibility = "";
    cell.style.position = previousPosition;
  };

  const save = async () => {
    if (didCleanup || isSaving) return;
    isSaving = true;
    const payload = { [field]: input.value.trim() || null };
    try {
      await api.patch(`/receipts/${id}`, payload);
    } catch (e) {
      console.error(e);
    }
    cleanup();
    loadReceipts();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") {
      cleanup();
      loadReceipts();
    }
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

  let finished = false;

  const save = async () => {
    if (finished) return;
    finished = true;

    const value = input.value.trim();
    if (value) {
      const newLabels = value
        .split(",")
        .map((l) => l.trim())
        .filter((l) => l);

      const allLabels = [...new Set([...labelsData, ...newLabels])];

      await api.patch(`/receipts/${id}/labels`, { labels: allLabels });
    }
    loadReceipts();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") {
      finished = true;
      loadReceipts();
    }
  });
  input.addEventListener("blur", save);
}

async function deleteLabel(id, label, event) {
  event.stopPropagation();
  const row = document.querySelector(`tr[data-id="${id}"]`);
  const labelsData = row ? JSON.parse(row.dataset.labels || "[]") : [];

  const newLabels = labelsData.filter((l) => l !== label);

  await api.patch(`/receipts/${id}/labels`, { labels: newLabels });

  loadReceipts();
}

loadReceipts();
