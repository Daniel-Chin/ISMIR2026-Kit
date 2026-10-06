(function () {
  const KEY = "ismirColorTheme";
  const root = document.documentElement;

  function getStoredTheme() {
    try {
      const stored = localStorage.getItem(KEY);
      return stored === "dark" ? "dark" : "light";
    } catch (error) {
      return root.dataset.theme === "dark" ? "dark" : "light";
    }
  }

  function setTheme(theme) {
    const next = theme === "light" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch (error) {
      // localStorage can be unavailable in restricted embedded contexts.
    }
    updateButtons(next);
  }

  function updateButtons(theme) {
    document.querySelectorAll("#theme-toggle, [data-theme-toggle]").forEach((button) => {
      button.textContent = theme === "light" ? "🌙 Lights Off" : "☀️ Lights On";
      button.setAttribute("aria-pressed", String(theme === "light"));
      button.title = theme === "light" ? "Switch lights off" : "Switch lights on";
    });
  }

  setTheme(getStoredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    updateButtons(root.dataset.theme || getStoredTheme());
    document.querySelectorAll("#theme-toggle, [data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        setTheme(root.dataset.theme === "light" ? "dark" : "light");
      });
    });
  });
})();
