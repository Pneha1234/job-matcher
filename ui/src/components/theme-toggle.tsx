"use client";

export const THEME_KEY = "jm-theme";

// Runs before paint (see layout.tsx) so a saved theme never flashes.
export const themeInitScript = `try{var t=localStorage.getItem("${THEME_KEY}");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem(THEME_KEY, root.dataset.theme);
    } catch {
      // Storage can be unavailable (private windows); the toggle still works for this visit.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="text-xs text-faint hover:text-foreground"
    >
      Toggle dark mode
    </button>
  );
}
