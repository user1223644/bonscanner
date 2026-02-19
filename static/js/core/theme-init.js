(() => {
  if (localStorage.getItem("theme") === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  }

  const applyShellClass = () => {
    if (document.body && document.querySelector(".sidebar")) {
      document.body.classList.add("app-shell");
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyShellClass);
  } else {
    applyShellClass();
  }
})();
