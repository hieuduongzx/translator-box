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
  Settings,
} from "lucide-react";
import {
  Sidebar,
  TitleBar,
  ToastProvider,
  useToast,
  type SidebarItem,
} from "./components/ui";
import { api } from "./lib/api";
import { AiProvidersPage } from "./pages/AiProvidersPage";
import { AppearancePage } from "./pages/AppearancePage";
import { AudioPage } from "./pages/AudioPage";
import { HotkeysPage } from "./pages/HotkeysPage";
import { LivePage } from "./pages/LivePage";
import { OcrPage } from "./pages/OcrPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TranslatePage } from "./pages/TranslatePage";
import { HudWindow } from "./windows/HudWindow";
import { LiveOutputWindow } from "./windows/LiveOutputWindow";
import type {
  AppConfig,
  AppMeta,
  HistoryEntry,
  LiveStatePayload,
  SonioxStatePayload,
  StatusEvent,
} from "./types";

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
  const [activePage, setActivePage] = useState("translate");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [meta, setMeta] = useState<AppMeta | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
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
      }),
      api.onTranslationResult((entry) => {
        setHistory((prev) => [entry, ...prev].slice(0, 30));
      }),
      api.onLiveState(setLiveState),
      api.onSonioxState(setSonioxState),
      api.onNavigate((page) => setActivePage(page)),
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
  }, []);

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
      <div className="app-body">
        <Sidebar
          items={navItems}
          footerItems={footerItems}
          activeId={activePage}
          collapsed={config.sidebar_collapsed}
          onSelect={setActivePage}
          onToggleCollapse={() =>
            updateConfig({ sidebar_collapsed: !config.sidebar_collapsed })
          }
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
              <SettingsPage config={config} meta={meta} onUpdateConfig={updateConfig} />
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
