let spendingChart = null;
let categoryChart = null;
let labelColorMap = {};
let categoriesCache = [];

const MAX_SCROLL_RESTORE_DELTA_X = 60;
const MAX_SCROLL_RESTORE_DELTA_Y = 120;

function restoreScrollNear(targetX, targetY) {
  const dx = Math.abs(window.scrollX - targetX);
  const dy = Math.abs(window.scrollY - targetY);
  if (dx <= MAX_SCROLL_RESTORE_DELTA_X && dy <= MAX_SCROLL_RESTORE_DELTA_Y) {
    window.scrollTo(targetX, targetY);
  }
}

function restoreScrollLater(scrollX, scrollY) {
  restoreScrollNear(scrollX, scrollY);
  requestAnimationFrame(() => restoreScrollNear(scrollX, scrollY));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => {
    switch (ch) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return ch;
    }
  });
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

function getPalette() {
  return typeof CATEGORY_COLORS !== "undefined" && CATEGORY_COLORS.length
    ? CATEGORY_COLORS
    : ["#f5a623", "#4ade80", "#60a5fa", "#f472b6", "#a78bfa"];
}

function buildLabelColorMap(categories) {
  const palette = getPalette();
  labelColorMap = {};
  (categories || []).forEach((cat, index) => {
    const color = cat.color || palette[index % palette.length];
    labelColorMap[cat.name] = color;
  });
}

async function loadCategories() {
  try {
    const res = await fetch(`${API_URL}/categories`);
    categoriesCache = await res.json();
  } catch (e) {
    categoriesCache = [];
  }
  buildLabelColorMap(categoriesCache);
  renderCategoriesManager(categoriesCache);
  renderRuleCategoryOptions(categoriesCache);
}

async function loadStats() {
  try {
    const res = await fetch(`${API_URL}/stats`);
    const data = await res.json();

    document.getElementById("stats-row").innerHTML = `
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">Gesamtausgaben</span>
          <div class="stat-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v12M9 9h6M9 15h6"/></svg></div>
        </div>
        <div class="stat-value">${data.sum.toFixed(2)} €</div>
      </div>
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">Belege gescannt</span>
          <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg></div>
        </div>
        <div class="stat-value">${data.count}</div>
      </div>
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">Durchschnitt</span>
          <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M18 9l-5 5-4-4-3 3"/></svg></div>
        </div>
        <div class="stat-value">${data.average.toFixed(2)} €</div>
      </div>
    `;

    renderSpendingChart(data.monthly_totals || {});
    renderCategoryChart(data.category_totals || {});
  } catch (e) {
    document.getElementById("stats-row").innerHTML =
      '<div class="empty-state">Fehler beim Laden</div>';
  }
}

function renderSpendingChart(monthlyData) {
  const labels = Object.keys(monthlyData);
  const values = Object.values(monthlyData);

  const ctx = document.getElementById("spending-chart").getContext("2d");

  if (spendingChart) spendingChart.destroy();

  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, "rgba(245, 166, 35, 0.3)");
  gradient.addColorStop(1, "rgba(245, 166, 35, 0.0)");

  const style = getComputedStyle(document.body);
  const gridColor = style.getPropertyValue("--border-color").trim();
  const textColor = style.getPropertyValue("--text-secondary").trim();
  const accentColor = style.getPropertyValue("--accent").trim();

  spendingChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Ausgaben (€)",
          data: values,
          borderColor: accentColor,
          backgroundColor: gradient,
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 4,
          pointBackgroundColor: accentColor,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { 
        legend: { display: false },
        tooltip: {
          backgroundColor: style.getPropertyValue("--bg-card").trim(),
          titleColor: textColor,
          bodyColor: textColor,
          borderColor: gridColor,
          borderWidth: 1,
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: { color: gridColor },
          ticks: { 
            callback: (v) => v + " €",
            color: textColor
          },
        },
        x: {
          grid: { display: false },
          ticks: { color: textColor }
        },
      },
    },
  });
}

