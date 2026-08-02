(() => {
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let saved = null;
  try { saved = localStorage.getItem("opengpu-theme"); } catch {}

  const apply = theme => {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    const button = document.getElementById("theme-toggle");
    if (button) {
      const dark = theme === "dark";
      button.setAttribute("aria-label", dark ? "Use light mode" : "Use dark mode");
      button.setAttribute("title", dark ? "Use light mode" : "Use dark mode");
      button.setAttribute("aria-pressed", String(dark));
    }
  };

  apply(saved === "light" || saved === "dark" ? saved : media.matches ? "dark" : "light");
  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
      const theme = root.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem("opengpu-theme", theme); } catch {}
      apply(theme);
    });
  });
  media.addEventListener("change", event => {
    try { if (localStorage.getItem("opengpu-theme")) return; } catch {}
    apply(event.matches ? "dark" : "light");
  });
})();
