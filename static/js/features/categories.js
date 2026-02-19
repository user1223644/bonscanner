let categoriesCache = [];
let modalController = null;

const ui = window.BonscannerUI;
const api = window.API;
const dom = window.DomUtils;

function escapeText(value) {
  if (dom?.escapeHtml) {
    return dom.escapeHtml(value);
  }
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

function ensureUI() {
  return ui || window.BonscannerUI;
}

async function loadCategories() {
  const container = document.getElementById("categories-list");
  if (!api) {
    if (container) {
      container.innerHTML = '<div class="empty-state">Fehler beim Laden</div>';
    }
    return;
  }
  try {
    categoriesCache = await api.get("/categories");
    renderCategories(categoriesCache);
  } catch (e) {
    categoriesCache = [];
    if (container) {
      container.innerHTML = '<div class="empty-state">Fehler beim Laden</div>';
    }
  }
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
    container.querySelector(".empty-cta")?.addEventListener("click", () => {
      modalController?.open?.();
    });
    return;
  }
  const palette = getPalette();
  container.innerHTML = categories
    .map((cat, index) => {
      const color = cat.color || palette[index % palette.length];
      const uiHelpers = ensureUI();
      return `
        <div class="category-row" data-id="${cat.id}">
          <input type="color" class="category-color-input" value="${color}" />
          <input type="text" class="category-name-input" value="${escapeText(cat.name)}" />
          <span class="category-usage">${cat.usage_count || 0}</span>
          <div class="category-actions">
            <button
              class="icon-btn save-category"
              data-icon="save"
              title="Speichern"
              aria-label="Kategorie speichern"
            >${uiHelpers?.icons?.save || ""}</button>
            <button
              class="icon-btn danger delete-category"
              data-icon="trash"
              title="Löschen"
              aria-label="Kategorie löschen"
            >${uiHelpers?.icons?.trash || ""}</button>
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
      ensureUI()?.setButtonLoading(btn);

      try {
        await api.patch(`/categories/${id}`, { name, color });
        updateCategoryCache(id, { name, color });
        ensureUI()?.showButtonSuccess(btn);
        ensureUI()?.flashRow(row);
      } catch (error) {
        if (nameInput) nameInput.value = previous.name || "";
        if (colorInput) colorInput.value = previous.color || colorInput?.value;
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

      const uiHelpers = ensureUI();
      const transitionDone = uiHelpers?.animateRowRemoval(row);

      try {
        await api.delete(`/categories/${id}`);
        categoriesCache = categoriesCache.filter((cat) => String(cat.id) !== String(id));
        await transitionDone;
        row.remove();
        if (categoriesCache.length === 0) {
          renderCategories(categoriesCache);
        }
        uiHelpers?.showToast("Kategorie gelöscht", {
          actionLabel: "Rückgängig",
          onAction: async () => {
            await api.post("/categories", {
              name: category.name,
              color: category.color,
            });
            await loadCategories();
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
  const openBtn = document.getElementById("open-category-modal");
  const modal = document.getElementById("category-modal");
  const cancelBtn = document.getElementById("cancel-category-btn");
  const createBtn = document.getElementById("create-category-btn");
  const nameInput = document.getElementById("new-category-name");
  const colorInput = document.getElementById("new-category-color");

  modalController = uiHelpers?.bindModal({
    openButton: openBtn,
    modal,
    onClose: () => {
      if (nameInput) nameInput.value = "";
    },
    focusTarget: nameInput,
  });

  cancelBtn?.addEventListener("click", () => modalController?.close());

  const submitCategory = async () => {
    const name = nameInput?.value.trim();
    const color = colorInput?.value;
    if (!name) return;
    await api.post("/categories", { name, color });
    modalController?.close();
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