function renderCategoryChart(categoryData) {
  const sortedEntries = Object.entries(categoryData).sort((a, b) => b[1] - a[1]);
  const labels = sortedEntries.map(([label]) => label);
  const values = sortedEntries.map(([, value]) => value);
  const total = values.reduce((a, b) => a + b, 0);
  const palette = getPalette();
  const colors = labels.map(
    (label, idx) => labelColorMap[label] || palette[idx % palette.length],
  );

  const ctx = document.getElementById("category-chart").getContext("2d");

  if (categoryChart) categoryChart.destroy();

  const style = getComputedStyle(document.body);
  const gridColor = style.getPropertyValue("--border-color").trim();
  const textColor = style.getPropertyValue("--text-secondary").trim();

  categoryChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      cutout: "65%",
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: style.getPropertyValue("--bg-card").trim(),
          titleColor: textColor,
          bodyColor: textColor,
          borderColor: gridColor,
          borderWidth: 1,
          callbacks: {
            label: function(context) {
              const value = context.parsed;
              const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
              return `${context.label}: ${value.toFixed(2)} € (${percentage}%)`;
            }
          }
        }
      },
    },
  });

  const legendEl = document.getElementById("category-legend");
  legendEl.innerHTML = labels
    .map((label, i) => {
      const pct = total > 0 ? Math.round((values[i] / total) * 100) : 0;
      return `
        <div class="legend-item">
          <span class="legend-label"><span class="legend-color" style="background: ${colors[i]}"></span>${label}</span>
          <span class="legend-value">${pct}%</span>
        </div>
      `;
    })
    .join("");

  labels.forEach((label, i) => {
    if (!labelColorMap[label]) {
      labelColorMap[label] = colors[i];
    }
  });
}

async function loadReceipts() {
  try {
    const res = await fetch(`${API_URL}/receipts`);
    const receipts = await res.json();
    const tbody = document.getElementById("receipts-body");

    if (receipts.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="empty-state">Keine Belege vorhanden</td></tr>';
      return;
    }

    const recent = receipts.slice(0, 4);

    tbody.innerHTML = recent
      .map(
        (r) => `
          <tr>
            <td><span class="editable" onclick="editField(${r.id}, 'date', this)">${formatDate(r.date)}</span></td>
            <td class="store-name"><span class="editable" onclick="editField(${r.id}, 'store_name', this)">${r.store_name || "-"}</span></td>
            <td>${renderCategoryTags(r.id, r.labels)}</td>
            <td class="amount">${r.total ? r.total.toFixed(2) + " €" : "-"}</td>
          </tr>
        `,
      )
      .join("");
  } catch (e) {
    document.getElementById("receipts-body").innerHTML =
      '<tr><td colspan="4" class="empty-state">Fehler beim Laden</td></tr>';
  }
}

function renderCategoryTags(id, labels) {
  if (!labels || labels.length === 0) {
    return `<span class="category-tag none" onclick="editCategory(${id}, this, ${JSON.stringify([])})">+ Kategorie</span>`;
  }
  return (
    labels
      .map((l) => {
        const color = labelColorMap[l] || "#f5a623";
        return `<span class="category-tag" style="background: ${color}20; color: ${color}">${l} <button class="delete-tag-btn-stats" onclick="deleteLabelStats(${id}, '${l.replace(/'/g, "\\'")}', event)" title="Entfernen">×</button></span>`;
      })
      .join("") +
    `<span class="category-tag none" onclick="editCategory(${id}, this, ${JSON.stringify(labels)})" title="Labels hinzufügen (kommagetrennt)">+</span>`
  );
}

async function editCategory(id, el, existingLabels = []) {
  const input = document.createElement("input");
  input.className = "category-input";
  input.placeholder = "Labels (kommagetrennt)...";
  input.style.width = "150px";
  el.replaceWith(input);
  input.focus();

  let finished = false;

  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && input.value.trim()) {
      if (finished) return;
      finished = true;

      const scrollX = window.scrollX;
      const scrollY = window.scrollY;

      const newLabels = input.value
        .split(",")
        .map((l) => l.trim())
        .filter((l) => l);

      const allLabels = [...new Set([...existingLabels, ...newLabels])];

      try {
        await fetch(`${API_URL}/receipts/${id}/labels`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ labels: allLabels }),
        });
      } catch (err) {
        console.error(err);
      }

      await Promise.all([loadReceipts(), loadStats()]);
      restoreScrollLater(scrollX, scrollY);
    } else if (e.key === "Escape") {
      if (finished) return;
      finished = true;
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      await loadReceipts();
      restoreScrollLater(scrollX, scrollY);
    }
  });

  input.addEventListener("blur", async () => {
    if (finished) return;
    finished = true;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    await loadReceipts();
    restoreScrollLater(scrollX, scrollY);
  });
}

