import { useCallback, useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  AudioLines,
  Bot,
  Keyboard,
  Languages,
  Palette,
  Radio,
  ScanText,
} from "lucide-react";
import { Sidebar, TitleBar, Toast, type SidebarItem } from "./components/ui";
import { UpdateBanner } from "./components/ui/UpdateBanner";
import {
  isThemeMode,
  themeStorageKey,
  useAppVersion,
  usePersistentState,
  useTheme,
  useToast,
  type ToastKind,
} from "./hooks";
import { useUpdater } from "./hooks/useUpdater";
import { api } from "./lib/api";
import { AiProvidersPage } from "./pages/AiProvidersPage";
import { AppearancePage } from "./pages/AppearancePage";
import { AudioPage } from "./pages/AudioPage";
import { HotkeysPage } from "./pages/HotkeysPage";
import { LivePage } from "./pages/LivePage";
import { OcrPage } from "./pages/OcrPage";
import { SettingsPage, type SettingsTab } from "./pages/SettingsPage";
import { TranslatePage } from "./pages/TranslatePage";
import { HudWindow } from "./windows/HudWindow";
import { LiveOutputWindow } from "./windows/LiveOutputWindow";
import type {
  AppConfig,
  AppMeta,
  HistoryEntry,
  LiveStatePayload,
  ReplaceCompletedPayload,
  SonioxStatePayload,
  StatusEvent,
} from "./types";

const VALID_PAGES = new Set([
  "translate",
  "live",
  "audio",
  "ai",
  "ocr",
  "appearance",
  "hotkeys",
  "settings",
]);

function isValidPage(v: unknown): v is string {
  return typeof v === "string" && VALID_PAGES.has(v);
}

function isValidSettingsTab(v: unknown): v is SettingsTab {
  return v === "general" || v === "text";
}

