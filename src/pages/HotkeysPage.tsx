import { useEffect, useState } from "react";
import { Keyboard, RotateCcw, X } from "lucide-react";
import { Button, Card, Dialog, useToast } from "../components/ui";
import { api } from "../lib/api";
import { HOTKEY_ACTIONS, formatHotkey } from "../lib/constants";
import type { AppConfig } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onConfigReplaced: (cfg: AppConfig) => void;
}

function eventToCombo(e: KeyboardEvent): string | null {
  const key = e.key.toLowerCase();
  if (["control", "alt", "shift", "meta"].includes(key)) return null;
  const parts: string[] = [];
  if (e.ctrlKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  if (e.metaKey) parts.push("win");

  const mapped =
    key === " "
      ? "space"
      : key === "arrowup"
        ? "up"
        : key === "arrowdown"
          ? "down"
          : key === "arrowleft"
            ? "left"
            : key === "arrowright"
              ? "right"
              : key;
  parts.push(mapped);
  return parts.join("+");
}

export function HotkeysPage({ config, onUpdateConfig, onConfigReplaced }: Props) {
  const { toast } = useToast();
  const [recordingAction, setRecordingAction] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    if (!recordingAction) return;
    const onKeyDown = async (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") {
        setRecordingAction(null);
        return;
      }
      const combo = eventToCombo(e);
      if (!combo) return;
      const duplicate = Object.entries(config.hotkeys).find(
        ([act, val]) => act !== recordingAction && val.toLowerCase() === combo
      );
      if (duplicate) {
        toast(`Tổ hợp ${formatHotkey(combo)} đã được dùng cho lệnh khác.`, "error");
        setRecordingAction(null);
        return;
      }
      const next = { ...config.hotkeys, [recordingAction]: combo };
      setRecordingAction(null);
      await onUpdateConfig({ hotkeys: next });
      toast(`Đã đặt phím tắt ${formatHotkey(combo)}`, "success");
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [recordingAction, config.hotkeys, onUpdateConfig, toast]);

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Keyboard size={24} />
            </span>
            <h1 className="page-title">Phím tắt toàn cục</h1>
          </div>
          <p className="page-subtitle">
            Đăng ký trực tiếp bằng Win32 RegisterHotKey — hoạt động trên mọi game/ứng dụng không xung đột anti-cheat.
          </p>
        </div>
        <div className="page-header-actions">
          <Button variant="secondary" onClick={() => setConfirmReset(true)}>
            <RotateCcw size={16} />
            Khôi phục mặc định
          </Button>
        </div>
      </div>

      <Card title="Danh sách tổ hợp phím">
        {HOTKEY_ACTIONS.map(({ label, action, hint }) => {
          const combo = config.hotkeys[action] || "";
          const isRecording = recordingAction === action;
          return (
            <div key={action} className="field-row">
              <div className="field-meta">
                <span className="field-label">{label}</span>
                <span className="field-hint">{hint}</span>
              </div>
              <div className="field-control">
                <span className="kbd hotkey-kbd">
                  {isRecording ? "Nhấn tổ hợp phím… (Esc huỷ)" : formatHotkey(combo)}
                </span>
                <Button
                  variant={isRecording ? "primary" : "secondary"}
                  onClick={() => setRecordingAction(isRecording ? null : action)}
                >
                  <Keyboard size={16} />
                  {isRecording ? "Đang ghi…" : "Đổi phím"}
                </Button>
                <Button
                  variant="ghost"
                  iconOnly
                  disabled={!combo}
                  title="Tắt phím tắt này"
                  aria-label={`Tắt phím tắt ${label}`}
                  onClick={async () => {
                    const next = { ...config.hotkeys, [action]: "" };
                    await onUpdateConfig({ hotkeys: next });
                    toast("Đã tắt phím tắt", "info");
                  }}
                >
                  <X size={16} />
                </Button>
              </div>
            </div>
          );
        })}
      </Card>

      <Dialog
        open={confirmReset}
        title="Khôi phục toàn bộ phím tắt mặc định?"
        description="Mọi phím tắt tuỳ chỉnh sẽ được đặt lại theo cấu hình ban đầu."
        confirmLabel="Khôi phục"
        onClose={() => setConfirmReset(false)}
        onConfirm={async () => {
          try {
            const updated = await api.resetHotkeys();
            onConfigReplaced(updated);
            setConfirmReset(false);
            toast("Đã khôi phục phím tắt mặc định", "success");
          } catch (err) {
            toast(String(err), "error");
          }
        }}
      />
    </div>
  );
}
