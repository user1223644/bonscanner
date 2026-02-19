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

function getPalette() {
  return typeof CATEGORY_COLORS !== "undefined" && CATEGORY_COLORS.length
    ? CATEGORY_COLORS
    : ["#f5a623", "#4ade80", "#60a5fa", "#f472b6", "#a78bfa"];
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
            <button class="icon-btn save-category" title="Speichern" aria-label="Kategorie speichern">
              <svg viewBox="0 0 24 24">
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </button>
            <button class="icon-btn danger delete-category" title="Löschen" aria-label="Kategorie löschen">
              <svg viewBox="0 0 24 24">
                <path d="M3 6h18" />
                <path d="M8 6V4h8v2" />
                <path d="M6 6l1 14h10l1-14" />
              </svg>
            </button>
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
      await loadCategories();
    });
  });

  container.querySelectorAll(".delete-category").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".category-row");
      if (!row) return;
      const id = row.dataset.id;
      if (!confirm("Kategorie wirklich löschen?")) return;
      await fetch(`${API_URL}/categories/${id}`, { method: "DELETE" });
      await loadCategories();
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

  const closeModal = () => {
    modal?.classList.remove("show");
    if (nameInput) nameInput.value = "";
  };

  openBtn?.addEventListener("click", () => {
    modal?.classList.add("show");
    nameInput?.focus();
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

  const submitCategory = async () => {
    const name = nameInput?.value.trim();
    const color = colorInput?.value;
    if (!name) return;
    await fetch(`${API_URL}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, color }),
    });
    closeModal();
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
