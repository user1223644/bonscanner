(() => {
  let labelColorMap = {};
  const dom = window.DomUtils;
  const api = window.API;

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
      const categories = await api.get("/categories");
      labelColorMap = {};
      categories.forEach((cat, i) => {
        labelColorMap[cat.name] = cat.color || palette[i % palette.length];
      });
    } catch (e) {
      labelColorMap = {};
    }
  }

  function renderCategories(receiptId, labels) {
    const safeLabels = Array.isArray(labels) ? labels.filter(Boolean) : [];
    const tags = safeLabels
      .map((label) => {
        const color = labelColorMap[label] || "#f5a623";
        const safeLabel = dom?.escapeHtml(label) || "";
        const labelParam = String(label)
          .replace(/\\/g, "\\\\")
          .replace(/'/g, "\\'");
        return `<span class="category-tag" style="background: ${color}20; color: ${color}">${safeLabel} <button class="delete-tag-btn" onclick="deleteLabel(${receiptId}, '${labelParam}', event)" title="Entfernen">×</button></span>`;
      })
      .join("");

    const addButton = `<span class="add-category" onclick="addCategory(${receiptId}, this)" title="Labels hinzufügen (kommagetrennt)">+</span>`;
    return tags + addButton;
  }

  function editField(receiptId, field, el) {
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

      const rawValue = input.value.trim();
      const payload = { [field]: rawValue || null };
      let ok = true;
      try {
        const res = await fetch(`${API_URL}/receipts/${receiptId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        ok = res.ok;
      } catch (e) {
        ok = false;
        console.error(e);
      }

      if (ok) {
        let displayValue = rawValue || "-";
        if (field === "date" && rawValue) displayValue = formatDate(rawValue);

        el.textContent = displayValue;
        if (field === "store_name") cell.title = displayValue;
      }

      cleanup();
      if (!ok) refreshRecentReceipts();
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") save();
      if (e.key === "Escape") {
        cleanup();
        refreshRecentReceipts();
      }
    });
    input.addEventListener("blur", save);
  }

  function addCategory(receiptId, el) {
    const row = document.querySelector(`tr[data-id="${receiptId}"]`);
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

        await fetch(`${API_URL}/receipts/${receiptId}/labels`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ labels: allLabels }),
        });
      }
      refreshRecentReceipts();
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") save();
      if (e.key === "Escape") {
        finished = true;
        refreshRecentReceipts();
      }
    });
    input.addEventListener("blur", save);
  }

  async function deleteLabel(receiptId, label, event) {
    event.stopPropagation();
    const row = document.querySelector(`tr[data-id="${receiptId}"]`);
    const labelsData = row ? JSON.parse(row.dataset.labels || "[]") : [];

    const newLabels = labelsData.filter((l) => l !== label);

    await fetch(`${API_URL}/receipts/${receiptId}/labels`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels: newLabels }),
    });

    refreshRecentReceipts();
  }

  async function refreshRecentReceipts() {
    const tbody = document.getElementById("recent-receipts-body");
    if (!tbody) return;

    const hasRows = Boolean(tbody.querySelector("tr[data-id]"));
    if (!hasRows) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="recent-empty">Lade Belege...</td></tr>';
    } else {
      tbody.classList.add("is-refreshing");
    }

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
          const receiptId = r?.id;
          const labelsJson = escapeHtml(JSON.stringify(r?.labels || []));

          const dateText = escapeHtml(formatDate(r?.date));
          const storeText = escapeHtml(r?.store_name || "-");
          const categoriesHtml = renderCategories(receiptId, r?.labels);

          const amountValue = formatAmount(r?.total);
          const amount = escapeHtml(amountValue);

          return `
            <tr data-id="${receiptId}" data-labels="${labelsJson}">
              <td><span class="editable" onclick="editField(${receiptId}, 'date', this)">${dateText}</span></td>
              <td title="${storeText}"><span class="editable" onclick="editField(${receiptId}, 'store_name', this)">${storeText}</span></td>
              <td>${categoriesHtml}</td>
              <td class="recent-amount">${amount}</td>
            </tr>
          `;
        })
        .join("");
    } catch (e) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="recent-empty">Fehler beim Laden</td></tr>';
    } finally {
      tbody.classList.remove("is-refreshing");
    }
  }

  window.refreshRecentReceipts = refreshRecentReceipts;
  window.editField = editField;
  window.addCategory = addCategory;
  window.deleteLabel = deleteLabel;
  document.addEventListener("DOMContentLoaded", refreshRecentReceipts);
})();
