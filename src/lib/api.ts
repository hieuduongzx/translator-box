import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  AppConfig,
  AppMeta,
  AudioDeviceOption,
  DesktopApplication,
  HistoryEntry,
  LiveFrameUpdate,
  LiveRegionInfo,
  LiveStatePayload,
  OcrEngineStatusInfo,
  OcrModelInfo,
  ReplaceCompletedPayload,
  SonioxStatePayload,
  StatusEvent,
  TranslateResultPayload,
} from "../types";

export const api = {
  getAppMeta: () => invoke<AppMeta>("get_app_meta"),
  getConfig: () => invoke<AppConfig>("get_config"),
  saveConfig: (config: AppConfig) => invoke<AppConfig>("save_config", { config }),

  getHistory: () => invoke<HistoryEntry[]>("get_history"),
  clearHistory: () => invoke<void>("clear_history"),
  copyText: (text: string) => invoke<void>("copy_text", { text }),
  translateText: (text: string, target?: string, source?: string) =>
    invoke<TranslateResultPayload>("translate_text_cmd", {
      text,
      target: target ?? null,
      source: source ?? null,
    }),

  regionToText: () => invoke<TranslateResultPayload>("action_region_to_text"),
  regionToOverlay: () => invoke<TranslateResultPayload>("action_region_to_overlay"),
  clipboardImageReplace: () => invoke<TranslateResultPayload>("action_clipboard_image_replace"),
  clipboardImageToText: () => invoke<TranslateResultPayload>("action_clipboard_image_to_text"),
  selectedTextReplace: () => invoke<TranslateResultPayload>("action_selected_text_replace"),
  clearOverlays: () => invoke<void>("clear_overlays"),
  toggleHudWindow: () => invoke<boolean>("toggle_hud_window"),
  startWindowDrag: () => invoke<void>("start_window_drag"),
  openMainWindow: (page?: string) => invoke<void>("open_main_window", { page: page ?? null }),
  showMainWindow: () => invoke<void>("show_main_window"),
  quitApp: () => invoke<void>("quit_app"),

  getLiveState: () => invoke<LiveStatePayload>("get_live_state"),
  liveAddRegion: (mode: "overlay" | "frame") =>
    invoke<LiveRegionInfo | null>("live_add_region", { mode }),
  liveEditRegion: (id: number) => invoke<LiveStatePayload>("live_edit_region", { id }),
  liveRemoveRegion: (id: number) => invoke<LiveStatePayload>("live_remove_region", { id }),
  liveClearRegions: () => invoke<LiveStatePayload>("live_clear_regions"),
  liveStart: () => invoke<LiveStatePayload>("live_start"),
  liveStop: () => invoke<LiveStatePayload>("live_stop"),
  liveRescan: () => invoke<void>("live_rescan"),
  openLiveOutputWindow: (regionId: number, bbox: [number, number, number, number]) =>
    invoke<void>("open_live_output_window", { regionId, bbox }),
  listDesktopApps: () => invoke<DesktopApplication[]>("list_desktop_apps"),

  getOcrStatus: (engine: string, model: string, backend: string) =>
    invoke<OcrEngineStatusInfo>("get_ocr_status", { engine, model, backend }),
  listOcrModels: () => invoke<OcrModelInfo[]>("list_ocr_models"),
  downloadOcrModel: (modelId: string) =>
    invoke<OcrModelInfo[]>("download_ocr_model", { modelId }),

  listAudioDevices: (isSystem: boolean) =>
    invoke<AudioDeviceOption[]>("list_audio_devices_cmd", { isSystem }),
  getSonioxState: () => invoke<SonioxStatePayload>("get_soniox_state"),
  sonioxStart: () => invoke<void>("soniox_start"),
  sonioxStop: () => invoke<SonioxStatePayload>("soniox_stop"),
  sonioxClear: () => invoke<SonioxStatePayload>("soniox_clear"),

  resetHotkeys: () => invoke<AppConfig>("reset_hotkeys"),

  onStatus: (cb: (e: StatusEvent) => void): Promise<UnlistenFn> =>
    listen<StatusEvent>("app-status", (ev) => cb(ev.payload)),
  onConfigUpdated: (cb: (cfg: AppConfig) => void): Promise<UnlistenFn> =>
    listen<AppConfig>("config-updated", (ev) => cb(ev.payload)),
  onTranslationResult: (cb: (entry: HistoryEntry) => void): Promise<UnlistenFn> =>
    listen<HistoryEntry>("translation-result", (ev) => cb(ev.payload)),
  onReplaceCompleted: (cb: (payload: ReplaceCompletedPayload) => void): Promise<UnlistenFn> =>
    listen<ReplaceCompletedPayload>("replace-completed", (ev) => cb(ev.payload)),
  onLiveState: (cb: (state: LiveStatePayload) => void): Promise<UnlistenFn> =>
    listen<LiveStatePayload>("live-state", (ev) => cb(ev.payload)),
  onLiveFrameText: (cb: (upd: LiveFrameUpdate) => void): Promise<UnlistenFn> =>
    listen<LiveFrameUpdate>("live-frame-text", (ev) => cb(ev.payload)),
  onSonioxState: (cb: (state: SonioxStatePayload) => void): Promise<UnlistenFn> =>
    listen<SonioxStatePayload>("soniox-state", (ev) => cb(ev.payload)),
  onNavigate: (cb: (page: string) => void): Promise<UnlistenFn> =>
    listen<string>("navigate", (ev) => cb(ev.payload)),
  onHudShowBar: (cb: () => void): Promise<UnlistenFn> =>
    listen("hud-show-bar", () => cb()),
};
