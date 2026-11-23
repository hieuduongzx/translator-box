import { useCallback, useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  AudioLines,
  Bot,
  Keyboard,
  Languages,
  Palette,
  Radio,
  ScanText,
  Settings,
} from "lucide-react";
import {
  Sidebar,
  TitleBar,
  ToastProvider,
  UpdateBanner,
  useToast,
  type SidebarItem,
} from "./components/ui";
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
const PAGE_STORAGE_KEY = "translator2k.ui.activePage";
const SETTINGS_TAB_STORAGE_KEY = "translator2k.ui.settingsTab";

function loadInitialPage(): string {
  try {
    const raw = localStorage.getItem(PAGE_STORAGE_KEY);
    if (raw && VALID_PAGES.has(raw)) return raw;
  } catch {
    // ignore
  }
  return "translate";
}

function loadInitialSettingsTab(): SettingsTab {
  try {
    const raw = localStorage.getItem(SETTINGS_TAB_STORAGE_KEY);
    if (raw === "general" || raw === "text") return raw;
  } catch {
    // ignore
  }
  return "general";
}

function applyTheme(theme: AppConfig["ui_theme"]) {
  try {
    localStorage.setItem("translator2k_theme", theme);
  } catch {
    // ignore
  }
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = theme === "system" ? (prefersDark ? "dark" : "light") : theme;
  document.documentElement.setAttribute("data-theme", resolved);
}

function MainApp() {
  const { toast } = useToast();
  const updater = useUpdater();
  const [activePage, setActivePageState] = useState<string>(loadInitialPage);
  const [settingsTab, setSettingsTabState] = useState<SettingsTab>(loadInitialSettingsTab);
  const [appVersion, setAppVersion] = useState<string>("");
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

  const setActivePage = useCallback((page: string) => {
    const safe = VALID_PAGES.has(page) ? page : "translate";
    setActivePageState(safe);
    try {
      localStorage.setItem(PAGE_STORAGE_KEY, safe);
    } catch {
      // ignore
    }
  }, []);

  const setSettingsTab = useCallback((tab: SettingsTab) => {
    setSettingsTabState(tab);
    try {
      localStorage.setItem(SETTINGS_TAB_STORAGE_KEY, tab);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    getVersion()
      .then((ver) => {
        if (ver) setAppVersion(ver);
      })
      .catch(() => {});

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
        if (m?.version) {
          setAppVersion((prev) => prev || m.version);
        }
        setHistory(hist);
        setLiveState(live);
        setSonioxState(sx);
        applyTheme(cfg.ui_theme);
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
        applyTheme(cfg.ui_theme);
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
        } else {
          setActivePage(page);
        }
      }),
    ];

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onScheme = () => {
      setConfig((cur) => {
        if (cur) applyTheme(cur.ui_theme);
        return cur;
      });
    };
    media.addEventListener("change", onScheme);

    return () => {
      media.removeEventListener("change", onScheme);
      for (const p of unlisteners) {
        p.then((fn) => fn()).catch(() => {});
      }
    };
  }, [setActivePage, setSettingsTab]);

  const updateConfig = useCallback(
    async (patch: Partial<AppConfig>) => {
      if (!config) return;
      const merged: AppConfig = { ...config, ...patch };
      setConfig(merged);
      if (patch.ui_theme) applyTheme(patch.ui_theme);
      try {
        const saved = await api.saveConfig(merged);
        setConfig(saved);
      } catch (err) {
        toast(String(err), "error");
      }
    },
    [config, toast]
  );

  const resolvedVersion = appVersion || updater.state?.currentVersion || meta?.version || "";
  const hasUpdate = Boolean(
    updater.state &&
      ["available", "downloading", "verifying", "ready"].includes(updater.state.status)
  );

  if (!config) {
    return (
      <div className="app-shell">
        <TitleBar title="Translator2k" status={status} />
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
    },
    {
      id: "audio",
      label: "Dịch âm thanh",
      icon: <AudioLines size={20} />,
      badge: sonioxState.state !== "idle" ? "ON" : undefined,
    },
    { id: "ai", label: "Dịch vụ AI", icon: <Bot size={20} /> },
    { id: "ocr", label: "OCR", icon: <ScanText size={20} /> },
    { id: "appearance", label: "Khung dịch", icon: <Palette size={20} /> },
    { id: "hotkeys", label: "Phím tắt", icon: <Keyboard size={20} /> },
  ];

  const footerItems: SidebarItem[] = [
    { id: "settings", label: "Cài đặt", icon: <Settings size={20} /> },
  ];

  return (
    <div className="app-shell">
      <TitleBar title={meta?.name ?? "Translator2k"} status={status} />
      <UpdateBanner appName={meta?.name ?? "Translator2k"} updater={updater} />
      <div className="app-body">
        <Sidebar
          items={navItems}
          footerItems={footerItems}
          activeId={activePage}
          collapsed={config.sidebar_collapsed}
          version={resolvedVersion}
          hasUpdate={hasUpdate}
          onSelect={setActivePage}
          onToggleCollapse={() =>
            updateConfig({ sidebar_collapsed: !config.sidebar_collapsed })
          }
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
              />
            )}
            {activePage === "live" && (
              <LivePage
                config={config}
                liveState={liveState}
                onUpdateConfig={updateConfig}
                onLiveStateChange={setLiveState}
              />
            )}
            {activePage === "audio" && (
              <AudioPage
                config={config}
                sonioxState={sonioxState}
                onUpdateConfig={updateConfig}
                onSonioxChange={setSonioxState}
              />
            )}
            {activePage === "ai" && (
              <AiProvidersPage config={config} onUpdateConfig={updateConfig} />
            )}
            {activePage === "ocr" && (
              <OcrPage config={config} onUpdateConfig={updateConfig} />
            )}
            {activePage === "appearance" && (
              <AppearancePage config={config} onUpdateConfig={updateConfig} />
            )}
            {activePage === "hotkeys" && (
              <HotkeysPage
                config={config}
                onUpdateConfig={updateConfig}
                onConfigReplaced={setConfig}
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
              />
            )}
          </div>
        </main>
      </div>
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
  return (
    <ToastProvider>
      <MainApp />
    </ToastProvider>
  );
}
