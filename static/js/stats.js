let spendingChart = null;
let categoryChart = null;
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
          backgroundColor: CATEGORY_COLORS.slice(0, labels.length),
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
          <span class="legend-label"><span class="legend-color" style="background: ${CATEGORY_COLORS[i]}"></span>${label}</span>
          <span class="legend-value">${pct}%</span>
        </div>
      `;
    })
    .join("");

  labelColorMap = {};
  labels.forEach((label, i) => {
    labelColorMap[label] = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
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

  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && input.value.trim()) {
      const newLabels = input.value
        .split(",")
        .map((l) => l.trim())
        .filter((l) => l);

      const allLabels = [...new Set([...existingLabels, ...newLabels])];

      const res = await fetch(`${API_URL}/receipts/${id}/labels`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labels: allLabels }),
      });
      if (res.ok) {
        loadReceipts();
        loadStats();
      }
    } else if (e.key === "Escape") {
      loadReceipts();
    }
  });

  input.addEventListener("blur", () => loadReceipts());
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
    loadStats();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") {
      loadReceipts();
      loadStats();
    }
  });
  input.addEventListener("blur", save);
}

async function deleteLabelStats(id, label, event) {
  event.stopPropagation();
  const receipts = await (await fetch(`${API_URL}/receipts`)).json();
  const receipt = receipts.find((r) => r.id === id);
  if (!receipt) return;

  const newLabels = (receipt.labels || []).filter((l) => l !== label);

  await fetch(`${API_URL}/receipts/${id}/labels`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labels: newLabels }),
  });

  loadReceipts();
  loadStats();
}

loadStats().then(() => loadReceipts());
