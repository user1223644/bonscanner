let selectedLabels = [];
let availableLabels = [];
let pendingFile = null;

const api = window.API;
const apiBase = api?.baseUrl || window.API_URL || "http://localhost:5000";
const ui = window.BonscannerUI;

const uploadArea = document.getElementById("upload-area");
const fileInput = document.getElementById("file-input");
const previewContainer = document.getElementById("preview-container");
const previewImg = document.getElementById("preview-img");
const imageModal = document.getElementById("image-modal");
const imageModalImg = document.getElementById("image-modal-img");
const imageModalClose = document.getElementById("image-modal-close");
const results = document.getElementById("results");
const labelSection = document.getElementById("label-section");
const labelInput = document.getElementById("label-input");
const selectedLabelsDiv = document.getElementById("selected-labels");
const suggestionsDiv = document.getElementById("label-suggestions");

let currentUploadReceiptId = null;
let uploadItemsCache = [];

function uploadReceiptWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";

    xhr.upload.addEventListener("progress", (event) => {
      if (!onProgress) return;
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      } else {
        onProgress(null);
      }
    });

    xhr.upload.addEventListener("loadend", () => {
      onProgress?.(1);
    });

    xhr.addEventListener("load", () => {
      let data = xhr.response;
      if (!data) {
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          data = null;
        }
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
        return;
      }

      const message =
        data?.error ||
        xhr.responseText ||
        `Request failed: ${xhr.status} ${xhr.statusText}`;
      reject(new Error(message));
    });

    xhr.addEventListener("error", () => reject(new Error("Netzwerkfehler")));
    xhr.addEventListener("abort", () => reject(new Error("Abgebrochen")));

    xhr.send(formData);
  });
}

async function loadLabels() {
  try {
    availableLabels = await api.get("/labels");
  } catch (e) {
    availableLabels = [];
  }
}

function renderSuggestions() {
  const unused = availableLabels
    .filter((l) => !selectedLabels.includes(l))
    .slice(0, 8);
  suggestionsDiv.innerHTML = unused
    .map(
      (l) =>
        `<button class="label-suggestion" onclick="addLabel('${l}')">${l}</button>`,
    )
    .join("");
}

function renderSelectedLabels() {
  selectedLabelsDiv.innerHTML = selectedLabels
    .map(
      (l) =>
        `<span class="label-tag">${l}<button onclick="removeLabel('${l}')">&times;</button></span>`,
    )
    .join("");
  renderSuggestions();
}

function addLabel(label) {
  if (label && !selectedLabels.includes(label)) {
    selectedLabels.push(label);
    renderSelectedLabels();
  }
  labelInput.value = "";
}

function removeLabel(label) {
  selectedLabels = selectedLabels.filter((l) => l !== label);
  renderSelectedLabels();
}

labelInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    addLabel(labelInput.value.trim());
  }
});

uploadArea.addEventListener("click", () => fileInput.click());
uploadArea.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadArea.classList.add("dragover");
});
uploadArea.addEventListener("dragleave", () =>
  uploadArea.classList.remove("dragover"),
);
uploadArea.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadArea.classList.remove("dragover");
  if (e.dataTransfer.files.length) showPreview(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) showPreview(e.target.files[0]);
});

function showPreview(file) {
  pendingFile = file;
  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src = e.target.result;
    previewContainer.classList.add("active");
    labelSection.classList.add("active");
    selectedLabels = [];
    renderSelectedLabels();
    renderSuggestions();
  };
  reader.readAsDataURL(file);
  setTimeout(() => {
    if (pendingFile === file) handleFile(file);
  }, 2000);
}

function openImageModal(src) {
  if (!imageModal || !imageModalImg || !src) return;
  imageModalImg.src = src;
  imageModal.classList.add("show");
  imageModal.setAttribute("aria-hidden", "false");
}

function closeImageModal() {
  if (!imageModal || !imageModalImg) return;
  imageModal.classList.remove("show");
  imageModal.setAttribute("aria-hidden", "true");
  imageModalImg.src = "";
}

previewImg?.addEventListener("click", () => {
  if (previewImg.src) openImageModal(previewImg.src);
});

imageModalClose?.addEventListener("click", closeImageModal);
imageModal?.addEventListener("click", (event) => {
  if (event.target === imageModal) closeImageModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && imageModal?.classList.contains("show")) {
    closeImageModal();
  }
});

