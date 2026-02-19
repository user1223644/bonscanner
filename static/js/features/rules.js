let categoriesCache = [];
let rulesCache = [];
let modalController = null;

const ui = window.BonscannerUI;

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

async function loadCategories() {
  try {
    const res = await fetch(`${API_URL}/categories`);
    categoriesCache = await res.json();
  } catch (e) {
    categoriesCache = [];
  }
  renderRuleCategoryOptions(categoriesCache);
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
    rulesCache = rules || [];
    renderRules(rulesCache);
  } catch (e) {
    const container = document.getElementById("rules-rows");
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

function getRuleById(id) {
  return (rulesCache || []).find((rule) => String(rule.id) === String(id));
}

function updateRuleCache(id, updates) {
  rulesCache = (rulesCache || []).map((rule) =>
    String(rule.id) === String(id) ? { ...rule, ...updates } : rule,
  );
}

function ensureUI() {
  return ui || window.BonscannerUI;
}

function renderRules(rules) {
  const container = document.getElementById("rules-rows");
  if (!container) return;
  if (!rules || rules.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <strong>Noch keine Regeln</strong>
        <span>Erstelle eine Regel über den Plus-Button.</span>
        <button class="btn-small btn-primary empty-cta">Regel anlegen</button>
      </div>
    `;
    container.querySelector(".empty-cta")?.addEventListener("click", () => {
      modalController?.open?.();
    });
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
          <input
            type="text"
            inputmode="numeric"
            class="rule-input rule-priority"
            value="${rule.priority ?? 100}"
          />
          <input type="checkbox" class="rule-active" ${rule.is_active ? "checked" : ""} />
          <div class="rule-actions">
            <button
              class="icon-btn save-rule"
              data-icon="save"
              title="Speichern"
              aria-label="Regel speichern"
            >${ensureUI()?.icons?.save || ""}</button>
            <button
              class="icon-btn danger delete-rule"
              data-icon="trash"
              title="Löschen"
              aria-label="Regel löschen"
            >${ensureUI()?.icons?.trash || ""}</button>
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
      const previous = getRuleById(id);
      if (!previous) return;
      const payload = {
        category_id: row.querySelector(".rule-category")?.value,
        rule_type: row.querySelector(".rule-type")?.value,
        match_type: row.querySelector(".rule-match")?.value,
        pattern: row.querySelector(".rule-pattern")?.value.trim(),
        priority: Number(row.querySelector(".rule-priority")?.value || 100),
        is_active: row.querySelector(".rule-active")?.checked || false,
      };

      const deleteBtn = row.querySelector(".delete-rule");
      btn.disabled = true;
      deleteBtn?.setAttribute("disabled", "true");
      ensureUI()?.setButtonLoading(btn);

      try {
        const res = await fetch(`${API_URL}/category-rules/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || "Speichern fehlgeschlagen.");
        }
        updateRuleCache(id, payload);
        ensureUI()?.showButtonSuccess(btn);
        ensureUI()?.flashRow(row);
      } catch (error) {
        row.querySelector(".rule-category").value = previous.category_id;
        row.querySelector(".rule-type").value = previous.rule_type;
        row.querySelector(".rule-match").value = previous.match_type;
        row.querySelector(".rule-pattern").value = previous.pattern || "";
        row.querySelector(".rule-priority").value = previous.priority ?? 100;
        row.querySelector(".rule-active").checked = !!previous.is_active;
        ensureUI()?.restoreButton(btn);
        ensureUI()?.showToast(error.message || "Speichern fehlgeschlagen.", {
          tone: "error",
        });
      } finally {
        btn.disabled = false;
        deleteBtn?.removeAttribute("disabled");
      }
    });
  });

  container.querySelectorAll(".delete-rule").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".rule-row");
      if (!row) return;
      const id = row.dataset.id;
      const rule = getRuleById(id);
      if (!rule) return;

      const saveBtn = row.querySelector(".save-rule");
      saveBtn?.setAttribute("disabled", "true");
      btn.setAttribute("disabled", "true");

      const uiHelpers = ensureUI();
      const transitionDone = uiHelpers?.animateRowRemoval(row);

      try {
        const res = await fetch(`${API_URL}/category-rules/${id}`, { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || "Löschen fehlgeschlagen.");
        }
        rulesCache = rulesCache.filter((item) => String(item.id) !== String(id));
        await transitionDone;
        row.remove();
        if (rulesCache.length === 0) {
          renderRules(rulesCache);
        }
        uiHelpers?.showToast("Regel gelöscht", {
          actionLabel: "Rückgängig",
          onAction: async () => {
            await fetch(`${API_URL}/category-rules`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                category_id: rule.category_id,
                rule_type: rule.rule_type,
                match_type: rule.match_type,
                pattern: rule.pattern,
                priority: rule.priority,
                is_active: rule.is_active,
              }),
            });
            await loadRules();
          },
        });
      } catch (error) {
        uiHelpers?.resetRowStyles(row);
        saveBtn?.removeAttribute("disabled");
        btn.removeAttribute("disabled");
        uiHelpers?.showToast(error.message || "Löschen fehlgeschlagen.", {
          tone: "error",
        });
      }
    });
  });
}

function setupHandlers() {
  const uiHelpers = ensureUI();
  const openBtn = document.getElementById("open-rule-modal");
  const modal = document.getElementById("rule-modal");
  const cancelBtn = document.getElementById("cancel-rule-btn");
  const addRuleBtn = document.getElementById("add-rule-btn");
  const patternInput = document.getElementById("rule-pattern");

  modalController = uiHelpers?.bindModal({
    openButton: openBtn,
    modal,
    onClose: () => {
      if (patternInput) patternInput.value = "";
    },
    focusTarget: patternInput,
  });

  cancelBtn?.addEventListener("click", () => modalController?.close());

  const submitRule = async () => {
    const categoryId = document.getElementById("rule-category")?.value;
    const ruleType = document.getElementById("rule-type")?.value;
    const matchType = document.getElementById("rule-match")?.value;
    const pattern = document.getElementById("rule-pattern")?.value.trim();
    const priorityRaw = document.getElementById("rule-priority")?.value;
    const active = document.getElementById("rule-active")?.checked ?? true;
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
        is_active: active,
      }),
    });
    modalController?.close();
    await loadRules();
  };

  addRuleBtn?.addEventListener("click", submitRule);
  patternInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      submitRule();
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  setupHandlers();
  await loadCategories();
  await loadRules();
});
