import { useSyncExternalStore } from "react";
import type { ToastKind } from "../hooks";
import { api } from "../lib/api";
import type {
  AppConfig,
  AudioDeviceOption,
  DesktopApplication,
  GlossaryEntry,
  LiveStatePayload,
  OcrDownloadProgressEvent,
  OcrEngineStatusInfo,
  OcrModelInfo,
  SonioxStatePayload,
  TranslateActionKind,
  TranslateResultPayload,
} from "../types";

export type NotifyFn = (message: string, kind?: ToastKind) => void;

export interface TranslateSlice {
  sourceText: string;
  resultText: string;
  imagePreview: string | null;
  busy: boolean;
  busyAction: TranslateActionKind | null;
  statusText: string | null;
  error: string | null;
}

export type LiveBusyAction = "add" | "edit" | "start" | "stop" | "rescan" | "remove" | "clear";

export interface LiveSlice {
  state: LiveStatePayload;
  apps: DesktopApplication[];
  hasLoadedApps: boolean;
  loadingApps: boolean;
  busyAction: LiveBusyAction | null;
}

export interface AudioSlice {
  sonioxState: SonioxStatePayload;
  micDevices: AudioDeviceOption[];
  sysDevices: AudioDeviceOption[];
  hasLoadedDevices: boolean;
  loadingDevices: boolean;
  toggling: boolean;
}

export interface OcrSlice {
  status: OcrEngineStatusInfo | null;
  models: OcrModelInfo[];
  hasLoaded: boolean;
  lastConfigKey: string;
  checking: boolean;
  downloadingId: string | null;
  cancellingDownload: boolean;
  downloadProgress: OcrDownloadProgressEvent | null;
  downloadError: string | null;
}

export interface AiSlice {
  glossaryDraft: string;
  glossaryDirty: boolean;
  savingGlossary: boolean;
}

export interface HotkeysSlice {
  resetting: boolean;
}

export interface AppStoreState {
  translate: TranslateSlice;
  live: LiveSlice;
  audio: AudioSlice;
  ocr: OcrSlice;
  ai: AiSlice;
  hotkeys: HotkeysSlice;
}

export type AppSliceKey = keyof AppStoreState;

export interface TabBusyInfo {
  busy: boolean;
  label?: string;
}

export function formatGlossaryEntries(entries: GlossaryEntry[]): string {
  return entries.map((e) => `${e.source} = ${e.target}`).join("\n");
}

function ocrConfigKey(cfg: Pick<AppConfig, "ocr_engine" | "ocr_model" | "ocr_backend">): string {
  return `${cfg.ocr_engine}|${cfg.ocr_model}|${cfg.ocr_backend}`;
}

function isAlreadyRunningError(err: unknown): boolean {
  return String(err).includes("ALREADY_RUNNING");
}

let state: AppStoreState = {
  translate: {
    sourceText: "",
    resultText: "",
    imagePreview: null,
    busy: false,
    busyAction: null,
    statusText: null,
    error: null,
  },
  live: {
    state: {
      running: false,
      paused_by_focus: false,
      regions: [],
    },
    apps: [],
    hasLoadedApps: false,
    loadingApps: false,
    busyAction: null,
  },
  audio: {
    sonioxState: {
      state: "idle",
      source: "system",
      error: null,
      blocks: [],
    },
    micDevices: [],
    sysDevices: [],
    hasLoadedDevices: false,
    loadingDevices: false,
    toggling: false,
  },
  ocr: {
    status: null,
    models: [],
    hasLoaded: false,
    lastConfigKey: "",
    checking: false,
    downloadingId: null,
    cancellingDownload: false,
    downloadProgress: null,
    downloadError: null,
  },
  ai: {
    glossaryDraft: "",
    glossaryDirty: false,
    savingGlossary: false,
  },
  hotkeys: {
    resetting: false,
  },
};

const listeners = new Set<() => void>();
let notifier: NotifyFn | null = null;
let initialized = false;
let lastOcrConfig: Pick<AppConfig, "ocr_engine" | "ocr_model" | "ocr_backend"> | null = null;

function emitChange() {
  for (const fn of listeners) fn();
}

