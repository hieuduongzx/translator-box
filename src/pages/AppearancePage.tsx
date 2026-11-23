import { useState } from "react";
import { Palette, RotateCcw } from "lucide-react";
import { Button, Card, ConfirmDialog, Switch } from "../components/ui";
import type { ToastKind } from "../hooks";
import {
  HUD_FONT_OPTIONS,
  HUD_STYLE_PRESETS,
  argbHexToRgbaCss,
  argbToColorAndAlpha,
  buildHudBackgroundPatch,
  colorAndAlphaToArgb,
  resolveHudBackgroundCss,
} from "../lib/constants";
import type { AppConfig } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onToast: (message: string, kind?: ToastKind) => void;
}

export function AppearancePage({ config, onUpdateConfig, onToast: toast }: Props) {
  const [confirmReset, setConfirmReset] = useState(false);

  const bgCss = resolveHudBackgroundCss(config);
  const bgParts = argbToColorAndAlpha(config.hud_background_color);

  const alignItems =
    config.hud_text_valign === "top"
      ? "flex-start"
      : config.hud_text_valign === "bottom"
        ? "flex-end"
        : "center";

  const justifyContent =
    config.hud_text_align === "left"
      ? "flex-start"
      : config.hud_text_align === "right"
        ? "flex-end"
        : "center";

  const textShadow = [
    config.hud_border_width > 0
      ? `0 0 ${config.hud_border_width}px ${config.hud_border_color}, 1px 1px 0 ${config.hud_border_color}, -1px -1px 0 ${config.hud_border_color}, 1px -1px 0 ${config.hud_border_color}, -1px 1px 0 ${config.hud_border_color}`
      : "",
    config.hud_shadow_radius > 0
      ? `0 2px ${config.hud_shadow_radius}px ${argbHexToRgbaCss(config.hud_shadow_color)}`
      : "",
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Palette size={24} />
            </span>
            <h1 className="page-title">Kiểu chữ khung dịch nổi</h1>
          </div>
          <p className="page-subtitle">
            Tuỳ chỉnh giao diện chữ và nền cho cửa sổ HUD nổi cùng các khung dịch Live.
          </p>
        </div>
        <div className="page-header-actions">
          <Button variant="secondary" onClick={() => setConfirmReset(true)}>
            <RotateCcw size={16} />
            Đặt lại mặc định
          </Button>
        </div>
      </div>

      <Card title="Xem trước trực tiếp">
        <div
          className="checker-preview"
          style={{ alignItems, justifyContent }}
        >
          <div
            style={{
              background: bgCss,
              padding: "8px 14px",
              borderRadius: "var(--radius)",
              fontFamily: `"${config.hud_font_family}", var(--font-sans)`,
              fontSize: config.hud_font_size,
              color: config.hud_text_color,
              textAlign: config.hud_text_align,
              textShadow: textShadow || undefined,
              fontWeight: 600,
              lineHeight: 1.4,
            }}
          >
            Xin chào · Hello · こんにちは
          </div>
        </div>
      </Card>

      <Card title="Bộ kiểu dựng sẵn">
        <div className="grid-4">
          {HUD_STYLE_PRESETS.map((preset) => {
            const isSelected =
              config.hud_text_color.toLowerCase() ===
                (preset.values.hud_text_color ?? "").toLowerCase() &&
              config.hud_background_enabled === preset.values.hud_background_enabled &&
              config.hud_border_width === preset.values.hud_border_width;
            return (
              <button
                key={preset.id}
                type="button"
                className={`preset-card ${isSelected ? "selected" : ""}`}
                onClick={async () => {
                  await onUpdateConfig({
                    ...preset.values,
                    hud_frame_transparent: false,
                  });
                  toast(`Đã áp dụng kiểu "${preset.name}"`, "success");
                }}
              >
                <strong style={{ color: "var(--text)" }}>{preset.name}</strong>
                <span className="field-hint">{preset.desc}</span>
              </button>
            );
          })}
        </div>
      </Card>

      <Card title="Chi tiết chữ & nền">
        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Phông chữ</span>
          </div>
          <select
            className="ui-select"
            value={config.hud_font_family}
            onChange={(e) => onUpdateConfig({ hud_font_family: e.target.value })}
          >
            {HUD_FONT_OPTIONS.map(([fam, cov]) => (
              <option key={fam} value={fam}>
                {fam} ({cov})
              </option>
            ))}
          </select>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Cỡ chữ (px)</span>
          </div>
          <input
            type="number"
            className="ui-input"
            style={{ width: 100 }}
            min={10}
            max={72}
            value={config.hud_font_size}
            onChange={(e) => onUpdateConfig({ hud_font_size: Number(e.target.value) || 22 })}
          />
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Màu chữ &amp; Màu viền</span>
          </div>
          <div className="field-control">
            <label className="row-8 field-hint">
              Chữ
              <input
                type="color"
                className="ui-color"
                value={config.hud_text_color}
                onChange={(e) => onUpdateConfig({ hud_text_color: e.target.value })}
              />
            </label>
            <label className="row-8 field-hint">
              Viền
              <input
                type="color"
                className="ui-color"
                value={config.hud_border_color}
                onChange={(e) => onUpdateConfig({ hud_border_color: e.target.value })}
              />
            </label>
            <label className="row-8 field-hint">
              Độ dày viền
              <input
                type="number"
                className="ui-input"
                style={{ width: 80 }}
                min={0}
                max={8}
                step={0.2}
                value={config.hud_border_width}
                onChange={(e) => onUpdateConfig({ hud_border_width: Number(e.target.value) || 0 })}
              />
            </label>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Căn lề văn bản</span>
          </div>
          <div className="row-8">
            <select
              className="ui-select"
              value={config.hud_text_align}
              onChange={(e) =>
                onUpdateConfig({ hud_text_align: e.target.value as AppConfig["hud_text_align"] })
              }
            >
              <option value="left">Trái</option>
              <option value="center">Giữa</option>
              <option value="right">Phải</option>
            </select>
            <select
              className="ui-select"
              value={config.hud_text_valign}
              onChange={(e) =>
                onUpdateConfig({ hud_text_valign: e.target.value as AppConfig["hud_text_valign"] })
              }
            >
              <option value="top">Trên</option>
              <option value="center">Giữa dọc</option>
              <option value="bottom">Dưới</option>
            </select>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Hiển thị nền hộp phía sau chữ</span>
            <span className="field-hint">Tắt để chữ nổi trong suốt kiểu phụ đề phim.</span>
          </div>
          <Switch
            checked={config.hud_background_enabled && !config.hud_frame_transparent}
            onChange={(v) => onUpdateConfig(buildHudBackgroundPatch(config, v))}
          />
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Màu &amp; độ mờ nền khung dịch</span>
            <span className="field-hint">Áp dụng khi bật nền hộp phía sau chữ trên HUD và khung Live.</span>
          </div>
          <div className="field-control">
            <label className="row-8 field-hint">
              Màu nền
              <input
                type="color"
                className="ui-color"
                value={bgParts.hex}
                onChange={(e) =>
                  onUpdateConfig({
                    hud_background_color: colorAndAlphaToArgb(e.target.value, bgParts.opacity),
                    hud_background_enabled: true,
                    hud_frame_transparent: false,
                  })
                }
              />
            </label>
            <label className="row-8 field-hint">
              Độ mờ ({bgParts.opacity}%)
              <input
                type="range"
                className="ui-range"
                min={10}
                max={100}
                step={5}
                value={bgParts.opacity}
                onChange={(e) =>
                  onUpdateConfig({
                    hud_background_color: colorAndAlphaToArgb(bgParts.hex, Number(e.target.value)),
                    hud_background_enabled: true,
                    hud_frame_transparent: false,
                  })
                }
              />
            </label>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Khung trong suốt hoàn toàn</span>
            <span className="field-hint">Tạm bỏ nền hộp bất kể màu nền đang chọn.</span>
          </div>
          <Switch
            checked={config.hud_frame_transparent}
            onChange={(v) => onUpdateConfig({ hud_frame_transparent: v })}
          />
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Ghim HUD luôn nổi trên cùng</span>
          </div>
          <Switch
            checked={config.hud_pinned}
            onChange={(v) => onUpdateConfig({ hud_pinned: v })}
          />
        </div>
      </Card>

      <ConfirmDialog
        open={confirmReset}
        title="Đặt lại kiểu chữ khung dịch về mặc định?"
        message="Các tuỳ chỉnh màu sắc, cỡ chữ và nền sẽ trở về bộ 'Phụ đề phim'."
        confirmLabel="Đặt lại"
        confirmVariant="primary"
        onCancel={() => setConfirmReset(false)}
        onConfirm={async () => {
          await onUpdateConfig({
            ...HUD_STYLE_PRESETS[0].values,
            hud_text_align: "center",
            hud_text_valign: "center",
          });
          setConfirmReset(false);
          toast("Đã khôi phục kiểu chữ mặc định", "success");
        }}
      />
    </div>
  );
}
