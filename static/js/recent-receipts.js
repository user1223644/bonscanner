(() => {
  let labelColorMap = {};

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
    if (!dateStr || dateStr === "-") return "-";

    const raw = String(dateStr).trim();

    // Format: DD.MM.YYYY, DD/MM/YYYY, MM/DD/YYYY
    let match = raw.match(/^(\d{1,2})([./])(\d{1,2})\2(\d{4})$/);
    if (match) {
      const a = Number(match[1]);
      const sep = match[2];
      const b = Number(match[3]);
      const year = match[4];

      let day = a;
      let month = b;

      // If separated by "/" and the second part can't be a month, treat as US MM/DD/YYYY.
      if (sep === "/" && a <= 12 && b > 12) {
        day = b;
        month = a;
      }

      return `${String(day).padStart(2, "0")}.${String(month).padStart(2, "0")}.${year}`;
    }

    // Format: YYYY-MM-DD (ISO)
    match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) {
      const year = match[1];
      const month = match[2];
      const day = match[3];
      return `${day}.${month}.${year}`;
    }

    return raw;
  }

  function formatAmount(total) {
    const amount =
      typeof total === "number"
        ? total
        : typeof total === "string"
          ? Number.parseFloat(total.replace(",", "."))
          : Number.NaN;

    if (!Number.isFinite(amount)) return "-";
    return `${amount.toFixed(2)} €`;
  }

  async function loadLabelColorMap() {
    const palette =
      typeof CATEGORY_COLORS !== "undefined" &&
      Array.isArray(CATEGORY_COLORS) &&
      CATEGORY_COLORS.length > 0
        ? CATEGORY_COLORS
        : ["#f5a623", "#4ade80", "#60a5fa", "#f472b6", "#a78bfa"];

    try {
      const res = await fetch(`${API_URL}/stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const stats = await res.json();
      const categoryData = stats?.category_totals || {};

      const sorted = Object.entries(categoryData).sort((a, b) => b[1] - a[1]);
      labelColorMap = {};
      sorted.forEach(([label], i) => {
        labelColorMap[label] = palette[i % palette.length];
      });
    } catch (e) {
      labelColorMap = {};
    }
  }

  function renderCategory(labels) {
    const safeLabels = Array.isArray(labels) ? labels.filter(Boolean) : [];
    if (safeLabels.length === 0) {
      return '<span class="cell-muted">-</span>';
    }

    const firstLabel = String(safeLabels[0]);
    const first = escapeHtml(firstLabel);
    const restCount = safeLabels.length - 1;
    const more =
      restCount > 0 ? `<span class="category-more">+${restCount}</span>` : "";

    const color = labelColorMap[firstLabel] || "#f5a623";
    const title = escapeHtml(safeLabels.join(", "));
    const style = `background: ${color}20; color: ${color}; border: 1px solid ${color}40;`;

    return `<span title="${title}"><span class="category-chip" style="${style}">${first}</span>${more}</span>`;
  }

  async function refreshRecentReceipts() {
    const tbody = document.getElementById("recent-receipts-body");
    if (!tbody) return;

    tbody.innerHTML =
      '<tr><td colspan="4" class="recent-empty">Lade Belege...</td></tr>';

    try {
      await loadLabelColorMap();

      const res = await fetch(`${API_URL}/receipts`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const receipts = await res.json();
      const recent = Array.isArray(receipts) ? receipts.slice(0, 10) : [];

      if (recent.length === 0) {
        tbody.innerHTML =
          '<tr><td colspan="4" class="recent-empty">Noch keine Belege vorhanden</td></tr>';
        return;
      }

      tbody.innerHTML = recent
        .map((r) => {
          const date = escapeHtml(formatDate(r?.date));
          const store = escapeHtml(r?.store_name || "-");
          const category = renderCategory(r?.labels);
          const amountValue = formatAmount(r?.total);
          const amount =
            amountValue === "-"
              ? '<span class="cell-muted">-</span>'
              : escapeHtml(amountValue);

          return `
            <tr>
              <td>${date}</td>
              <td title="${store}">${store}</td>
              <td>${category}</td>
              <td class="recent-amount">${amount}</td>
            </tr>
          `;
        })
        .join("");
    } catch (e) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="recent-empty">Fehler beim Laden</td></tr>';
    }
  }

  window.refreshRecentReceipts = refreshRecentReceipts;
  document.addEventListener("DOMContentLoaded", refreshRecentReceipts);
})();
