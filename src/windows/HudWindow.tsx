import { useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  AppWindow,
  AudioLines,
  Camera,
  Check,
  ChevronDown,
  Clipboard,
  Copy,
  Eraser,
  EyeOff,
  FileText,
  GripVertical,
  Image as ImageIcon,
  Languages,
  Layers,
  Mic,
  Monitor,
  MoreHorizontal,
  Move,
  PanelTopClose,
  PenLine,
  Pin,
  Play,
  Power,
  Replace,
  RotateCcw,
  Scan,
  Settings,
  Square,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import {
  LANGUAGES,
  argbHexToRgbaCss,
  buildHudBackgroundPatch,
  currentServiceValue,
  formatHotkey,
  getServiceOptions,
  parseServiceValue,
  resolveHudBackgroundCss,
} from "../lib/constants";
import type {
  AppConfig,
  LiveStatePayload,
  ReplaceCompletedPayload,
  SonioxStatePayload,
  StatusEvent,
} from "../types";

type MenuId = "screen" | "image" | "text" | "audio" | "lang" | "more" | null;

export function HudWindow() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [text, setText] = useState("");
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
  const [openMenu, setOpenMenu] = useState<MenuId>(null);
  const [pinned, setPinned] = useState(true);
  const [barHidden, setBarHidden] = useState(false);
  const [lastReplace, setLastReplace] = useState<ReplaceCompletedPayload | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const configRef = useRef<AppConfig | null>(null);
  const lastDownRef = useRef<{ t: number; x: number; y: number } | null>(null);
  const lastToggleRef = useRef<number>(0);

  useEffect(() => {
    configRef.current = config;
  }, [config]);

  useEffect(() => {
    document.documentElement.classList.add("transparent-window");
    document.body.classList.add("transparent-window");

    Promise.all([api.getConfig(), api.getLiveState(), api.getSonioxState()]).then(
      ([cfg, live, sx]) => {
        setConfig(cfg);
        setPinned(cfg.hud_pinned);
        setLiveState(live);
        setSonioxState(sx);
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        const resolved =
          cfg.ui_theme === "system" ? (prefersDark ? "dark" : "light") : cfg.ui_theme;
        document.documentElement.setAttribute("data-theme", resolved);
      }
    );

    const unlisteners = [
      api.onConfigUpdated((c) => {
        setConfig(c);
        setPinned(c.hud_pinned);
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        const resolved = c.ui_theme === "system" ? (prefersDark ? "dark" : "light") : c.ui_theme;
        document.documentElement.setAttribute("data-theme", resolved);
      }),
      api.onTranslationResult((entry) => setText(entry.translated)),
      api.onReplaceCompleted((payload) => setLastReplace(payload)),
      api.onStatus(setStatus),
      api.onLiveState(setLiveState),
      api.onSonioxState(setSonioxState),
      api.onHudShowBar(() => setBarHidden(false)),
    ];

    const onDown = (e: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenu(null);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);

    let saveGeoTimer: number | null = null;
    const scheduleSaveGeometry = () => {
      if (saveGeoTimer !== null) window.clearTimeout(saveGeoTimer);
      saveGeoTimer = window.setTimeout(async () => {
        const cur = configRef.current;
        if (!cur) return;
        try {
          const win = getCurrentWindow();
          const [pos, size, scale] = await Promise.all([
            win.outerPosition(),
            win.innerSize(),
            win.scaleFactor(),
          ]);
          const x = Math.round(pos.x / scale);
          const y = Math.round(pos.y / scale);
          const w = Math.round(size.width / scale);
          const h = Math.round(size.height / scale);
          if (w >= 400 && h >= 100) {
            await api.saveConfig({
              ...cur,
              hud_geometry: { x, y, w, h },
            });
          }
        } catch {
          // ignore
        }
      }, 450);
    };

    const win = getCurrentWindow();
    const unMove = win.onMoved(scheduleSaveGeometry);
    const unResize = win.onResized(scheduleSaveGeometry);

    return () => {
      document.documentElement.classList.remove("transparent-window");
      document.body.classList.remove("transparent-window");
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
      if (saveGeoTimer !== null) window.clearTimeout(saveGeoTimer);
      unMove.then((f) => f()).catch(() => {});
      unResize.then((f) => f()).catch(() => {});
      for (const p of unlisteners) {
        p.then((f) => f()).catch(() => {});
      }
    };
  }, []);

  const updateConfig = async (patch: Partial<AppConfig>) => {
    if (!config) return;
    const merged = { ...config, ...patch };
    setConfig(merged);
    await api.saveConfig(merged).catch(() => {});
  };

  const runAndClose = (fn: () => Promise<unknown> | void) => {
    setOpenMenu(null);
    Promise.resolve(fn()).catch((err) => {
      setStatus({ text: String(err), state: "error" });
    });
  };

  const togglePin = async () => {
    const next = !pinned;
    setPinned(next);
    await getCurrentWindow().setAlwaysOnTop(next);
    await updateConfig({ hud_pinned: next });
  };

  const toggleMenu = (id: MenuId) => setOpenMenu((cur) => (cur === id ? null : id));

  const isInteractiveTarget = (target: EventTarget | null): boolean =>
    Boolean(
      (target as HTMLElement | null)?.closest(
        "button, input, select, textarea, a, .hud-dropdown, .hud-pane-actions"
      )
    );

  const toggleBarSafely = () => {
    const now = Date.now();
    if (now - lastToggleRef.current < 220) return;
    lastToggleRef.current = now;
    lastDownRef.current = null;
    setOpenMenu(null);
    setBarHidden((prev) => !prev);
  };

  const handleDragAreaDoubleClick = (e: React.MouseEvent<HTMLElement>) => {
    if (isInteractiveTarget(e.target)) return;
    e.preventDefault();
    toggleBarSafely();
  };

  const handleDragAreaPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0 || isInteractiveTarget(e.target)) return;
    const now = Date.now();
    const prev = lastDownRef.current;
    if (
      e.detail >= 2 ||
      (prev && now - prev.t <= 420 && Math.hypot(e.screenX - prev.x, e.screenY - prev.y) <= 8)
    ) {
      e.preventDefault();
      toggleBarSafely();
      return;
    }
    lastDownRef.current = { t: now, x: e.screenX, y: e.screenY };
    const startX = e.screenX;
    const startY = e.screenY;
    const targetEl = e.currentTarget;
    const pointerId = e.pointerId;
    try {
      targetEl.setPointerCapture(pointerId);
    } catch {
      // ignore
    }
    const onMove = (ev: PointerEvent) => {
      if (Math.hypot(ev.screenX - startX, ev.screenY - startY) >= 4) {
        cleanup();
        lastDownRef.current = null;
        api.startWindowDrag().catch(() => {
          getCurrentWindow().startDragging().catch(() => {});
        });
      }
    };
    const cleanup = () => {
      try {
        if (targetEl.hasPointerCapture(pointerId)) {
          targetEl.releasePointerCapture(pointerId);
        }
      } catch {
        // ignore
      }
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  };

  const hk = (action: string): string => {
    const raw = config?.hotkeys?.[action]?.trim() || "";
    return raw ? formatHotkey(raw) : "";
  };

  const tip = (desc: string, action?: string): string => {
    const combo = action ? hk(action) : "";
    return combo ? `${desc} (${combo})` : desc;
  };

  const serviceOptions = config ? getServiceOptions(config) : [];
  const activeServiceVal = config ? currentServiceValue(config) : "google";
  const activeServiceShort =
    (serviceOptions.find((o) => o.value === activeServiceVal)?.label || "Google").split(" · ").pop() ||
    "Google";
  const activeTargetLabel =
    LANGUAGES.find(([, code]) => code === config?.target_language)?.[0] ||
    config?.target_language ||
    "vi";

  const audioActive = sonioxState.state !== "idle";
  const audioDisplayText = audioActive
    ? (config?.soniox_display_mode === "translation"
        ? sonioxState.blocks.filter((b) => b.kind === "translation")
        : sonioxState.blocks
      )
        .slice(-4)
        .map((b) => b.text)
        .join("\n")
    : "";

  const displayText = audioDisplayText || text;

  const bgCss = resolveHudBackgroundCss(config);
  const bgActive = Boolean(config && config.hud_background_enabled && !config.hud_frame_transparent);

  const textShadow = config
    ? [
        config.hud_border_width > 0
          ? `0 0 ${config.hud_border_width}px ${config.hud_border_color}, 1px 1px 0 ${config.hud_border_color}, -1px -1px 0 ${config.hud_border_color}, 1px -1px 0 ${config.hud_border_color}, -1px 1px 0 ${config.hud_border_color}`
          : "",
        config.hud_shadow_radius > 0
          ? `0 2px ${config.hud_shadow_radius}px ${argbHexToRgbaCss(config.hud_shadow_color)}`
          : "",
      ]
        .filter(Boolean)
        .join(", ")
    : undefined;

  return (
    <div className="hud-root">
      {!barHidden && (
        <div
          className="hud-bar"
          ref={barRef}
          onPointerDown={handleDragAreaPointerDown}
          onDoubleClick={handleDragAreaDoubleClick}
          title="Kéo để di chuyển · Nhấp đúp để ẩn thanh công cụ (giữ vùng dịch)"
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              color: "var(--text-muted)",
              cursor: "grab",
              flexShrink: 0,
              marginRight: 2,
            }}
            title="Kéo để di chuyển thanh HUD"
          >
            <GripVertical size={16} />
          </span>
          <img
            src="/icon.png"
            alt=""
            draggable={false}
            style={{ width: 16, height: 16, marginRight: 4, flexShrink: 0, cursor: "grab" }}
          />

        {/* Màn hình ▾ */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn ${openMenu === "screen" ? "open" : ""} ${liveState.running ? "active" : ""}`}
            onClick={() => toggleMenu("screen")}
            title="Chụp vùng màn hình (Overlay / Khung dịch) và quản lý Live đa vùng"
          >
            <Monitor size={16} />
            <span>{liveState.running ? `Live (${liveState.regions.length})` : "Màn hình"}</span>
            <ChevronDown size={16} />
          </button>
          {openMenu === "screen" && (
            <div className="hud-dropdown">
              <div className="hud-menu-section">Một lần</div>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Chọn vùng, dịch một lần và vẽ bản dịch đè lên chữ gốc", "region_to_overlay")}
                onClick={() => runAndClose(() => api.regionToOverlay())}
              >
                <Layers size={16} />
                <span>Overlay tại chỗ</span>
                {hk("region_to_overlay") && <span className="hud-menu-kbd">{hk("region_to_overlay")}</span>}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Chọn vùng, dịch một lần và đưa bản dịch vào khung", "region_to_text")}
                onClick={() => runAndClose(() => api.regionToText())}
              >
                <Camera size={16} />
                <span>Vào khung dịch</span>
                {hk("region_to_text") && <span className="hud-menu-kbd">{hk("region_to_text")}</span>}
              </button>
              <div className="hud-menu-sep" />
              <div className="hud-menu-section">
                Live ({liveState.regions.length}/12 vùng)
              </div>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Chọn thêm vùng live: dịch liên tục và vẽ đè tại chỗ", "region_to_live")}
                onClick={() => runAndClose(() => api.liveAddRegion("overlay"))}
              >
                <Layers size={16} />
                <span>Thêm vùng overlay</span>
                {hk("region_to_live") && <span className="hud-menu-kbd">{hk("region_to_live")}</span>}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Chọn thêm vùng live: hiện bản dịch trong khung nổi riêng", "region_to_live_frame")}
                onClick={() =>
                  runAndClose(async () => {
                    const added = await api.liveAddRegion("frame");
                    if (added) await api.openLiveOutputWindow(added.id, added.bbox);
                  })
                }
              >
                <AppWindow size={16} />
                <span>Thêm vùng vào khung</span>
                {hk("region_to_live_frame") && <span className="hud-menu-kbd">{hk("region_to_live_frame")}</span>}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Bắt đầu hoặc dừng dịch live trên mọi vùng đã thêm", "live_toggle")}
                onClick={() =>
                  runAndClose(() => (liveState.running ? api.liveStop() : api.liveStart()))
                }
              >
                {liveState.running ? <Square size={16} /> : <Play size={16} />}
                <span>{liveState.running ? "Dừng Live" : "Bắt đầu Live"}</span>
                {hk("live_toggle") && <span className="hud-menu-kbd">{hk("live_toggle")}</span>}
              </button>
              {liveState.running && (
                <button
                  type="button"
                  className="hud-menu-item"
                  title={tip("Ép OCR và dịch lại ngay mọi vùng live đang chạy", "live_rescan")}
                  onClick={() => runAndClose(() => api.liveRescan())}
                >
                  <Scan size={16} />
                  <span>Quét lại ngay</span>
                  {hk("live_rescan") && <span className="hud-menu-kbd">{hk("live_rescan")}</span>}
                </button>
              )}
              {liveState.regions.length > 0 && (
                <>
                  <div className="hud-menu-sep" />
                  <div className="hud-menu-section">Sửa nhanh vùng nhận diện</div>
                  {liveState.regions.map((r, idx) => (
                    <button
                      key={r.id}
                      type="button"
                      className="hud-menu-item"
                      title="Kéo di chuyển hoặc đổi cỡ trực tiếp vùng nhận diện này trên màn hình"
                      onClick={() => runAndClose(() => api.liveEditRegion(r.id))}
                    >
                      <Move size={16} />
                      <span>
                        Sửa vùng #{idx + 1} ({r.mode === "overlay" ? "Overlay" : "Khung"})
                      </span>
                    </button>
                  ))}
                </>
              )}
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                title="Xoá mọi lớp phủ overlay đang hiển thị trên màn hình"
                onClick={() => runAndClose(() => api.clearOverlays())}
              >
                <Eraser size={16} /> Xoá overlay đang hiện
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title="Mở bảng quản lý danh sách vùng Live và cài đặt trigger"
                onClick={() => runAndClose(() => api.openMainWindow("live"))}
              >
                <Settings size={16} /> Quản lý vùng Live…
              </button>
            </div>
          )}
        </div>

        {liveState.running && (
          <button
            type="button"
            className="hud-bar-btn danger"
            onClick={() =>
              runAndClose(async () => {
                const st = await api.liveStop();
                setLiveState(st);
              })
            }
            title={tip("Dừng dịch Live ngay lập tức", "live_toggle")}
            aria-label="Dừng Live"
          >
            <Square size={16} />
            <span>Dừng Live</span>
          </button>
        )}

        {/* Ảnh ▾ */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn ${openMenu === "image" ? "open" : ""}`}
            onClick={() => toggleMenu("image")}
            title="OCR và dịch ảnh đang có trong clipboard"
          >
            <ImageIcon size={16} />
            <span>Ảnh</span>
            <ChevronDown size={16} />
          </button>
          {openMenu === "image" && (
            <div className="hud-dropdown">
              <button
                type="button"
                className="hud-menu-item"
                title={tip("OCR, xoá chữ gốc và vẽ bản dịch đè lên ảnh clipboard", "clipboard_image_replace")}
                onClick={() => runAndClose(() => api.clipboardImageReplace())}
              >
                <ImageIcon size={16} />
                <span>Dịch ảnh clipboard</span>
                {hk("clipboard_image_replace") && (
                  <span className="hud-menu-kbd">{hk("clipboard_image_replace")}</span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("OCR ảnh clipboard rồi đưa bản dịch dạng chữ vào khung", "clipboard_image_to_text")}
                onClick={() => runAndClose(() => api.clipboardImageToText())}
              >
                <Clipboard size={16} />
                <span>Ảnh clipboard → khung</span>
                {hk("clipboard_image_to_text") && (
                  <span className="hud-menu-kbd">{hk("clipboard_image_to_text")}</span>
                )}
              </button>
            </div>
          )}
        </div>

        {/* Văn bản ▾ */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn ${openMenu === "text" ? "open" : ""}`}
            onClick={() => toggleMenu("text")}
            title="Dịch & thay thế đoạn đang bôi đen, dịch văn bản nhập hoặc tự dịch khi Copy"
          >
            <FileText size={16} />
            <span>Văn bản</span>
            <ChevronDown size={16} />
          </button>
          {openMenu === "text" && (
            <div className="hud-dropdown">
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Bôi đen văn bản rồi thay bằng bản dịch (dán đè tại chỗ)", "selected_text_replace")}
                onClick={() => runAndClose(() => api.selectedTextReplace())}
              >
                <Replace size={16} />
                <span>Dịch & thay thế tại chỗ</span>
                {hk("selected_text_replace") && (
                  <span className="hud-menu-kbd">{hk("selected_text_replace")}</span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Mở ô nhập nhanh để gõ hoặc dán văn bản cần dịch", "quick_translate")}
                onClick={() => runAndClose(() => api.openMainWindow("translate"))}
              >
                <PenLine size={16} />
                <span>Dịch văn bản nhập…</span>
                {hk("quick_translate") && <span className="hud-menu-kbd">{hk("quick_translate")}</span>}
              </button>
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                title={tip("Tự động dịch mọi văn bản khi bạn nhấn Ctrl+C", "toggle_auto_clipboard")}
                onClick={() =>
                  runAndClose(() =>
                    updateConfig({
                      auto_translate_clipboard: !config?.auto_translate_clipboard,
                    })
                  )
                }
              >
                <Clipboard size={16} />
                <span>Tự dịch khi Copy</span>
                {hk("toggle_auto_clipboard") && (
                  <span className="hud-menu-kbd">{hk("toggle_auto_clipboard")}</span>
                )}
                {config?.auto_translate_clipboard && (
                  <span className="hud-menu-check" style={{ marginLeft: 4 }}>
                    <Check size={16} />
                  </span>
                )}
              </button>
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                title="Mở tab Cài đặt riêng cho Dịch văn bản và Replace"
                onClick={() => runAndClose(() => api.openMainWindow("settings:text"))}
              >
                <Settings size={16} />
                <span>Cài đặt dịch văn bản…</span>
              </button>
            </div>
          )}
        </div>

        {/* Âm thanh ▾ */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn ${openMenu === "audio" ? "open" : ""} ${audioActive ? "active" : ""}`}
            onClick={() => toggleMenu("audio")}
            title="Dịch âm thanh hệ thống hoặc microphone realtime bằng Soniox"
          >
            <AudioLines size={16} />
            <span>Âm thanh</span>
            <ChevronDown size={16} />
          </button>
          {openMenu === "audio" && (
            <div className="hud-dropdown">
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => (audioActive ? api.sonioxStop() : api.sonioxStart()))
                }
              >
                {audioActive ? <Square size={16} /> : <Play size={16} />}
                {audioActive ? "Dừng dịch audio" : "Bắt đầu dịch audio"}
              </button>
              <div className="hud-menu-sep" />
              <div className="hud-menu-section">Nguồn âm thanh</div>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() => runAndClose(() => updateConfig({ soniox_audio_source: "system" }))}
              >
                <Volume2 size={16} /> Âm thanh hệ thống
                {config?.soniox_audio_source === "system" && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => updateConfig({ soniox_audio_source: "microphone" }))
                }
              >
                <Mic size={16} /> Microphone
                {config?.soniox_audio_source === "microphone" && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <div className="hud-menu-sep" />
              <div className="hud-menu-section">Hiển thị</div>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => updateConfig({ soniox_display_mode: "bilingual" }))
                }
              >
                Song ngữ
                {config?.soniox_display_mode === "bilingual" && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => updateConfig({ soniox_display_mode: "translation" }))
                }
              >
                Chỉ bản dịch
                {config?.soniox_display_mode === "translation" && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                onClick={() => runAndClose(() => api.openMainWindow("audio"))}
              >
                <Settings size={16} /> Cài đặt Audio…
              </button>
            </div>
          )}
        </div>

        <span className="hud-divider" />

        {/* Status strip */}
        <span
          className="titlebar-status"
          style={{ flex: 1, marginLeft: 2, marginRight: 4, cursor: "move" }}
          title="Kéo để di chuyển · Nhấp đúp để ẩn thanh công cụ (giữ vùng dịch)"
        >
          <span className={`status-dot ${status.state}`} />
          <span>{status.text}</span>
        </span>

        {/* Dịch vụ → Ngôn ngữ ▾ */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn chip ${openMenu === "lang" ? "open" : ""}`}
            onClick={() => toggleMenu("lang")}
            title="Chọn dịch vụ dịch và ngôn ngữ đích"
          >
            <Languages size={16} style={{ flexShrink: 0 }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {activeServiceShort} → {activeTargetLabel}
            </span>
            <ChevronDown size={16} style={{ flexShrink: 0 }} />
          </button>
          {openMenu === "lang" && (
            <div className="hud-dropdown align-right">
              <div className="hud-menu-section">Dịch vụ</div>
              {serviceOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className="hud-menu-item"
                  onClick={() =>
                    runAndClose(() => {
                      const parsed = parseServiceValue(opt.value);
                      return updateConfig({
                        translator: parsed.translator,
                        ...(parsed.llm_model ? { llm_model: parsed.llm_model } : {}),
                      });
                    })
                  }
                >
                  <span>{opt.label}</span>
                  {opt.value === activeServiceVal && (
                    <span className="hud-menu-check">
                      <Check size={16} />
                    </span>
                  )}
                </button>
              ))}
              <div className="hud-menu-sep" />
              <div className="hud-menu-section">Ngôn ngữ đích</div>
              {LANGUAGES.map(([label, code]) => (
                <button
                  key={code}
                  type="button"
                  className="hud-menu-item"
                  onClick={() => runAndClose(() => updateConfig({ target_language: code }))}
                >
                  <span>{label}</span>
                  {code === config?.target_language && (
                    <span className="hud-menu-check">
                      <Check size={16} />
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Ghim */}
        <button
          type="button"
          className={`hud-bar-btn icon-only ${pinned ? "active" : ""}`}
          onClick={togglePin}
          title={pinned ? "Đang ghim trên cùng (bấm để bỏ ghim)" : "Ghim luôn nổi trên cùng"}
          aria-label="Ghim khung dịch"
        >
          <Pin size={16} />
        </button>

        {/* ⋯ Thêm */}
        <div className="hud-menu-wrap">
          <button
            type="button"
            className={`hud-bar-btn icon-only ${openMenu === "more" ? "open" : ""}`}
            onClick={() => toggleMenu("more")}
            title="Thêm tuỳ chọn & Cài đặt"
            aria-label="Thêm"
          >
            <MoreHorizontal size={16} />
          </button>
          {openMenu === "more" && (
            <div className="hud-dropdown align-right">
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => (displayText.trim() ? api.copyText(displayText) : undefined))
                }
              >
                <Copy size={16} /> Sao chép bản dịch
              </button>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() =>
                  runAndClose(() => {
                    setText("");
                    if (audioActive) return api.sonioxClear();
                  })
                }
              >
                <Trash2 size={16} /> Xoá khung dịch
              </button>
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                title={
                  bgActive
                    ? "Nền khung dịch: BẬT · Bấm để tắt nền hộp"
                    : "Nền khung dịch: TẮT · Bấm để bật nền hộp phía sau chữ"
                }
                onClick={() =>
                  runAndClose(() =>
                    config ? updateConfig(buildHudBackgroundPatch(config, !bgActive)) : undefined
                  )
                }
              >
                Nền khung dịch
                {bgActive && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title="Buộc khung dịch trong suốt hoàn toàn, bỏ qua màu nền"
                onClick={() =>
                  runAndClose(() =>
                    updateConfig({ hud_frame_transparent: !config?.hud_frame_transparent })
                  )
                }
              >
                Khung trong suốt
                {config?.hud_frame_transparent && (
                  <span className="hud-menu-check">
                    <Check size={16} />
                  </span>
                )}
              </button>
              <button
                type="button"
                className="hud-menu-item"
                title="Ẩn thanh công cụ, giữ lại khung dịch (nhấp đúp khung dịch để hiện lại)"
                onClick={() => {
                  setOpenMenu(null);
                  setBarHidden(true);
                }}
              >
                <PanelTopClose size={16} />
                <span>Ẩn thanh công cụ</span>
                <span className="hud-menu-kbd">Nhấp đúp</span>
              </button>
              <div className="hud-menu-sep" />
              <button
                type="button"
                className="hud-menu-item"
                onClick={() => runAndClose(() => api.openMainWindow("settings"))}
              >
                <Settings size={16} /> Cài đặt / Bảng điều khiển…
              </button>
              <button
                type="button"
                className="hud-menu-item"
                onClick={() => runAndClose(() => api.toggleHudWindow())}
              >
                <EyeOff size={16} /> Ẩn HUD
              </button>
              <button
                type="button"
                className="hud-menu-item danger"
                title={tip("Đóng hoàn toàn Translator2k", "quit")}
                onClick={() => runAndClose(() => api.quitApp())}
              >
                <Power size={16} />
                <span>Thoát ứng dụng</span>
                {hk("quit") && <span className="hud-menu-kbd">{hk("quit")}</span>}
              </button>
            </div>
          )}
        </div>
      </div>
      )}

      {/* Replace undo-original strip */}
      {lastReplace && config?.replace_show_undo_original && (
        <div className="hud-undo-bar">
          <RotateCcw size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
          <span className="hud-undo-text" title={lastReplace.original}>
            Bản gốc: {lastReplace.original}
          </span>
          <button
            type="button"
            className="hud-bar-btn"
            style={{ height: 22, padding: "0 6px", fontSize: 11.5 }}
            onClick={() => {
              api.copyText(lastReplace.original).catch(() => {});
              setStatus({ text: "Đã sao chép bản gốc để hoàn tác", state: "ready" });
            }}
            title="Sao chép bản gốc để dán lại / hoàn tác"
          >
            <Copy size={14} />
            Chép gốc
          </button>
          <button
            type="button"
            className="hud-bar-btn icon-only"
            style={{ height: 22, width: 22 }}
            onClick={() => setLastReplace(null)}
            title="Đóng"
            aria-label="Đóng thanh bản gốc"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Transparent translation output pane */}
      <div
        className={`hud-pane ${bgActive ? "has-bg" : ""} ${barHidden ? "bar-hidden" : ""}`}
        onPointerDown={handleDragAreaPointerDown}
        onDoubleClick={handleDragAreaDoubleClick}
        title={barHidden ? "Kéo để di chuyển · Nhấp đúp để hiện lại thanh công cụ" : undefined}
        style={{
          background: barHidden && !bgActive ? "rgba(0, 0, 0, 0.01)" : bgCss,
          alignItems:
            config?.hud_text_valign === "top"
              ? "flex-start"
              : config?.hud_text_valign === "bottom"
                ? "flex-end"
                : "center",
          justifyContent:
            config?.hud_text_align === "left"
              ? "flex-start"
              : config?.hud_text_align === "right"
                ? "flex-end"
                : "center",
        }}
      >
        {displayText && (
          <div className="hud-pane-actions">
            <button
              type="button"
              className="ui-btn ui-btn-secondary ui-btn-icon"
              style={{ height: 26, width: 26 }}
              onClick={() => api.copyText(displayText)}
              title="Sao chép bản dịch"
            >
              <Copy size={16} />
            </button>
            <button
              type="button"
              className="ui-btn ui-btn-secondary ui-btn-icon"
              style={{ height: 26, width: 26 }}
              onClick={() => {
                setText("");
                if (audioActive) api.sonioxClear().catch(() => {});
              }}
              title="Xoá khung dịch"
            >
              <X size={16} />
            </button>
          </div>
        )}
        <div
          className="selectable-text"
          style={{
            fontFamily: config
              ? `"${config.hud_font_family}", var(--font-sans)`
              : "var(--font-sans)",
            fontSize: config?.hud_font_size ?? 22,
            color: config?.hud_text_color ?? "#ffffff",
            textAlign: config?.hud_text_align ?? "center",
            textShadow,
            fontWeight: 600,
            whiteSpace: "pre-wrap",
          }}
        >
          {displayText}
        </div>
      </div>
    </div>
  );
}
