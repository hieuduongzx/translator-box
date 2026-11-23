import { useEffect } from "react";
import {
  ArrowLeftRight,
  AudioLines,
  Copy,
  Mic,
  Play,
  RefreshCw,
  Square,
  Trash2,
  Volume2,
} from "lucide-react";
import { Button, Card, Switch } from "../components/ui";
import type { ToastKind } from "../hooks";
import { api } from "../lib/api";
import { SONIOX_LANGUAGES } from "../lib/constants";
import { appActions, useAppSlice } from "../store/appStore";
import type { AppConfig } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onToast: (message: string, kind?: ToastKind) => void;
}

const STATE_LABELS: Record<string, { text: string; tone: string }> = {
  idle: { text: "Sẵn sàng", tone: "" },
  connecting: { text: "Đang kết nối Soniox…", tone: "warning" },
  listening: { text: "Đang lắng nghe & dịch", tone: "success" },
  reconnecting: { text: "Đang nối lại…", tone: "warning" },
  standby: { text: "Chờ có tiếng (tiết kiệm chi phí)", tone: "accent" },
  stopping: { text: "Đang dừng…", tone: "warning" },
};

export function AudioPage({ config, onUpdateConfig, onToast: toast }: Props) {
  const { sonioxState, micDevices, sysDevices, loadingDevices, toggling } = useAppSlice("audio");

  useEffect(() => {
    void appActions.loadAudioDevices();
  }, []);

  const isActive = sonioxState.state !== "idle";
  const badgeInfo = STATE_LABELS[sonioxState.state] || STATE_LABELS.idle;

  const visibleBlocks =
    config.soniox_display_mode === "translation"
      ? sonioxState.blocks.filter((b) => b.kind === "translation")
      : sonioxState.blocks;

  const copyTranscript = async () => {
    const text = visibleBlocks.map((b) => b.text).join("\n");
    if (!text.trim()) return;
    await api.copyText(text);
    toast("Đã sao chép toàn bộ bản ghi âm thanh", "success");
  };

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <AudioLines size={24} />
            </span>
            <h1 className="page-title">Dịch âm thanh trực tiếp (Soniox)</h1>
          </div>
          <p className="page-subtitle">
            Thu âm thanh hệ thống (WASAPI loopback) hoặc micro và dịch trực tiếp bằng Soniox stt-rt-v6.
          </p>
        </div>
        <div className="page-header-actions">
          <span className={`badge ${badgeInfo.tone}`}>{badgeInfo.text}</span>
          <Button
            variant={isActive ? "danger" : "primary"}
            disabled={
              toggling || sonioxState.state === "connecting" || sonioxState.state === "stopping"
            }
            onClick={() => void appActions.toggleSoniox()}
          >
            {isActive ? <Square size={16} /> : <Play size={16} />}
            {isActive ? "Dừng dịch âm thanh" : "Bắt đầu nghe"}
          </Button>
        </div>
      </div>

      {sonioxState.error && (
        <Card>
          <span style={{ color: "var(--danger)", fontWeight: 500 }}>{sonioxState.error}</span>
        </Card>
      )}

      <Card
        title="Bản ghi trực tiếp"
        headerRight={
          <div className="row-8">
            <Button variant="secondary" disabled={visibleBlocks.length === 0} onClick={copyTranscript}>
              <Copy size={16} />
              Sao chép
            </Button>
            <Button
              variant="ghost"
              disabled={sonioxState.blocks.length === 0}
              onClick={() => void appActions.clearSoniox()}
            >
              <Trash2 size={16} />
              Xoá
            </Button>
          </div>
        }
      >
        <div
          className="selectable-text"
          style={{
            minHeight: 160,
            maxHeight: 280,
            overflowY: "auto",
            padding: 12,
            borderRadius: "var(--radius)",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            textAlign: config.soniox_text_alignment,
          }}
        >
          {visibleBlocks.length === 0 ? (
            <div className="empty-state" style={{ border: "none", background: "transparent" }}>
              <AudioLines size={20} />
              <span>
                Chưa có nội dung âm thanh. Nhấn &ldquo;Bắt đầu nghe&rdquo; để dịch video, cuộc họp hoặc giọng nói trực tiếp.
              </span>
            </div>
          ) : (
            <div className="stack-8">
              {visibleBlocks.map((b, i) => (
                <div
                  key={i}
                  style={{
                    opacity: b.is_final ? 1 : 0.72,
                    color: b.kind === "translation" ? "var(--text)" : "var(--text-muted)",
                    fontWeight: b.kind === "translation" ? 500 : 400,
                  }}
                >
                  {b.speaker && <span className="badge" style={{ marginRight: 6 }}>Người {b.speaker}</span>}
                  {b.language && <span className="kbd" style={{ marginRight: 6 }}>{b.language}</span>}
                  <span>{b.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Cấu hình Soniox & Thiết bị âm thanh"
        headerRight={
          <Button
            variant="secondary"
            disabled={loadingDevices}
            onClick={() => void appActions.loadAudioDevices(true)}
          >
            <RefreshCw size={16} className={loadingDevices ? "spin" : undefined} />
            {loadingDevices ? "Đang quét…" : "Quét thiết bị"}
          </Button>
        }
      >
        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Khóa API Soniox</span>
            <span className="field-hint">
              Gửi qua header Authorization: Bearer theo chuẩn bảo mật Soniox v6.
            </span>
          </div>
          <div className="field-control">
            <input
              type="password"
              className="ui-input"
              style={{ width: 260 }}
              placeholder="Nhập Soniox API key…"
              value={config.soniox_api_key}
              onChange={(e) => onUpdateConfig({ soniox_api_key: e.target.value })}
            />
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Nguồn âm thanh</span>
            <span className="field-hint">Chọn thu âm thanh phát ra loa hoặc thu từ micro.</span>
          </div>
          <div className="segmented">
            <Button
              variant={config.soniox_audio_source === "system" ? "primary" : "secondary"}
              onClick={() => onUpdateConfig({ soniox_audio_source: "system" })}
            >
              <Volume2 size={16} />
              Âm thanh hệ thống
            </Button>
            <Button
              variant={config.soniox_audio_source === "microphone" ? "primary" : "secondary"}
              onClick={() => onUpdateConfig({ soniox_audio_source: "microphone" })}
            >
              <Mic size={16} />
              Micro
            </Button>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">
              {config.soniox_audio_source === "system"
                ? "Thiết bị phát (WASAPI Loopback)"
                : "Thiết bị Micro"}
            </span>
          </div>
          <div className="field-control">
            <select
              className="ui-select"
              style={{ width: 260 }}
              value={
                config.soniox_audio_source === "system"
                  ? config.soniox_system_device
                  : config.soniox_input_device
              }
              onChange={(e) =>
                config.soniox_audio_source === "system"
                  ? onUpdateConfig({ soniox_system_device: e.target.value })
                  : onUpdateConfig({ soniox_input_device: e.target.value })
              }
            >
              {(config.soniox_audio_source === "system" ? sysDevices : micDevices).map((d) => (
                <option key={d.id || "default"} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Chế độ dịch</span>
            <span className="field-hint">Một chiều (mọi ngôn ngữ → đích) hoặc Hai chiều (đối thoại 2 ngôn ngữ).</span>
          </div>
          <div className="row-8">
            <select
              className="ui-select"
              value={config.soniox_translation_mode}
              onChange={(e) =>
                onUpdateConfig({
                  soniox_translation_mode: e.target.value as AppConfig["soniox_translation_mode"],
                })
              }
            >
              <option value="one_way">Dịch một chiều</option>
              <option value="two_way">Dịch hai chiều</option>
            </select>

            {config.soniox_translation_mode === "one_way" ? (
              <select
                className="ui-select"
                value={config.soniox_target_language}
                onChange={(e) => onUpdateConfig({ soniox_target_language: e.target.value })}
              >
                {SONIOX_LANGUAGES.map(([label, code]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            ) : (
              <>
                <select
                  className="ui-select"
                  value={config.soniox_language_a}
                  onChange={(e) => onUpdateConfig({ soniox_language_a: e.target.value })}
                >
                  {SONIOX_LANGUAGES.map(([label, code]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
                <ArrowLeftRight size={16} />
                <select
                  className="ui-select"
                  value={config.soniox_language_b}
                  onChange={(e) => onUpdateConfig({ soniox_language_b: e.target.value })}
                >
                  {SONIOX_LANGUAGES.map(([label, code]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Hiển thị song ngữ</span>
            <span className="field-hint">Hiện cả lời gốc và bản dịch, hoặc chỉ bản dịch.</span>
          </div>
          <select
            className="ui-select"
            value={config.soniox_display_mode}
            onChange={(e) =>
              onUpdateConfig({
                soniox_display_mode: e.target.value as AppConfig["soniox_display_mode"],
              })
            }
          >
            <option value="bilingual">Song ngữ (Gốc + Dịch)</option>
            <option value="translation">Chỉ bản dịch</option>
          </select>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Tách từng người nói</span>
            <span className="field-hint">Gắn nhãn Người 1, Người 2 trong cuộc họp hoặc phim.</span>
          </div>
          <Switch
            checked={config.soniox_speaker_diarization}
            onChange={(v) => onUpdateConfig({ soniox_speaker_diarization: v })}
          />
        </div>

        <div className="stack-8" style={{ paddingTop: 12 }}>
          <span className="field-label">Ngữ cảnh &amp; thuật ngữ ưu tiên (tuỳ chọn)</span>
          <input
            type="text"
            className="ui-input"
            placeholder="Mô tả chủ đề (vd: Họp kỹ thuật Rust/Tauri, game RPG…)"
            value={config.soniox_context_text}
            onChange={(e) => onUpdateConfig({ soniox_context_text: e.target.value })}
          />
          <input
            type="text"
            className="ui-input"
            placeholder="Thuật ngữ cách nhau bằng dấu phẩy (hỗ trợ: Gojo => Gojo, Hollow Purple => Tử Thức)"
            value={config.soniox_context_terms}
            onChange={(e) => onUpdateConfig({ soniox_context_terms: e.target.value })}
          />
        </div>
      </Card>
    </div>
  );
}