function updateSlice<K extends AppSliceKey>(
  key: K,
  updater: (prev: AppStoreState[K]) => AppStoreState[K]
) {
  const prevSlice = state[key];
  const nextSlice = updater(prevSlice);
  if (nextSlice === prevSlice) return;
  state = { ...state, [key]: nextSlice };
  emitChange();
}

function notify(message: string, kind: ToastKind = "info") {
  notifier?.(message, kind);
}

export function registerNotifier(fn: NotifyFn | null) {
  notifier = fn;
}

export function getAppState(): AppStoreState {
  return state;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useAppSlice<K extends AppSliceKey>(key: K): AppStoreState[K] {
  return useSyncExternalStore(
    subscribe,
    () => state[key],
    () => state[key]
  );
}

export function useFullAppState(): AppStoreState {
  return useSyncExternalStore(subscribe, getAppState, getAppState);
}

export function computeTabBusyMap(s: AppStoreState): Record<string, TabBusyInfo> {
  const liveLabel =
    s.live.busyAction === "add"
      ? "Đang chọn vùng Live…"
      : s.live.busyAction === "edit"
        ? "Đang chỉnh vùng Live…"
        : s.live.busyAction === "start"
          ? "Đang khởi động Live…"
          : s.live.busyAction === "stop"
            ? "Đang dừng Live…"
            : s.live.busyAction === "rescan"
              ? "Đang quét lại vùng Live…"
              : s.live.loadingApps
                ? "Đang quét danh sách ứng dụng…"
                : s.live.state.running && s.live.state.paused_by_focus
                  ? "Live đang tạm nghỉ (chờ ứng dụng)"
                  : "Đang dịch Live…";

  const audioState = s.audio.sonioxState.state;
  const audioLabel = s.audio.loadingDevices
    ? "Đang quét thiết bị âm thanh…"
    : audioState === "connecting"
      ? "Đang kết nối Soniox…"
      : audioState === "listening"
        ? "Đang lắng nghe & dịch âm thanh…"
        : audioState === "reconnecting"
          ? "Đang kết nối lại Soniox…"
          : audioState === "standby"
            ? "Dịch âm thanh đang ở chế độ chờ…"
            : audioState === "stopping"
              ? "Đang dừng dịch âm thanh…"
              : "Đang chuyển trạng thái âm thanh…";

  const ocrProg = s.ocr.downloadProgress;
  const ocrLabel = s.ocr.downloadingId
    ? ocrProg && ocrProg.percent > 0
      ? `Đang tải model OCR (${Math.round(ocrProg.percent)}%)`
      : "Đang tải model OCR…"
    : "Đang kiểm tra trạng thái OCR…";

  return {
    translate: {
      busy: s.translate.busy,
      label: s.translate.statusText || "Đang dịch…",
    },
    live: {
      busy: s.live.state.running || s.live.loadingApps || s.live.busyAction !== null,
      label: liveLabel,
    },
    audio: {
      busy: audioState !== "idle" || s.audio.loadingDevices || s.audio.toggling,
      label: audioLabel,
    },
    ai: {
      busy: s.ai.savingGlossary,
      label: "Đang lưu từ điển thuật ngữ…",
    },
    ocr: {
      busy: Boolean(s.ocr.downloadingId) || s.ocr.checking,
      label: ocrLabel,
    },
    hotkeys: {
      busy: s.hotkeys.resetting,
      label: "Đang khôi phục phím tắt…",
    },
  };
}

export function useTabBusyMap(): Record<string, TabBusyInfo> {
  const s = useFullAppState();
  return computeTabBusyMap(s);
}

export async function hydrateFromBackend(): Promise<void> {
  try {
    const [snap, live, soniox] = await Promise.all([
      api.getTaskSnapshot(),
      api.getLiveState(),
      api.getSonioxState(),
    ]);
    const active = new Set(snap.activeTasks);

    updateSlice("live", (prev) => ({
      ...prev,
      state: live,
      loadingApps: active.has("live:apps"),
    }));

    updateSlice("audio", (prev) => ({
      ...prev,
      sonioxState: soniox,
      loadingDevices: active.has("audio:devices:sys") || active.has("audio:devices:mic"),
      toggling: active.has("audio:start"),
    }));

    updateSlice("ocr", (prev) => {
      const downloadingId =
        snap.ocr.downloadingModelId ?? (active.has("ocr:download") ? prev.downloadingId : null);
      return {
        ...prev,
        downloadingId,
        cancellingDownload: downloadingId ? prev.cancellingDownload : false,
        downloadProgress: downloadingId ? snap.ocr.downloadProgress ?? prev.downloadProgress : null,
        downloadError: snap.ocr.lastError ?? prev.downloadError,
      };
    });

    updateSlice("translate", (prev) => {
      const busy =
        snap.translate.busy || active.has("translate:text") || active.has("translate:action");
      return {
        ...prev,
        busy,
        busyAction: busy
          ? ((snap.translate.action as TranslateActionKind | null) ?? prev.busyAction)
          : null,
        statusText: busy ? snap.translate.statusText ?? prev.statusText : null,
        sourceText: prev.sourceText || snap.translate.lastSource || "",
        resultText: prev.resultText || snap.translate.lastResult || "",
        imagePreview: prev.imagePreview ?? snap.translate.lastImageDataUrl ?? null,
        error: snap.translate.lastError ?? prev.error,
      };
    });
  } catch {
    // Ignore hydration failures when running outside Tauri
  }
}

export function initAppStore(): void {
  if (initialized) return;
  initialized = true;

  api
    .onLiveState((live) => {
      updateSlice("live", (prev) => ({ ...prev, state: live }));
    })
    .catch(() => {});

  api
    .onSonioxState((sx) => {
      updateSlice("audio", (prev) => ({ ...prev, sonioxState: sx }));
    })
    .catch(() => {});

  api
    .onOcrDownloadProgress((prog) => {
      updateSlice("ocr", (prev) => ({
        ...prev,
        downloadingId: prog.modelId,
        downloadProgress: prog,
        downloadError: null,
      }));
    })
    .catch(() => {});

  api
    .onOcrTaskState((snap) => {
      const prevDownloading = state.ocr.downloadingId;
      updateSlice("ocr", (prev) => ({
        ...prev,
        downloadingId: snap.downloadingModelId,
        cancellingDownload: snap.downloadingModelId ? prev.cancellingDownload : false,
        downloadProgress: snap.downloadingModelId ? snap.downloadProgress : null,
        downloadError: snap.lastError,
      }));
      if (prevDownloading && !snap.downloadingModelId && lastOcrConfig) {
        void appActions.refreshOcr(lastOcrConfig, true);
      }
    })
    .catch(() => {});

  api
    .onTranslateTaskState((snap) => {
      const succeeded = !snap.busy && !snap.lastError;
      updateSlice("translate", (prev) => ({
        ...prev,
        busy: snap.busy,
        busyAction: snap.busy ? ((snap.action as TranslateActionKind | null) ?? prev.busyAction) : null,
        statusText: snap.busy ? snap.statusText ?? prev.statusText : null,
        sourceText:
          succeeded && snap.lastSource !== null && snap.lastSource !== ""
            ? snap.lastSource
            : prev.sourceText,
        resultText:
          succeeded && snap.lastResult !== null && snap.lastResult !== ""
            ? snap.lastResult
            : prev.resultText,
        imagePreview:
          succeeded &&
          ((snap.lastSource !== null && snap.lastSource !== "") ||
            (snap.lastResult !== null && snap.lastResult !== "") ||
            snap.lastImageDataUrl !== null)
            ? snap.lastImageDataUrl
            : prev.imagePreview,
        error: snap.lastError,
      }));
    })
    .catch(() => {});

  void hydrateFromBackend();
}

export const appActions = {
  // ── Config sync helpers ─────────────────────────────────────────────────────
  syncGlossaryFromConfig(entries: GlossaryEntry[]) {
    if (state.ai.glossaryDirty) return;
    const formatted = formatGlossaryEntries(entries);
    if (state.ai.glossaryDraft === formatted) return;
    updateSlice("ai", (prev) => ({ ...prev, glossaryDraft: formatted }));
  },

  // ── Translate ───────────────────────────────────────────────────────────────
  setSourceText(text: string) {
    updateSlice("translate", (prev) => ({ ...prev, sourceText: text }));
  },

  clearTranslate() {
    if (state.translate.busy) return;
    updateSlice("translate", (prev) => ({
      ...prev,
      sourceText: "",
      resultText: "",
      imagePreview: null,
      error: null,
    }));
  },

  async translateText(config: AppConfig) {
    const trimmed = state.translate.sourceText.trim();
    if (!trimmed || state.translate.busy) return;
    updateSlice("translate", (prev) => ({
      ...prev,
      busy: true,
      busyAction: "text",
      statusText: "Đang dịch văn bản…",
      imagePreview: null,
      error: null,
    }));
    try {
      const res = await api.translateText(
        trimmed,
        config.text_target_language,
        config.text_source_language
      );
      updateSlice("translate", (prev) => ({
        ...prev,
        resultText: res.translated,
        busy: false,
        busyAction: null,
        statusText: null,
        error: null,
      }));
      if (config.text_auto_copy_result && res.translated.trim()) {
        notify("Đã dịch và tự sao chép kết quả", "success");
      }
    } catch (err) {
      if (isAlreadyRunningError(err)) {
        await hydrateFromBackend();
        return;
      }
      const msg = String(err);
      updateSlice("translate", (prev) => ({
        ...prev,
        busy: false,
        busyAction: null,
        statusText: null,
        error: msg,
      }));
      notify(msg, "error");
    }
  },

  async runTranslateAction(
    action: Exclude<TranslateActionKind, "text">,
    fn: () => Promise<TranslateResultPayload>,
    statusText: string,
    okMsg?: string
  ) {
    if (state.translate.busy) return;
    updateSlice("translate", (prev) => ({
      ...prev,
      busy: true,
      busyAction: action,
      statusText,
      error: null,
    }));
    try {
      const res = await fn();
      updateSlice("translate", (prev) => ({
        ...prev,
        sourceText: res.original ? res.original : prev.sourceText,
        resultText: res.translated ? res.translated : prev.resultText,
        imagePreview: res.image_data_url,
        busy: false,
        busyAction: null,
        statusText: null,
        error: null,
      }));
      if (okMsg && (res.translated || res.image_data_url)) {
        notify(okMsg, "success");
      }
    } catch (err) {
      if (isAlreadyRunningError(err)) {
        await hydrateFromBackend();
        return;
      }
      const msg = String(err);
      updateSlice("translate", (prev) => ({
        ...prev,
        busy: false,
        busyAction: null,
        statusText: null,
        error: msg,
      }));
      notify(msg, "error");
    }
  },

  // ── Live ────────────────────────────────────────────────────────────────────
  async loadDesktopApps(force = false) {
    const cur = state.live;
    if (cur.loadingApps) return;
    if (!force && cur.hasLoadedApps) return;
    updateSlice("live", (prev) => ({ ...prev, loadingApps: true }));
    try {
      const list = await api.listDesktopApps();
      updateSlice("live", (prev) => ({
        ...prev,
        apps: list,
        hasLoadedApps: true,
        loadingApps: false,
      }));
    } catch (err) {
      if (isAlreadyRunningError(err)) {
        await hydrateFromBackend();
        return;
      }
      updateSlice("live", (prev) => ({ ...prev, loadingApps: false }));
    }
  },

  async liveAddRegion(mode: "overlay" | "frame") {
    if (state.live.busyAction) return;
    updateSlice("live", (prev) => ({ ...prev, busyAction: "add" }));
    try {
      const added = await api.liveAddRegion(mode);
      if (added) {
        const next = await api.getLiveState();
        updateSlice("live", (prev) => ({ ...prev, state: next }));
        if (mode === "frame") {
          await api.openLiveOutputWindow(added.id, added.bbox);
        }
        notify(
          mode === "overlay" ? "Đã thêm vùng Live Overlay" : "Đã thêm vùng Live Khung nổi",
          "success"
        );
      }
    } catch (err) {
      if (!isAlreadyRunningError(err)) {
        notify(String(err), "error");
      }
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  async liveEditRegion(id: number) {
    if (state.live.busyAction) return;
    updateSlice("live", (prev) => ({ ...prev, busyAction: "edit" }));
    try {
      const st = await api.liveEditRegion(id);
      updateSlice("live", (prev) => ({ ...prev, state: st }));
    } catch (err) {
      if (!isAlreadyRunningError(err)) {
        notify(String(err), "error");
      }
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  async liveToggleRun() {
    if (state.live.busyAction) return;
    const isRunning = state.live.state.running;
    updateSlice("live", (prev) => ({ ...prev, busyAction: isRunning ? "stop" : "start" }));
    try {
      if (isRunning) {
        const st = await api.liveStop();
        updateSlice("live", (prev) => ({ ...prev, state: st }));
        notify("Đã dừng dịch Live", "info");
      } else {
        for (const r of state.live.state.regions) {
          if (r.mode === "frame") {
            await api.openLiveOutputWindow(r.id, r.bbox);
          }
        }
        const st = await api.liveStart();
        updateSlice("live", (prev) => ({ ...prev, state: st }));
        notify("Đã bắt đầu dịch Live", "success");
      }
    } catch (err) {
      if (!isAlreadyRunningError(err)) {
        notify(String(err), "error");
      }
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  async liveRescan() {
    if (state.live.busyAction) return;
    updateSlice("live", (prev) => ({ ...prev, busyAction: "rescan" }));
    try {
      await api.liveRescan();
      notify("Đang quét lại toàn bộ vùng Live…", "info");
    } catch (err) {
      notify(String(err), "error");
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  async liveRemoveRegion(id: number, index: number) {
    if (state.live.busyAction) return;
    updateSlice("live", (prev) => ({ ...prev, busyAction: "remove" }));
    try {
      const st = await api.liveRemoveRegion(id);
      updateSlice("live", (prev) => ({ ...prev, state: st }));
      notify(`Đã xoá vùng #${index}`, "info");
    } catch (err) {
      notify(String(err), "error");
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  async liveClearRegions() {
    if (state.live.busyAction) return;
    updateSlice("live", (prev) => ({ ...prev, busyAction: "clear" }));
    try {
      const st = await api.liveClearRegions();
      updateSlice("live", (prev) => ({ ...prev, state: st }));
      notify("Đã xoá toàn bộ vùng Live", "info");
    } catch (err) {
      notify(String(err), "error");
    } finally {
      updateSlice("live", (prev) => ({ ...prev, busyAction: null }));
    }
  },

  // ── Audio / Soniox ──────────────────────────────────────────────────────────
  async loadAudioDevices(force = false) {
    const cur = state.audio;
    if (cur.loadingDevices) return;
    if (!force && cur.hasLoadedDevices) return;
    updateSlice("audio", (prev) => ({ ...prev, loadingDevices: true }));
    try {
      const [mics, sys] = await Promise.all([
        api.listAudioDevices(false),
        api.listAudioDevices(true),
      ]);
      updateSlice("audio", (prev) => ({
        ...prev,
        micDevices: mics,
        sysDevices: sys,
        hasLoadedDevices: true,
        loadingDevices: false,
      }));
    } catch (err) {
      if (isAlreadyRunningError(err)) {
        await hydrateFromBackend();
        return;
      }
      updateSlice("audio", (prev) => ({ ...prev, loadingDevices: false }));
    }
  },

  async toggleSoniox() {
    const cur = state.audio;
    if (cur.toggling) return;
    const isActive = cur.sonioxState.state !== "idle";
    if (cur.sonioxState.state === "connecting" || cur.sonioxState.state === "stopping") return;
    updateSlice("audio", (prev) => ({ ...prev, toggling: true }));
    try {
      if (isActive) {
        const st = await api.sonioxStop();
        updateSlice("audio", (prev) => ({ ...prev, sonioxState: st }));
        notify("Đã dừng dịch âm thanh", "info");
      } else {
        await api.sonioxStart();
        notify("Đã khởi động dịch âm thanh Soniox", "success");
      }
    } catch (err) {
      if (!isAlreadyRunningError(err)) {
        notify(String(err), "error");
      }
    } finally {
      updateSlice("audio", (prev) => ({ ...prev, toggling: false }));
    }
  },

  async clearSoniox() {
    try {
      const st = await api.sonioxClear();
      updateSlice("audio", (prev) => ({ ...prev, sonioxState: st }));
    } catch (err) {
      notify(String(err), "error");
    }
  },

  // ── OCR ─────────────────────────────────────────────────────────────────────
  async refreshOcr(
    cfg: Pick<AppConfig, "ocr_engine" | "ocr_model" | "ocr_backend">,
    force = false
  ) {
    lastOcrConfig = {
      ocr_engine: cfg.ocr_engine,
      ocr_model: cfg.ocr_model,
      ocr_backend: cfg.ocr_backend,
    };
    const key = ocrConfigKey(cfg);
    const cur = state.ocr;
    if (cur.checking) return;
    if (!force && cur.hasLoaded && cur.lastConfigKey === key) return;

    updateSlice("ocr", (prev) => ({ ...prev, checking: true }));
    try {
      const [st, list] = await Promise.all([
        api.getOcrStatus(cfg.ocr_engine, cfg.ocr_model, cfg.ocr_backend),
        api.listOcrModels(),
      ]);
      updateSlice("ocr", (prev) => ({
        ...prev,
        status: st,
        models: list,
        hasLoaded: true,
        lastConfigKey: key,
        checking: false,
      }));
    } catch {
      updateSlice("ocr", (prev) => ({ ...prev, checking: false }));
    }
  },

  async downloadOcrModel(
    modelId: string,
    cfg: Pick<AppConfig, "ocr_engine" | "ocr_model" | "ocr_backend">
  ) {
    if (state.ocr.downloadingId) return;
    lastOcrConfig = {
      ocr_engine: cfg.ocr_engine,
      ocr_model: cfg.ocr_model,
      ocr_backend: cfg.ocr_backend,
    };
    const modelLabel = state.ocr.models.find((m) => m.id === modelId)?.label ?? modelId;
    updateSlice("ocr", (prev) => ({
      ...prev,
      downloadingId: modelId,
      cancellingDownload: false,
      downloadError: null,
      downloadProgress: {
        modelId,
        modelLabel,
        fileIndex: 1,
        fileTotal: 3,
        currentFile: "Đang chuẩn bị tải…",
        downloadedBytes: 0,
        totalBytes: 0,
        percent: 0,
      },
    }));

    try {
      const next = await api.downloadOcrModel(modelId);
      updateSlice("ocr", (prev) => ({
        ...prev,
        models: next,
        downloadingId: null,
        cancellingDownload: false,
        downloadProgress: null,
        downloadError: null,
      }));
      await appActions.refreshOcr(cfg, true);
      notify("Đã tải xong model OCR ngoại tuyến", "success");
    } catch (err) {
      if (isAlreadyRunningError(err)) {
        await hydrateFromBackend();
        return;
      }
      const msg = String(err);
      const cancelled = msg.includes("Đã huỷ");
      updateSlice("ocr", (prev) => ({
        ...prev,
        downloadingId: null,
        cancellingDownload: false,
        downloadProgress: null,
        downloadError: cancelled ? null : msg,
      }));
      notify(msg, cancelled ? "info" : "error");
    }
  },

  cancelOcrDownload() {
    if (!state.ocr.downloadingId || state.ocr.cancellingDownload) return;
    updateSlice("ocr", (prev) => ({ ...prev, cancellingDownload: true }));
    api.cancelTask("ocr").catch(() => {});
  },

  // ── AI Providers / Glossary ─────────────────────────────────────────────────
  setGlossaryDraft(text: string) {
    updateSlice("ai", (prev) => ({
      ...prev,
      glossaryDraft: text,
      glossaryDirty: true,
    }));
  },

  async saveGlossary(
    entries: GlossaryEntry[],
    onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>
  ) {
    if (state.ai.savingGlossary) return;
    updateSlice("ai", (prev) => ({ ...prev, savingGlossary: true }));
    try {
      await onUpdateConfig({ translation_glossary: entries });
      updateSlice("ai", (prev) => ({
        ...prev,
        glossaryDraft: formatGlossaryEntries(entries),
        glossaryDirty: false,
        savingGlossary: false,
      }));
      notify(`Đã lưu ${entries.length} thuật ngữ`, "success");
    } catch (err) {
      updateSlice("ai", (prev) => ({ ...prev, savingGlossary: false }));
      notify(String(err), "error");
    }
  },

  // ── Hotkeys ─────────────────────────────────────────────────────────────────
  async resetHotkeys(onConfigReplaced: (cfg: AppConfig) => void) {
    if (state.hotkeys.resetting) return;
    updateSlice("hotkeys", (prev) => ({ ...prev, resetting: true }));
    try {
      const updated = await api.resetHotkeys();
      onConfigReplaced(updated);
      notify("Đã khôi phục phím tắt mặc định", "success");
    } catch (err) {
      if (!isAlreadyRunningError(err)) {
        notify(String(err), "error");
      }
    } finally {
      updateSlice("hotkeys", (prev) => ({ ...prev, resetting: false }));
    }
  },
};