function editField(id, field, el) {
  const cell = el.closest("td") || el.parentElement;
  if (!cell || cell.querySelector("input.edit-input")) return;

  const currentValue = el.textContent.replace(" €", "").trim();
  const input = document.createElement("input");
  input.className = "edit-input";
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
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const payload = { [field]: input.value.trim() || null };
    try {
      await fetch(`${API_URL}/receipts/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.error(e);
    }
    cleanup();
    await Promise.all([loadReceipts(), loadStats()]);
    restoreScrollLater(scrollX, scrollY);
  };

  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") {
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      cleanup();
      await Promise.all([loadReceipts(), loadStats()]);
      restoreScrollLater(scrollX, scrollY);
    }
  });
  input.addEventListener("blur", save);
}

async function deleteLabelStats(id, label, event) {
  event.stopPropagation();
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;

  const receipts = await (await fetch(`${API_URL}/receipts`)).json();
  const receipt = receipts.find((r) => r.id === id);
  if (!receipt) return;

  const newLabels = (receipt.labels || []).filter((l) => l !== label);

  await fetch(`${API_URL}/receipts/${id}/labels`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labels: newLabels }),
  });

  await Promise.all([loadReceipts(), loadStats()]);
  restoreScrollLater(scrollX, scrollY);
}

async function renderCategoriesManager(categories) {
  const container = document.getElementById("categories-list");
  if (!container) return;
  if (!categories || categories.length === 0) {
    container.innerHTML = '<div class="empty-hint">Keine Kategorien vorhanden</div>';
    return;
  }
  const palette = getPalette();
  container.innerHTML = categories
    .map((cat, index) => {
      const color = cat.color || palette[index % palette.length];
      return `
        <div class="category-row" data-id="${cat.id}">
          <input type="color" class="category-color-input" value="${color}" />
          <input type="text" class="category-name-input" value="${escapeHtml(cat.name)}" />
          <span class="category-usage">${cat.usage_count || 0}</span>
          <div class="category-actions">
            <button class="btn-small save-category">Speichern</button>
            <button class="btn-small danger delete-category">Löschen</button>
          </div>
        </div>
      `;
    })
    .join("");

  container.querySelectorAll(".save-category").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".category-row");
      if (!row) return;
      const id = row.dataset.id;
      const name = row.querySelector(".category-name-input")?.value.trim();
      const color = row.querySelector(".category-color-input")?.value;
      if (!name) return;
      await fetch(`${API_URL}/categories/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, color }),
      });
      await refreshManagementData();
    });
  });

  container.querySelectorAll(".delete-category").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".category-row");
      if (!row) return;
      const id = row.dataset.id;
      if (!confirm("Kategorie wirklich löschen?")) return;
      await fetch(`${API_URL}/categories/${id}`, { method: "DELETE" });
      await refreshManagementData();
    });
  });
}

function renderRuleCategoryOptions(categories) {
  const select = document.getElementById("rule-category");
  if (!select) return;
  select.innerHTML = (categories || [])
    .map((cat) => `<option value="${cat.id}">${escapeHtml(cat.name)}</option>`)
    .join("");
}

async function loadRules() {
  try {
    const res = await fetch(`${API_URL}/category-rules`);
    const rules = await res.json();
    renderRules(rules);
  } catch (e) {
    const container = document.getElementById("rules-list");
    if (container) {
      container.innerHTML = '<div class="empty-hint">Keine Regeln gefunden</div>';
    }
  }
}

function buildRuleTypeOptions(selected) {
  const options = [
    { value: "store", label: "Geschäft" },
    { value: "keyword", label: "Keyword" },
    { value: "payment", label: "Zahlung" },
    { value: "item", label: "Artikel" },
  ];
  return options
    .map(
      (opt) =>
        `<option value="${opt.value}" ${opt.value === selected ? "selected" : ""}>${opt.label}</option>`,
    )
    .join("");
}

function buildMatchOptions(selected) {
  const options = [
    { value: "contains", label: "Enthält" },
    { value: "equals", label: "Gleich" },
    { value: "regex", label: "Regex" },
  ];
  return options
    .map(
      (opt) =>
        `<option value="${opt.value}" ${opt.value === selected ? "selected" : ""}>${opt.label}</option>`,
    )
    .join("");
}

function buildCategorySelect(selectedId) {
  return (categoriesCache || [])
    .map((cat) => {
      const selected = String(cat.id) === String(selectedId) ? "selected" : "";
      return `<option value="${cat.id}" ${selected}>${escapeHtml(cat.name)}</option>`;
    })
    .join("");
}