function MainApp() {
  const { toasts, showToast, dismissToast } = useToast(4, 4200);
  const { setTheme } = useTheme("translator2k");
  const appVersion = useAppVersion();
  const updater = useUpdater();

  const [activePage, setActivePage] = usePersistentState<string>(
    "translator2k.ui.activePage",
    "translate",
    { validate: isValidPage }
  );
  const [settingsTab, setSettingsTab] = usePersistentState<SettingsTab>(
    "translator2k.ui.settingsTab",
    "general",
    { validate: isValidSettingsTab }
  );
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState<boolean>(
    "translator2k.ui.sidebarCollapsed",
    false,
    { validate: (v): v is boolean => typeof v === "boolean" }
  );

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [meta, setMeta] = useState<AppMeta | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [lastReplace, setLastReplace] = useState<ReplaceCompletedPayload | null>(null);
  const [status, setStatus] = useState<StatusEvent>({ text: "Sẵn sàng", state: "ready" });
  const [liveState, setLiveState] = useState<LiveStatePayload>({
    running: false,
    paused_by_focus: false,
    regions: [],
  });
  const [sonioxState, setSonioxState] = useState<SonioxStatePayload>({
    state: "idle",
    source: "system",
    error: null,
    blocks: [],
  });

  const notify = useCallback(
    (message: string, kind: ToastKind = "info") => {
      showToast(kind, message);
    },
    [showToast]
  );

  useEffect(() => {
    Promise.all([
      api.getConfig(),
      api.getAppMeta(),
      api.getHistory(),
      api.getLiveState(),
      api.getSonioxState(),
    ])
      .then(([cfg, m, hist, live, sx]) => {
        setConfig(cfg);
        setMeta(m);
        setHistory(hist);
        setLiveState(live);
        setSonioxState(sx);
        if (isThemeMode(cfg.ui_theme)) {
          try {
            if (!localStorage.getItem(themeStorageKey("translator2k"))) {
              setTheme(cfg.ui_theme);
            }
          } catch {
            setTheme(cfg.ui_theme);
          }
        }
        try {
          if (localStorage.getItem("translator2k.ui.sidebarCollapsed") === null) {
            setSidebarCollapsed(cfg.sidebar_collapsed);
          }
        } catch {
          setSidebarCollapsed(cfg.sidebar_collapsed);
        }
      })
      .catch(() => {})
      .finally(() => {
        requestAnimationFrame(() => {
          api.showMainWindow().catch(() => {
            getCurrentWindow().show().catch(() => {});
          });
        });
      });

    const unlisteners = [
      api.onStatus(setStatus),
      api.onConfigUpdated((cfg) => {
        setConfig(cfg);
        if (isThemeMode(cfg.ui_theme)) {
          setTheme(cfg.ui_theme);
        }
        setHistory((prev) => prev.slice(0, cfg.text_history_limit));
      }),
      api.onTranslationResult((entry) => {
        setConfig((cur) => {
          if (!cur || cur.text_keep_history) {
            const limit = cur?.text_history_limit ?? 30;
            setHistory((prev) => [entry, ...prev].slice(0, limit));
          }
          return cur;
        });
      }),
      api.onReplaceCompleted((payload) => {
        setLastReplace(payload);
      }),
      api.onLiveState(setLiveState),
      api.onSonioxState(setSonioxState),
      api.onNavigate((page) => {
        if (page === "settings:text") {
          setSettingsTab("text");
          setActivePage("settings");
        } else if (VALID_PAGES.has(page)) {
          setActivePage(page);
        }
      }),
    ];

    return () => {
      for (const p of unlisteners) {
        p.then((fn) => fn()).catch(() => {});
      }
    };
  }, [setActivePage, setSettingsTab, setSidebarCollapsed, setTheme]);

  const updateConfig = useCallback(
    async (patch: Partial<AppConfig>) => {
      if (!config) return;
      const merged: AppConfig = { ...config, ...patch };
      setConfig(merged);
      if (patch.ui_theme && isThemeMode(patch.ui_theme)) {
        setTheme(patch.ui_theme);
      }
      if (typeof patch.sidebar_collapsed === "boolean") {
        setSidebarCollapsed(patch.sidebar_collapsed);
      }
      try {
        const saved = await api.saveConfig(merged);
        setConfig(saved);
      } catch (err) {
        notify(String(err), "error");
      }
    },
    [config, notify, setSidebarCollapsed, setTheme]
  );

  const resolvedVersion = appVersion || updater.state?.currentVersion || meta?.version || "";
  const hasUpdate = Boolean(
    updater.state &&
      ["available", "downloading", "verifying", "ready"].includes(updater.state.status)
  );

  const statusIndicator = (
    <span className="titlebar-status" data-tauri-drag-region>
      <span
        className={`status-dot ${
          status.state === "busy" ? "busy" : status.state === "error" ? "error" : ""
        }`}
      />
      <span>{status.text}</span>
    </span>
  );

  if (!config) {
    return (
      <div className="app-shell">
        <TitleBar title="Translator2k" rightContent={statusIndicator} />
        <div className="content-area loading-shell">
          <span className="field-hint">Đang tải cấu hình…</span>
        </div>
      </div>
    );
  }

  const navItems: SidebarItem[] = [
    { id: "translate", label: "Dịch nhanh", icon: <Languages size={20} /> },
    {
      id: "live",
      label: "Live màn hình",
      icon: <Radio size={20} />,
      badge: liveState.running ? "ON" : undefined,
      badgeVariant: "accent",
    },
    {
      id: "audio",
      label: "Dịch âm thanh",
      icon: <AudioLines size={20} />,
      badge: sonioxState.state !== "idle" ? "ON" : undefined,
      badgeVariant: "accent",
    },
    { id: "ai", label: "Dịch vụ AI", icon: <Bot size={20} /> },
    { id: "ocr", label: "OCR", icon: <ScanText size={20} /> },
    { id: "appearance", label: "Khung dịch", icon: <Palette size={20} /> },
    { id: "hotkeys", label: "Phím tắt", icon: <Keyboard size={20} /> },
  ];

  const handleToggleCollapse = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    void updateConfig({ sidebar_collapsed: next });
  };

  return (
    <div className="app-shell">
      <TitleBar title={meta?.name ?? "Translator2k"} rightContent={statusIndicator} />
      <UpdateBanner appName={meta?.name ?? "Translator2k"} updater={updater} />
      <div className="app-body">
        <Sidebar
          items={navItems}
          activeId={activePage}
          collapsed={sidebarCollapsed}
          settingsId="settings"
          settingsBadge={
            updater.state?.status === "ready"
              ? "Mới"
              : updater.state?.status === "available"
                ? "1"
                : undefined
          }
          hasUpdate={hasUpdate}
          version={resolvedVersion}
          onSelect={setActivePage}
          onToggleCollapse={handleToggleCollapse}
          onVersionClick={() => {
            setSettingsTab("general");
            setActivePage("settings");
          }}
        />
        <main className="content-area">
          <div
            className={
              activePage === "translate"
                ? "page-container page-container-wide"
                : "page-container"
            }
          >
            {activePage === "translate" && (
              <TranslatePage
                config={config}
                history={history}
                lastReplace={lastReplace}
                onDismissReplace={() => setLastReplace(null)}
                onOpenTextSettings={() => {
                  setSettingsTab("text");
                  setActivePage("settings");
                }}
                onUpdateConfig={updateConfig}
                onHistoryCleared={() => setHistory([])}
                onToast={notify}
              />
            )}
            {activePage === "live" && (
              <LivePage
                config={config}
                liveState={liveState}
                onUpdateConfig={updateConfig}
                onLiveStateChange={setLiveState}
                onToast={notify}
              />
            )}
            {activePage === "audio" && (
              <AudioPage
                config={config}
                sonioxState={sonioxState}
                onUpdateConfig={updateConfig}
                onSonioxChange={setSonioxState}
                onToast={notify}
              />
            )}
            {activePage === "ai" && (
              <AiProvidersPage
                config={config}
                onUpdateConfig={updateConfig}
                onToast={notify}
              />
            )}
            {activePage === "ocr" && (
              <OcrPage config={config} onUpdateConfig={updateConfig} onToast={notify} />
            )}
            {activePage === "appearance" && (
              <AppearancePage
                config={config}
                onUpdateConfig={updateConfig}
                onToast={notify}
              />
            )}
            {activePage === "hotkeys" && (
              <HotkeysPage
                config={config}
                onUpdateConfig={updateConfig}
                onConfigReplaced={setConfig}
                onToast={notify}
              />
            )}
            {activePage === "settings" && (
              <SettingsPage
                config={config}
                meta={meta}
                appVersion={resolvedVersion}
                updater={updater}
                activeTab={settingsTab}
                onTabChange={setSettingsTab}
                onUpdateConfig={updateConfig}
                onToast={notify}
              />
            )}
          </div>
        </main>
      </div>
      <Toast toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

export function App() {
  const label = getCurrentWindow().label;

  if (label === "hud") {
    return <HudWindow />;
  }
  if (label.startsWith("live-output-")) {
    const id = Number(label.slice("live-output-".length) || "1");
    return <LiveOutputWindow regionId={id} />;
  }
  return <MainApp />;
}
