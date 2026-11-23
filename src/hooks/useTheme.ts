import { useCallback, useEffect, useState } from "react";

export type ThemeMode = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export function themeStorageKey(slug: string): string {
  return `${slug.toLowerCase()}.theme`;
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === "system" || value === "light" || value === "dark";
}

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === "light" || mode === "dark") return mode;
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "dark";
}

export function applyThemeToDocument(mode: ThemeMode): ResolvedTheme {
  const resolved = resolveTheme(mode);
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.setAttribute("data-theme", resolved);
    root.style.colorScheme = resolved;
    root.style.backgroundColor = resolved === "dark" ? "#111318" : "#f5f6f8";
  }
  return resolved;
}

export interface UseThemeResult {
  theme: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setTheme: (mode: ThemeMode) => void;
}

/**
 * Quản lý theme Sáng / Tối / Theo hệ thống dùng chung key localStorage `<slug>.theme`.
 * Đồng bộ ngay với `data-theme` trên `:root` và lắng nghe thay đổi của Windows khi chọn "system".
 */
export function useTheme(slug: string, defaultMode: ThemeMode = "system"): UseThemeResult {
  const storageKey = themeStorageKey(slug);

  const [theme, setThemeState] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (isThemeMode(saved)) return saved;
    } catch {
      // ignore storage errors
    }
    return defaultMode;
  });

  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => resolveTheme(theme));

  useEffect(() => {
    setResolvedTheme(applyThemeToDocument(theme));
    try {
      localStorage.setItem(storageKey, theme);
    } catch {
      // ignore storage errors
    }

    if (theme !== "system" || typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolvedTheme(applyThemeToDocument("system"));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [storageKey, theme]);

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode);
  }, []);

  return { theme, resolvedTheme, setTheme };
}
