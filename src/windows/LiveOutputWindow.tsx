import { useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Check, Copy, GripVertical, Move, Play, Scan, Square, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import {
  argbHexToRgbaCss,
  buildHudBackgroundPatch,
  resolveHudBackgroundCss,
} from "../lib/constants";
import type { AppConfig, LiveStatePayload } from "../types";

export function LiveOutputWindow({ regionId }: { regionId: number }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [liveState, setLiveState] = useState<LiveStatePayload>({
    running: false,
    paused_by_focus: false,
    regions: [],
  });
  const [text, setText] = useState("");
  const [label, setLabel] = useState(`Vùng #${regionId}`);
  const [barHidden, setBarHidden] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const lastDownRef = useRef<{ t: number; x: number; y: number } | null>(null);
  const lastToggleRef = useRef<number>(0);

  useEffect(() => {
    document.documentElement.classList.add("transparent-window");
    document.body.classList.add("transparent-window");

    const applyTheme = (c: AppConfig) => {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const resolved = c.ui_theme === "system" ? (prefersDark ? "dark" : "light") : c.ui_theme;
      document.documentElement.setAttribute("data-theme", resolved);
    };

    const syncLive = (st: LiveStatePayload) => {
      setLiveState(st);
      const idx = st.regions.findIndex((r) => r.id === regionId);
      if (idx >= 0) {
        setLabel(`#${idx + 1} · Khung`);
        if (st.regions[idx].last_text) {
          setText((cur) => cur || st.regions[idx].last_text);
        }
      }
    };

    Promise.all([api.getConfig(), api.getLiveState()]).then(([cfg, st]) => {
      setConfig(cfg);
      applyTheme(cfg);
      syncLive(st);
    });

    const unlisteners = [
      api.onConfigUpdated((c) => {
        setConfig(c);
        applyTheme(c);
      }),
      api.onLiveState(syncLive),
      api.onLiveFrameText((upd) => {
        if (upd.region_id === regionId) {
          setText(upd.text);
          setLabel(`#${upd.number} · Khung`);
        }
      }),
    ];

    return () => {
      document.documentElement.classList.remove("transparent-window");
      document.body.classList.remove("transparent-window");
      for (const p of unlisteners) {
        p.then((f) => f()).catch(() => {});
      }
    };
  }, [regionId]);

  const isInteractiveTarget = (target: EventTarget | null): boolean =>
    Boolean((target as HTMLElement | null)?.closest("button, input, select, textarea, a"));

  const toggleBarSafely = () => {
    const now = Date.now();
    if (now - lastToggleRef.current < 220) return;
    lastToggleRef.current = now;
    lastDownRef.current = null;
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

  const handleEditRegion = async () => {
    if (editing) return;
    setEditing(true);
    try {
      const st = await api.liveEditRegion(regionId);
      setLiveState(st);
    } catch {
      // ignore cancel
    } finally {
      setEditing(false);
    }
  };

  const handleToggleLive = async () => {
    try {
      const st = liveState.running ? await api.liveStop() : await api.liveStart();
      setLiveState(st);
    } catch {
      // ignore
    }
  };

  const handleCopy = async () => {
    if (!text.trim()) return;
    await api.copyText(text).catch(() => {});
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  const handleToggleBg = async () => {
    if (!config) return;
    const next = { ...config, ...buildHudBackgroundPatch(config, !bgActive) };
    setConfig(next);
    await api.saveConfig(next).catch(() => {});
  };

  const handleRemoveRegion = async () => {
    await api.liveRemoveRegion(regionId).catch(() => {});
    await getCurrentWindow().close().catch(() => {});
  };

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
          style={{ height: 32, minHeight: 32, cursor: "grab" }}
          onPointerDown={handleDragAreaPointerDown}
          onDoubleClick={handleDragAreaDoubleClick}
          title="Kéo để di chuyển · Nhấp đúp để ẩn/hiện thanh công cụ"
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
            title="Kéo để di chuyển khung Live"
          >
            <GripVertical size={16} />
          </span>
          <span
            className={`status-dot ${liveState.running ? (liveState.paused_by_focus ? "busy" : "ready") : ""}`}
            style={{
              background: liveState.running
                ? liveState.paused_by_focus
                  ? "var(--warning)"
                  : "var(--success)"
                : "var(--text-muted)",
              marginRight: 4,
            }}
          />
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap" }}>
            {label}
          </span>

          <span className="hud-divider" />

          <button
            type="button"
            className={`hud-bar-btn ${editing ? "active" : ""}`}
            onClick={handleEditRegion}
            disabled={editing}
            title="Kéo di chuyển hoặc đổi cỡ vùng nhận diện Live này trên màn hình"
          >
            <Move size={16} />
            <span>{editing ? "Đang sửa…" : "Sửa vùng"}</span>
          </button>

          <button
            type="button"
            className={`hud-bar-btn ${liveState.running ? "danger" : ""}`}
            onClick={handleToggleLive}
            title={liveState.running ? "Dừng dịch Live ngay" : "Bắt đầu dịch Live"}
          >
            {liveState.running ? <Square size={16} /> : <Play size={16} />}
            <span>{liveState.running ? "Dừng" : "Chạy"}</span>
          </button>

          {liveState.running && (
            <button
              type="button"
              className="hud-bar-btn icon-only"
              onClick={() => api.liveRescan().catch(() => {})}
              title="Quét lại ngay vùng Live"
              aria-label="Quét lại ngay"
            >
              <Scan size={16} />
            </button>
          )}

          <span style={{ flex: 1 }} />

          <button
            type="button"
            className={`hud-bar-btn ${bgActive ? "active" : ""}`}
            onClick={handleToggleBg}
            title={bgActive ? "Tắt nền khung dịch" : "Bật nền khung dịch"}
          >
            <span>Nền</span>
          </button>

          {text.trim() && (
            <button
              type="button"
              className="hud-bar-btn icon-only"
              onClick={handleCopy}
              title={copied ? "Đã sao chép!" : "Sao chép bản dịch"}
              aria-label="Sao chép bản dịch"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
          )}

          <button
            type="button"
            className="hud-bar-btn icon-only"
            onClick={handleRemoveRegion}
            title="Xoá hẳn vùng Live này"
            aria-label="Xoá vùng Live"
            style={{ color: "var(--danger)" }}
          >
            <Trash2 size={16} />
          </button>

          <button
            type="button"
            className="hud-bar-btn icon-only"
            onClick={() => getCurrentWindow().close()}
            title="Ẩn khung này (vẫn giữ vùng Live)"
            aria-label="Ẩn khung"
          >
            <X size={16} />
          </button>
        </div>
      )}
      <div
        className={`hud-pane ${bgActive ? "has-bg" : ""} ${barHidden ? "bar-hidden" : ""}`}
        onPointerDown={handleDragAreaPointerDown}
        onDoubleClick={handleDragAreaDoubleClick}
        title={barHidden ? "Kéo để di chuyển · Nhấp đúp để hiện thanh công cụ" : undefined}
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
        <div
          className="selectable-text"
          style={{
            fontFamily: config ? `"${config.hud_font_family}", var(--font-sans)` : "var(--font-sans)",
            fontSize: config?.hud_font_size ?? 20,
            color: config?.hud_text_color ?? "#ffffff",
            textAlign: config?.hud_text_align ?? "center",
            textShadow,
            fontWeight: 600,
            whiteSpace: "pre-wrap",
          }}
        >
          {text || "Đang chờ chữ từ vùng Live…"}
        </div>
      </div>
    </div>
  );
}