function renderRules(rules) {
  const container = document.getElementById("rules-list");
  if (!container) return;
  if (!rules || rules.length === 0) {
    container.innerHTML = '<div class="empty-hint">Keine Regeln vorhanden</div>';
    return;
  }
  container.innerHTML = rules
    .map(
      (rule) => `
        <div class="rule-row" data-id="${rule.id}">
          <select class="rule-select rule-category">${buildCategorySelect(rule.category_id)}</select>
          <select class="rule-select rule-type">${buildRuleTypeOptions(rule.rule_type)}</select>
          <select class="rule-select rule-match">${buildMatchOptions(rule.match_type)}</select>
          <input type="text" class="rule-input rule-pattern" value="${escapeHtml(rule.pattern)}" />
          <input type="number" class="rule-input rule-priority" value="${rule.priority ?? 100}" />
          <input type="checkbox" class="rule-active" ${rule.is_active ? "checked" : ""} />
          <div class="rule-actions">
            <button class="btn-small save-rule">Speichern</button>
            <button class="btn-small danger delete-rule">Löschen</button>
          </div>
        </div>
      `,
    )
    .join("");

  container.querySelectorAll(".save-rule").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".rule-row");
      if (!row) return;
      const id = row.dataset.id;
      const payload = {
        category_id: row.querySelector(".rule-category")?.value,
        rule_type: row.querySelector(".rule-type")?.value,
        match_type: row.querySelector(".rule-match")?.value,
        pattern: row.querySelector(".rule-pattern")?.value.trim(),
        priority: Number(row.querySelector(".rule-priority")?.value || 100),
        is_active: row.querySelector(".rule-active")?.checked || false,
      };
      await fetch(`${API_URL}/category-rules/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadRules();
    });
  });

  container.querySelectorAll(".delete-rule").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".rule-row");
      if (!row) return;
      const id = row.dataset.id;
      if (!confirm("Regel wirklich löschen?")) return;
      await fetch(`${API_URL}/category-rules/${id}`, { method: "DELETE" });
      await loadRules();
    });
  });
}

async function refreshManagementData() {
  await loadCategories();
  await loadRules();
  await Promise.all([loadReceipts(), loadStats()]);
}

function setupManagementHandlers() {
  const addCategoryBtn = document.getElementById("add-category-btn");
  if (addCategoryBtn) {
    addCategoryBtn.addEventListener("click", async () => {
      const nameInput = document.getElementById("new-category-name");
      const colorInput = document.getElementById("new-category-color");
      const name = nameInput?.value.trim();
      const color = colorInput?.value;
      if (!name) return;
      await fetch(`${API_URL}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, color }),
      });
      if (nameInput) nameInput.value = "";
      await refreshManagementData();
    });
  }

  const addRuleBtn = document.getElementById("add-rule-btn");
  if (addRuleBtn) {
    addRuleBtn.addEventListener("click", async () => {
      const categoryId = document.getElementById("rule-category")?.value;
      const ruleType = document.getElementById("rule-type")?.value;
      const matchType = document.getElementById("rule-match")?.value;
      const pattern = document.getElementById("rule-pattern")?.value.trim();
      const priorityRaw = document.getElementById("rule-priority")?.value;
      if (!categoryId || !ruleType || !pattern) return;
      await fetch(`${API_URL}/category-rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category_id: categoryId,
          rule_type: ruleType,
          match_type: matchType,
          pattern,
          priority: Number(priorityRaw || 100),
          is_active: true,
        }),
      });
      const patternInput = document.getElementById("rule-pattern");
      if (patternInput) patternInput.value = "";
      await loadRules();
    });
  }

  const exportJsonLink = document.getElementById("export-json-link");
  if (exportJsonLink) exportJsonLink.href = `${API_URL}/export/json`;
  const exportCsvLink = document.getElementById("export-csv-link");
  if (exportCsvLink) exportCsvLink.href = `${API_URL}/export/csv`;
  const exportDbLink = document.getElementById("export-db-link");
  if (exportDbLink) exportDbLink.href = `${API_URL}/export/db`;

  const importBtn = document.getElementById("import-backup-btn");
  if (importBtn) {
    importBtn.addEventListener("click", async () => {
      const fileInput = document.getElementById("backup-file");
      const status = document.getElementById("backup-status");
      const file = fileInput?.files?.[0];
      if (!file) {
        if (status) status.textContent = "Bitte JSON-Datei auswählen.";
        return;
      }
      if (status) status.textContent = "Import läuft...";
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = await fetch(`${API_URL}/import/json`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
          if (status) status.textContent = data.error || "Import fehlgeschlagen.";
          return;
        }
        if (status) {
          status.textContent = `Importiert: ${JSON.stringify(data.imported)}`;
        }
        await refreshManagementData();
      } catch (e) {
        if (status) status.textContent = "Import fehlgeschlagen.";
      }
    });
  }
}

async function initializeDashboard() {
  setupManagementHandlers();
  await loadCategories();
  await Promise.all([loadStats(), loadReceipts(), loadRules()]);
}

initializeDashboard();