async function handleFile(file) {
  results.classList.add("active");
  results.innerHTML =
    `
      <div class="loading">
        <div class="spinner"></div>
        <p class="loading-text" id="loading-text">Lade hoch...</p>
        <div
          class="progress indeterminate"
          id="upload-progress"
          role="progressbar"
          aria-label="Upload Fortschritt"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow="0"
        >
          <div class="progress-fill" id="upload-progress-fill"></div>
        </div>
      </div>
    `;

  const loadingText = document.getElementById("loading-text");
  const progressBar = document.getElementById("upload-progress");
  const progressFill = document.getElementById("upload-progress-fill");

  const setProgress = (ratio) => {
    if (!progressBar || !progressFill || !loadingText) return;

    if (ratio === null) {
      progressBar.classList.add("indeterminate");
      progressBar.setAttribute("aria-valuenow", "0");
      return;
    }

    progressBar.classList.remove("indeterminate");
    const percent = Math.max(0, Math.min(100, Math.round(ratio * 100)));
    progressFill.style.width = `${percent}%`;
    progressBar.setAttribute("aria-valuenow", String(percent));

    if (percent < 100) {
      loadingText.textContent = `Lade hoch... ${percent}%`;
    } else {
      loadingText.textContent = "Analysiere Beleg...";
    }
  };

  try {
    const formData = new FormData();
    formData.append("image", file);
    selectedLabels.forEach((l) => formData.append("labels", l));

    const data = await uploadReceiptWithProgress(
      `${apiBase}/scan`,
      formData,
      setProgress,
    );
    if (!data || typeof data !== "object") {
      throw new Error("Ungültige Serverantwort");
    }
    if (data.error) throw new Error(data.error);
    displayResults(data);
    window.refreshRecentReceipts?.();
  } catch (error) {
    results.innerHTML = `<div class="error">Fehler: ${error.message}</div>`;
  }
}

function displayResults(data) {
  const receiptId = data?.id;
  currentUploadReceiptId = receiptId || null;
  uploadItemsCache = Array.isArray(data.items) ? data.items : [];
  const formatTotal = (value) => {
    if (value === null || value === undefined || value === "") return "Nicht gefunden";
    const parsed = Number.parseFloat(String(value).replace(",", "."));
    if (!Number.isFinite(parsed)) return String(value);
    return `${parsed.toFixed(2)} €`;
  };

  const formatText = (value) => {
    if (value === null || value === undefined || value === "") return "Nicht gefunden";
    return String(value);
  };

  const buildEditableField = (label, field, value, formatter) => {
    const rawValue = value ?? "";
    const displayValue = formatter ? formatter(rawValue) : formatText(rawValue);
    const editableClass = receiptId ? "editable" : "";
    return `
      <div class="result-section" data-field-section="${field}">
        <h3>${label}</h3>
        <p class="result-value">
          <span class="result-field ${editableClass}" data-field="${field}" data-raw="${String(rawValue).replace(/"/g, "&quot;")}">${displayValue}</span>
        </p>
      </div>
    `;
  };

  let itemsHtml = "";
  if (receiptId) {
    itemsHtml = `
      <div class="result-section">
        <h3>Artikel</h3>
        <div id="upload-items">Lade Artikel...</div>
      </div>
    `;
  } else if (data.items?.length) {
    itemsHtml = `<div class="result-section"><h3>Artikel</h3><ul class="items-list">${data.items.map((i) => `<li><span>${i.name}</span><span class="item-price">${i.price}</span></li>`).join("")}</ul></div>`;
  }
  const taxesHtml = data.taxes?.length
    ? `<div class="result-section"><h3>Steuern</h3><ul class="items-list">${data.taxes.map((t) => `<li><span>${t.tax_rate || ""}%</span><span class="item-price">${t.tax_amount?.toFixed ? t.tax_amount.toFixed(2) : t.tax_amount} €</span></li>`).join("")}</ul></div>`
    : "";
  results.innerHTML = `
    <div class="success-toast" role="status" aria-live="polite">
      <div class="success-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>
      <div>
        <div class="success-title">Upload abgeschlossen</div>
        <div class="success-subtitle">Beleg wurde erfolgreich gespeichert.</div>
      </div>
    </div>
    ${buildEditableField("Geschäft", "store_name", data.store_name, formatText)}
    ${buildEditableField("Datum", "date", data.date, formatText)}
    ${buildEditableField("Gesamtsumme", "total", data.total, formatTotal)}
    ${itemsHtml}
    ${taxesHtml}
    <div class="result-section"><h3>OCR-Rohtext</h3><pre class="raw-text">${data.raw_text || "Kein Text erkannt"}</pre></div>
  `;

  if (receiptId) {
    bindResultEditors(receiptId);
    loadUploadItems(receiptId);
  }
}

loadLabels();

function showError(message) {
  if (ui?.showToast) {
    ui.showToast(message, { tone: "error" });
  } else {
    alert(message);
  }
}

function bindResultEditors(receiptId) {
  const fields = results.querySelectorAll(".result-field.editable");
  fields.forEach((field) => {
    field.addEventListener("click", () => startInlineEdit(field, receiptId));
  });
}

