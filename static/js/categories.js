let categoriesCache = [];

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

function getPalette() {
  return typeof CATEGORY_COLORS !== "undefined" && CATEGORY_COLORS.length
    ? CATEGORY_COLORS
    : ["#f5a623", "#4ade80", "#60a5fa", "#f472b6", "#a78bfa"];
}

function getCategoryById(id) {
  return (categoriesCache || []).find((cat) => String(cat.id) === String(id));
}

function updateCategoryCache(id, updates) {
  categoriesCache = (categoriesCache || []).map((cat) =>
    String(cat.id) === String(id) ? { ...cat, ...updates } : cat,
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

function openCategoryModal() {
  const modal = document.getElementById("category-modal");
  modal?.classList.add("show");
  const input = document.getElementById("new-category-name");
  input?.focus();
}

function closeCategoryModal() {
  const modal = document.getElementById("category-modal");
  modal?.classList.remove("show");
  const input = document.getElementById("new-category-name");
  if (input) input.value = "";
}

async function loadCategories() {
  try {
    const res = await fetch(`${API_URL}/categories`);
    categoriesCache = await res.json();
  } catch (e) {
    categoriesCache = [];
  }
  renderCategories(categoriesCache);
}

function renderCategories(categories) {
  const container = document.getElementById("categories-list");
  if (!container) return;
  if (!categories || categories.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <strong>Noch keine Kategorien</strong>
        <span>Erstelle deine erste Kategorie über den Plus-Button.</span>
        <button class="btn-small btn-primary empty-cta">Kategorie anlegen</button>
      </div>
    `;
    container.querySelector(".empty-cta")?.addEventListener("click", openCategoryModal);
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
            <button
              class="icon-btn save-category"
              data-icon="save"
              title="Speichern"
              aria-label="Kategorie speichern"
            >${ICONS.save}</button>
            <button
              class="icon-btn danger delete-category"
              data-icon="trash"
              title="Löschen"
              aria-label="Kategorie löschen"
            >${ICONS.trash}</button>
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
      const nameInput = row.querySelector(".category-name-input");
      const colorInput = row.querySelector(".category-color-input");
      const name = nameInput?.value.trim();
      const color = colorInput?.value;
      const previous = getCategoryById(id);
      if (!name || !previous) return;

      const deleteBtn = row.querySelector(".delete-category");
      btn.disabled = true;
      deleteBtn?.setAttribute("disabled", "true");
      setButtonLoading(btn);

      try {
        const res = await fetch(`${API_URL}/categories/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, color }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || "Speichern fehlgeschlagen.");
        }
        updateCategoryCache(id, { name, color });
        showButtonSuccess(btn);
        row.classList.add("flash");
        row.addEventListener("animationend", () => row.classList.remove("flash"), {
          once: true,
        });
      } catch (error) {
        if (nameInput) nameInput.value = previous.name || "";
        if (colorInput) colorInput.value = previous.color || colorInput?.value;
        restoreButton(btn);
        showToast(error.message || "Speichern fehlgeschlagen.", { tone: "error" });
      } finally {
        btn.disabled = false;
        deleteBtn?.removeAttribute("disabled");
      }
    });
  });

  container.querySelectorAll(".delete-category").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".category-row");
      if (!row) return;
      const id = row.dataset.id;
      const category = getCategoryById(id);
      if (!category) return;

      const saveBtn = row.querySelector(".save-category");
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
        const res = await fetch(`${API_URL}/categories/${id}`, { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || "Löschen fehlgeschlagen.");
        }
        categoriesCache = categoriesCache.filter((cat) => String(cat.id) !== String(id));
        await transitionDone;
        row.remove();
        if (categoriesCache.length === 0) {
          renderCategories(categoriesCache);
        }
        showToast("Kategorie gelöscht", {
          actionLabel: "Rückgängig",
          onAction: async () => {
            await fetch(`${API_URL}/categories`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: category.name, color: category.color }),
            });
            await loadCategories();
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
  const openBtn = document.getElementById("open-category-modal");
  const modal = document.getElementById("category-modal");
  const cancelBtn = document.getElementById("cancel-category-btn");
  const createBtn = document.getElementById("create-category-btn");
  const nameInput = document.getElementById("new-category-name");
  const colorInput = document.getElementById("new-category-color");

  openBtn?.addEventListener("click", openCategoryModal);

  cancelBtn?.addEventListener("click", closeCategoryModal);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeCategoryModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal?.classList.contains("show")) {
      closeCategoryModal();
    }
  });

  const submitCategory = async () => {
    const name = nameInput?.value.trim();
    const color = colorInput?.value;
    if (!name) return;
    await fetch(`${API_URL}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, color }),
    });
    closeCategoryModal();
    await loadCategories();
  };

  createBtn?.addEventListener("click", submitCategory);
  nameInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      submitCategory();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupHandlers();
  loadCategories();
});
