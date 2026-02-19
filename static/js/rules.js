let categoriesCache = [];

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
    renderRules(rules);
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

function renderRules(rules) {
  const container = document.getElementById("rules-rows");
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
          <input
            type="text"
            inputmode="numeric"
            class="rule-input rule-priority"
            value="${rule.priority ?? 100}"
          />
          <input type="checkbox" class="rule-active" ${rule.is_active ? "checked" : ""} />
          <div class="rule-actions">
            <button class="icon-btn save-rule" title="Speichern" aria-label="Regel speichern">
              <svg viewBox="0 0 24 24">
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </button>
            <button class="icon-btn danger delete-rule" title="Löschen" aria-label="Regel löschen">
              <svg viewBox="0 0 24 24">
                <path d="M3 6h18" />
                <path d="M8 6V4h8v2" />
                <path d="M6 6l1 14h10l1-14" />
              </svg>
            </button>
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

function setupHandlers() {
  const openBtn = document.getElementById("open-rule-modal");
  const modal = document.getElementById("rule-modal");
  const cancelBtn = document.getElementById("cancel-rule-btn");
  const addRuleBtn = document.getElementById("add-rule-btn");
  const patternInput = document.getElementById("rule-pattern");

  const closeModal = () => {
    modal?.classList.remove("show");
    if (patternInput) patternInput.value = "";
  };

  openBtn?.addEventListener("click", () => {
    modal?.classList.add("show");
    patternInput?.focus();
  });

  cancelBtn?.addEventListener("click", closeModal);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal?.classList.contains("show")) {
      closeModal();
    }
  });

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
    closeModal();
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
