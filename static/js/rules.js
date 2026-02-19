let categoriesCache = [];
let rulesCache = [];

const ICONS = {
  save: `
    <svg viewBox="0 0 24 24">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  `,
  trash: `
    <svg viewBox="0 0 24 24">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M6 6l1 14h10l1-14" />
    </svg>
  `,
  check: `
    <svg viewBox="0 0 24 24">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  `,
};

const SPINNER = '<span class="spinner" aria-hidden="true"></span>';

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

function getToastContainer() {
  return document.getElementById("toast-container");
}

function showToast(message, options = {}) {
  const container = getToastContainer();
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast${options.tone === "error" ? " error" : ""}`;
  const text = document.createElement("span");
  text.textContent = message;
  toast.appendChild(text);

  let actionButton;
  if (options.actionLabel && typeof options.onAction === "function") {
    actionButton = document.createElement("button");
    actionButton.type = "button";
    actionButton.textContent = options.actionLabel;
    actionButton.addEventListener("click", () => {
      options.onAction();
      toast.remove();
    });
    toast.appendChild(actionButton);
  }

  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.add("show");
  });

  const timeout = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 200);
  }, options.duration || 4000);

  if (actionButton) {
    actionButton.addEventListener("click", () => clearTimeout(timeout));
  }
}

function setButtonLoading(button) {
  if (!button) return;
  button.classList.add("loading");
  button.disabled = true;
  button.innerHTML = SPINNER;
}

function restoreButton(button) {
  if (!button) return;
  const icon = button.dataset.icon;
  button.classList.remove("loading");
  button.disabled = false;
  button.innerHTML = ICONS[icon] || "";
}

function showButtonSuccess(button) {
  if (!button) return;
  button.classList.remove("loading");
  button.innerHTML = ICONS.check;
  setTimeout(() => restoreButton(button), 800);
}

function openRuleModal() {
  const modal = document.getElementById("rule-modal");
  modal?.classList.add("show");
  const input = document.getElementById("rule-pattern");
  input?.focus();
}

function closeRuleModal() {
  const modal = document.getElementById("rule-modal");
  modal?.classList.remove("show");
  const input = document.getElementById("rule-pattern");
  if (input) input.value = "";
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
    container.querySelector(".empty-cta")?.addEventListener("click", openRuleModal);
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
            >${ICONS.save}</button>
            <button
              class="icon-btn danger delete-rule"
              data-icon="trash"
              title="Löschen"
              aria-label="Regel löschen"
            >${ICONS.trash}</button>
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
      setButtonLoading(btn);

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
        showButtonSuccess(btn);
        row.classList.add("flash");
        row.addEventListener("animationend", () => row.classList.remove("flash"), {
          once: true,
        });
      } catch (error) {
        row.querySelector(".rule-category").value = previous.category_id;
        row.querySelector(".rule-type").value = previous.rule_type;
        row.querySelector(".rule-match").value = previous.match_type;
        row.querySelector(".rule-pattern").value = previous.pattern || "";
        row.querySelector(".rule-priority").value = previous.priority ?? 100;
        row.querySelector(".rule-active").checked = !!previous.is_active;
        restoreButton(btn);
        showToast(error.message || "Speichern fehlgeschlagen.", { tone: "error" });
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

      const height = row.offsetHeight;
      row.style.height = `${height}px`;
      row.classList.add("removing");
      requestAnimationFrame(() => {
        row.style.height = "0px";
        row.style.opacity = "0";
        row.style.marginTop = "0";
        row.style.marginBottom = "0";
        row.style.paddingTop = "0";
        row.style.paddingBottom = "0";
        row.style.borderWidth = "0";
      });

      const transitionDone = new Promise((resolve) => {
        const timer = setTimeout(resolve, 260);
        row.addEventListener(
          "transitionend",
          (event) => {
            if (event.propertyName === "height") {
              clearTimeout(timer);
              resolve();
            }
          },
          { once: true },
        );
      });

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
        showToast("Regel gelöscht", {
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
        row.classList.remove("removing");
        row.style.height = "";
        row.style.opacity = "";
        row.style.marginTop = "";
        row.style.marginBottom = "";
        row.style.paddingTop = "";
        row.style.paddingBottom = "";
        row.style.borderWidth = "";
        saveBtn?.removeAttribute("disabled");
        btn.removeAttribute("disabled");
        showToast(error.message || "Löschen fehlgeschlagen.", { tone: "error" });
      }
    });
  });
}

function setupHandlers() {
  const openBtn = document.getElementById("open-rule-modal");
  const modal = document.getElementById("rule-modal");
  const cancelBtn = document.getElementById("cancel-rule-btn");
  const addRuleBtn = document.getElementById("add-rule-btn");
  const patternInput = document.getElementById("rule-pattern");

  openBtn?.addEventListener("click", openRuleModal);

  cancelBtn?.addEventListener("click", closeRuleModal);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeRuleModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal?.classList.contains("show")) {
      closeRuleModal();
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
    closeRuleModal();
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