function startInlineEdit(span, receiptId) {
  if (!span || span.dataset.editing === "true") return;
  const field = span.dataset.field;
  const rawValue = span.dataset.raw || "";
  span.dataset.editing = "true";

  const input = document.createElement("input");
  input.className = "edit-input";
  input.type = "text";
  input.value = rawValue;

  span.replaceWith(input);
  input.focus();
  input.select();

  let didCleanup = false;
  let isSaving = false;

  const cleanup = (restoreValue) => {
    if (didCleanup) return;
    didCleanup = true;
    if (restoreValue !== undefined) {
      span.dataset.raw = restoreValue;
    }
    span.dataset.editing = "false";
    input.replaceWith(span);
  };

  const updateDisplay = (value) => {
    if (field === "total") {
      const parsed = Number.parseFloat(String(value).replace(",", "."));
      if (Number.isFinite(parsed)) {
        span.textContent = `${parsed.toFixed(2)} €`;
        return;
      }
    }
    span.textContent = value ? value : "Nicht gefunden";
  };

  const save = async () => {
    if (didCleanup || isSaving) return;
    isSaving = true;
    const newValue = input.value.trim();
    const previousText = span.textContent;
    const previousRaw = span.dataset.raw || "";
    span.dataset.raw = newValue;
    updateDisplay(newValue);
    cleanup();
    try {
      await api.patch(`/receipts/${receiptId}`, {
        [field]: newValue || null,
      });
    } catch (e) {
      span.dataset.raw = previousRaw;
      span.textContent = previousText;
      showError("Fehler beim Speichern");
    }
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") cleanup(span.dataset.raw || "");
  });
  input.addEventListener("blur", save);
}

function normalizeDecimal(value) {
  return String(value || "").replace(",", ".");
}

function formatItemPrice(item) {
  if (!item) return "-";
  const raw = item.line_total ?? item.price ?? "";
  const parsed = Number.parseFloat(normalizeDecimal(raw));
  if (!Number.isFinite(parsed)) return raw || "-";
  return `${parsed.toFixed(2)} €`;
}

function renderUploadItems(items) {
  const container = document.getElementById("upload-items");
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<span style="color: var(--text-muted);">Keine Artikel</span>';
    return;
  }
  container.innerHTML = `
    <ul class="items-list">
      ${items
        .map(
          (item) => `
            <li data-item-id="${item.id}">
              <span class="editable upload-item-field" data-field="name">${item.name || "-"}</span>
              <span class="item-price editable upload-item-field" data-field="line_total">${formatItemPrice(item)}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
  bindUploadItemEditors();
  updateTotalFromItems(items);
}

async function loadUploadItems(receiptId) {
  try {
    const items = await api.get(`/receipts/${receiptId}/items`);
    uploadItemsCache = items || [];
    renderUploadItems(uploadItemsCache);
  } catch (e) {
    const container = document.getElementById("upload-items");
    if (container) {
      container.innerHTML = '<span style="color: var(--text-muted);">Fehler beim Laden</span>';
    }
  }
}

function bindUploadItemEditors() {
  const fields = results.querySelectorAll(".upload-item-field");
  fields.forEach((field) => {
    field.addEventListener("click", () => startItemInlineEdit(field));
  });
}

function startItemInlineEdit(span) {
  if (!span || !currentUploadReceiptId) return;
  if (span.dataset.editing === "true") return;
  const itemRow = span.closest("li[data-item-id]");
  if (!itemRow) return;
  const itemId = itemRow.dataset.itemId;
  const field = span.dataset.field;
  const previousText = span.textContent;
  span.dataset.editing = "true";

  const input = document.createElement("input");
  input.className = "edit-input";
  input.type = "text";
  input.value =
    field === "line_total" ? previousText.replace("€", "").trim() : previousText;

  span.replaceWith(input);
  input.focus();
  input.select();

  let didCleanup = false;
  let isSaving = false;

  const cleanup = (restoreText) => {
    if (didCleanup) return;
    didCleanup = true;
    span.dataset.editing = "false";
    if (restoreText !== undefined) span.textContent = restoreText;
    input.replaceWith(span);
  };

  const save = async () => {
    if (didCleanup || isSaving) return;
    isSaving = true;
    const rawValue = input.value.trim();
    let payload = {};
    let nextText = rawValue || "-";

    if (field === "line_total") {
      const normalized = normalizeDecimal(rawValue);
      payload = { line_total: normalized || null };
      const parsed = Number.parseFloat(normalized);
      if (Number.isFinite(parsed)) {
        nextText = `${parsed.toFixed(2)} €`;
      }
    } else {
      payload = { name: rawValue || null };
    }

    span.textContent = nextText;
    cleanup();

    try {
      const response = await api.patch(
        `/receipts/${currentUploadReceiptId}/items/${itemId}`,
        payload,
      );
      if (response?.items) {
        uploadItemsCache = response.items;
        renderUploadItems(uploadItemsCache);
      }
    } catch (e) {
      span.textContent = previousText;
      showError("Fehler beim Speichern");
    }
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") cleanup(previousText);
  });
  input.addEventListener("blur", save);
}

function updateTotalFromItems(items) {
  if (!Array.isArray(items) || items.length === 0) return;
  const totalField = results.querySelector('.result-field[data-field="total"]');
  if (!totalField) return;
  const sum = items.reduce((acc, item) => {
    const raw = item.line_total ?? item.price ?? "";
    const value = Number.parseFloat(normalizeDecimal(raw));
    return Number.isFinite(value) ? acc + value : acc;
  }, 0);
  if (Number.isFinite(sum) && sum > 0) {
    totalField.textContent = `${sum.toFixed(2)} €`;
    totalField.dataset.raw = sum.toFixed(2);
  }
}
