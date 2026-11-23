import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export type UpdaterStatus =
  | "idle"
  | "checking"
  | "up-to-date"
  | "available"
  | "downloading"
  | "verifying"
  | "ready"
  | "installing"
  | "error";

export interface UpdateInfo {
  version: string;
  pubDate: string;
  notes: string[];
  kind: "portable" | "installer" | string;
  filename: string;
  size: number;
  sha256: string;
}

export interface UpdaterState {
  status: UpdaterStatus;
  currentVersion: string;
  detectedKind: "portable" | "installer" | string;
  autoUpdate: boolean;
  lastCheckedAt: string | null;
  available: UpdateInfo | null;
  downloadedBytes: number;
  totalBytes: number;
  speedBps: number;
  installOnExit: boolean;
  error: string | null;
  manifestUrl: string;
}

export interface UseUpdaterResult {
  state: UpdaterState | null;
  percent: number;
  bannerDismissed: boolean;
  dismissBanner: () => void;
  checkForUpdates: (autoDownload?: boolean) => Promise<UpdaterState | null>;
  downloadUpdate: () => Promise<UpdaterState | null>;
  cancelDownload: () => Promise<UpdaterState | null>;
  installNow: (relaunch?: boolean) => Promise<void>;
  setAutoUpdate: (enabled: boolean) => Promise<UpdaterState | null>;
  setInstallOnExit: (enabled: boolean) => Promise<UpdaterState | null>;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  const fixed = v >= 100 ? 0 : v >= 10 ? 1 : 2;
  return `${v.toFixed(fixed)} ${units[i]}`;
}

export function useUpdater(): UseUpdaterResult {
  const [state, setState] = useState<UpdaterState | null>(null);
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    invoke<UpdaterState>("updater_get_state")
      .then((s) => {
        if (active) setState(s);
      })
      .catch(() => {});

    const unlistenPromise = listen<UpdaterState>("updater-state", (e) => {
      if (!active) return;
      setState(e.payload);
      // Re-show banner if download completes or user triggers a fresh check/download.
      if (e.payload.status === "ready" || e.payload.status === "downloading") {
        setDismissedKey((prev) =>
          prev === `${e.payload.available?.version ?? ""}:available` ? null : prev
        );
      }
    });

    return () => {
      active = false;
      unlistenPromise.then((fn) => fn()).catch(() => {});
    };
  }, []);

  const checkForUpdates = useCallback(async (autoDownload?: boolean) => {
    setDismissedKey(null);
    try {
      const next = await invoke<UpdaterState>("updater_check", {
        autoDownload: autoDownload ?? null,
      });
      setState(next);
      return next;
    } catch {
      const fallback = await invoke<UpdaterState>("updater_get_state").catch(() => null);
      if (fallback) setState(fallback);
      return fallback;
    }
  }, []);

  const downloadUpdate = useCallback(async () => {
    setDismissedKey(null);
    try {
      const next = await invoke<UpdaterState>("updater_download");
      setState(next);
      return next;
    } catch {
      const fallback = await invoke<UpdaterState>("updater_get_state").catch(() => null);
      if (fallback) setState(fallback);
      return fallback;
    }
  }, []);

  const cancelDownload = useCallback(async () => {
    const next = await invoke<UpdaterState>("updater_cancel_download").catch(() => null);
    if (next) setState(next);
    return next;
  }, []);

  const installNow = useCallback(async (relaunch = true) => {
    await invoke<void>("updater_install_now", { relaunch });
  }, []);

  const setAutoUpdate = useCallback(async (enabled: boolean) => {
    const next = await invoke<UpdaterState>("updater_set_auto_update", { enabled }).catch(
      () => null
    );
    if (next) setState(next);
    return next;
  }, []);

  const setInstallOnExit = useCallback(async (enabled: boolean) => {
    const next = await invoke<UpdaterState>("updater_set_install_on_exit", { enabled }).catch(
      () => null
    );
    if (next) setState(next);
    return next;
  }, []);

  const currentDismissKey = state
    ? `${state.available?.version ?? "err"}:${state.status}`
    : null;

  const dismissBanner = useCallback(() => {
    if (currentDismissKey) setDismissedKey(currentDismissKey);
  }, [currentDismissKey]);

  const percent =
    state && state.totalBytes > 0
      ? Math.min(100, Math.round((state.downloadedBytes / state.totalBytes) * 100))
      : 0;

  return {
    state,
    percent,
    bannerDismissed: Boolean(dismissedKey && dismissedKey === currentDismissKey),
    dismissBanner,
    checkForUpdates,
    downloadUpdate,
    cancelDownload,
    installNow,
    setAutoUpdate,
    setInstallOnExit,
  };
}
