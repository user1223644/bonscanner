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
  const addCategoryBtn = document.getElementById("add-category-btn");
  if (!addCategoryBtn) return;
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
    await loadCategories();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupHandlers();
  loadCategories();
});
