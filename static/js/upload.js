let selectedLabels = [];
let availableLabels = [];
let pendingFile = null;

const uploadArea = document.getElementById("upload-area");
const fileInput = document.getElementById("file-input");
const previewContainer = document.getElementById("preview-container");
const previewImg = document.getElementById("preview-img");
const results = document.getElementById("results");
const labelSection = document.getElementById("label-section");
const labelInput = document.getElementById("label-input");
const selectedLabelsDiv = document.getElementById("selected-labels");
const suggestionsDiv = document.getElementById("label-suggestions");

async function loadLabels() {
  try {
    const res = await fetch(`${API_URL}/labels`);
    availableLabels = await res.json();
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

async function handleFile(file) {
  results.classList.add("active");
  results.innerHTML =
    '<div class="loading"><div class="spinner"></div><p class="loading-text">Analysiere Beleg...</p></div>';

  try {
    const formData = new FormData();
    formData.append("image", file);
    selectedLabels.forEach((l) => formData.append("labels", l));

    const response = await fetch(`${API_URL}/scan`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    displayResults(data);
  } catch (error) {
    results.innerHTML = `<div class="error">Fehler: ${error.message}</div>`;
  }
}

function displayResults(data) {
  const itemsHtml = data.items?.length
    ? `<div class="result-section"><h3>Artikel</h3><ul class="items-list">${data.items.map((i) => `<li><span>${i.name}</span><span class="item-price">${i.price}</span></li>`).join("")}</ul></div>`
    : "";
  results.innerHTML = `
    <div class="result-section"><h3>Geschäft</h3><p class="result-value">${data.store_name || "Nicht gefunden"}</p></div>
    <div class="result-section"><h3>Datum</h3><p class="result-value">${data.date || "Nicht gefunden"}</p></div>
    <div class="result-section"><h3>Gesamtsumme</h3><p class="result-value">${data.total || "Nicht gefunden"}</p></div>
    ${itemsHtml}
    <div class="result-section"><h3>OCR-Rohtext</h3><pre class="raw-text">${data.raw_text || "Kein Text erkannt"}</pre></div>
  `;
}

loadLabels();
