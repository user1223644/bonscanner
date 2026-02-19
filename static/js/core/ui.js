(function attachUIHelpers() {
  if (window.BonscannerUI) return;

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

  function flashRow(row) {
    if (!row) return;
    row.classList.add("flash");
    row.addEventListener(
      "animationend",
      () => row.classList.remove("flash"),
      { once: true },
    );
  }

  function animateRowRemoval(row) {
    if (!row) return Promise.resolve();
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

    return new Promise((resolve) => {
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
  }

  function resetRowStyles(row) {
    if (!row) return;
    row.classList.remove("removing");
    row.style.height = "";
    row.style.opacity = "";
    row.style.marginTop = "";
    row.style.marginBottom = "";
    row.style.paddingTop = "";
    row.style.paddingBottom = "";
    row.style.borderWidth = "";
  }

  function bindModal({ openButton, modal, onOpen, onClose, focusTarget }) {
    if (!modal) return { open: () => {}, close: () => {} };

    const open = () => {
      modal.classList.add("show");
      if (typeof onOpen === "function") onOpen();
      if (focusTarget) focusTarget.focus();
    };

    const close = () => {
      modal.classList.remove("show");
      if (typeof onClose === "function") onClose();
    };

    openButton?.addEventListener("click", open);

    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        close();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && modal.classList.contains("show")) {
        close();
      }
    });

    return { open, close };
  }

  window.BonscannerUI = {
    icons: ICONS,
    showToast,
    setButtonLoading,
    restoreButton,
    showButtonSuccess,
    flashRow,
    animateRowRemoval,
    resetRowStyles,
    bindModal,
  };
})();
