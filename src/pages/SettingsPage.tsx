import { useEffect, useState } from "react";
import { open as openExternal } from "@tauri-apps/plugin-shell";
import {
  Download,
  ExternalLink,
  FileText,
  Keyboard,
  Monitor,
  Moon,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  Sun,
  X,
} from "lucide-react";
import { Button, Card, Dialog, Toggle, useToast } from "../components/ui";
import { api } from "../lib/api";
import {
  LANGUAGES,
  SOURCE_LANGUAGES,
  currentServiceValue,
  currentTextServiceValue,
  eventToCombo,
  formatHotkey,
  getServiceOptions,
  parseTextServiceValue,
} from "../lib/constants";
import type { AppConfig, AppMeta, ReleaseInfo } from "../types";

export type SettingsTab = "general" | "text";

interface Props {
  config: AppConfig;
  meta: AppMeta | null;
  activeTab: SettingsTab;
  onTabChange: (tab: SettingsTab) => void;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
}

export function SettingsPage({
  config,
  meta,
  activeTab,
  onTabChange,
  onUpdateConfig,
}: Props) {
  const { toast } = useToast();
  const [checking, setChecking] = useState(false);
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<{ downloaded: number; total: number } | null>(null);
  const [confirmInstall, setConfirmInstall] = useState(false);
  const [recordingAction, setRecordingAction] = useState<string | null>(null);

  useEffect(() => {
    const unlisten = api.onUpdateProgress((p) => setProgress(p));
    return () => {
      unlisten.then((fn) => fn()).catch(() => {});
    };
  }, []);

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

  const serviceOptions = getServiceOptions(config);
  const defaultServiceLabel =
    serviceOptions.find((o) => o.value === currentServiceValue(config))?.label ?? "Google Dịch";

  const handleCheckUpdate = async () => {
    setChecking(true);
    try {
      const found = await api.checkForUpdate();
      setRelease(found);
      if (found) {
        toast(`Có phiên bản mới ${found.version}!`, "success");
      } else {
        toast("Bạn đang dùng phiên bản mới nhất.", "info");
      }
    } catch (err) {
      toast(String(err), "error");
    } finally {
      setChecking(false);
    }
  };

  const handleInstall = async () => {
    if (!release) return;
    setConfirmInstall(false);
    setInstalling(true);
    try {
      await api.installUpdate(release);
    } catch (err) {
      toast(String(err), "error");
      setInstalling(false);
    }
  };

  const renderHotkeyControl = (action: string, label: string, disabled = false) => {
    const combo = config.hotkeys[action] || "";
    const isRecording = recordingAction === action;
    return (
      <div className="field-control">
        <span className="kbd hotkey-kbd">
          {isRecording ? "Nhấn tổ hợp phím… (Esc huỷ)" : formatHotkey(combo)}
        </span>
        <Button
          variant={isRecording ? "primary" : "secondary"}
          disabled={disabled}
          onClick={() => setRecordingAction(isRecording ? null : action)}
        >
          <Keyboard size={16} />
          {isRecording ? "Đang ghi…" : "Đổi phím"}
        </Button>
        <Button
          variant="ghost"
          iconOnly
          disabled={disabled || !combo}
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
    );
  };

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Settings size={24} />
            </span>
            <h1 className="page-title">Cài đặt</h1>
          </div>
          <p className="page-subtitle">
            Tuỳ chỉnh giao diện, cài đặt riêng cho Dịch văn bản, hành vi thay thế và cập nhật ứng dụng.
          </p>
        </div>
      </div>

      <div className="settings-tabs" role="tablist" aria-label="Nhóm cài đặt">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "general"}
          className={`settings-tab-btn ${activeTab === "general" ? "active" : ""}`}
          onClick={() => onTabChange("general")}
        >
          <SlidersHorizontal size={16} />
          Chung
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "text"}
          className={`settings-tab-btn ${activeTab === "text" ? "active" : ""}`}
          onClick={() => onTabChange("text")}
        >
          <FileText size={16} />
          Dịch văn bản
        </button>
      </div>

      {activeTab === "general" && (
        <>
          <Card title="Giao diện">
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Chủ đề giao diện</span>
                <span className="field-hint">
                  Mặc định theo hệ thống Windows; hỗ trợ chế độ Sáng và Tối đồng nhất với bộ ứng dụng *2k.
                </span>
              </div>
              <div className="segmented">
                <Button
                  variant={config.ui_theme === "system" ? "primary" : "secondary"}
                  onClick={() => onUpdateConfig({ ui_theme: "system" })}
                >
                  <Monitor size={16} />
                  Theo hệ thống
                </Button>
                <Button
                  variant={config.ui_theme === "light" ? "primary" : "secondary"}
                  onClick={() => onUpdateConfig({ ui_theme: "light" })}
                >
                  <Sun size={16} />
                  Sáng
                </Button>
                <Button
                  variant={config.ui_theme === "dark" ? "primary" : "secondary"}
                  onClick={() => onUpdateConfig({ ui_theme: "dark" })}
                >
                  <Moon size={16} />
                  Tối
                </Button>
              </div>
            </div>
          </Card>

          <Card
            title="Hành vi dịch màn hình &amp; mặc định"
            description="Tuỳ chọn chi tiết cho dịch văn bản, dịch thay thế (Replace) và lịch sử nằm ở tab Dịch văn bản."
            headerRight={
              <Button variant="secondary" onClick={() => onTabChange("text")}>
                <FileText size={16} />
                Mở cài đặt Dịch văn bản
              </Button>
            }
          >
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Ngôn ngữ đích mặc định (Màn hình / OCR / Live)</span>
                <span className="field-hint">
                  Áp dụng cho chụp vùng màn hình, overlay tại chỗ, ảnh clipboard và Live đa vùng.
                </span>
              </div>
              <select
                className="ui-select"
                value={config.target_language}
                onChange={(e) => onUpdateConfig({ target_language: e.target.value })}
              >
                {LANGUAGES.map(([label, code]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </Card>

          <Card title="Cập nhật &amp; Giới thiệu">
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Tự kiểm tra cập nhật khi mở ứng dụng</span>
              </div>
              <Toggle
                checked={config.auto_update}
                onChange={(v) => onUpdateConfig({ auto_update: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">
                  {meta?.name ?? "Translator2k"} · v{meta?.version ?? "2.1.0"}
                </span>
                <span className="field-hint">
                  Viết lại hoàn toàn bằng Rust + Tauri 2 · Tác giả: {meta?.publisher ?? "hieuduongzx"}
                </span>
              </div>
              <div className="field-control">
                <Button variant="secondary" disabled={checking} onClick={handleCheckUpdate}>
                  <RefreshCw size={16} className={checking ? "spin" : undefined} />
                  {checking ? "Đang kiểm tra…" : "Kiểm tra cập nhật"}
                </Button>
                {meta?.releases_url && (
                  <Button variant="ghost" onClick={() => openExternal(meta.releases_url)}>
                    <ExternalLink size={16} />
                    Trang phát hành
                  </Button>
                )}
              </div>
            </div>

            {release && (
              <div className="history-item" style={{ marginTop: 12 }}>
                <div className="row-8" style={{ justifyContent: "space-between" }}>
                  <div>
                    <strong>Phiên bản mới: {release.name}</strong>
                    {progress && progress.total > 0 && (
                      <div className="field-hint">
                        Đang tải: {Math.round((progress.downloaded / progress.total) * 100)}%
                      </div>
                    )}
                  </div>
                  <Button
                    variant="primary"
                    disabled={installing || !release.asset_url}
                    onClick={() => setConfirmInstall(true)}
                  >
                    <Download size={16} />
                    {installing ? "Đang tải & cài…" : "Cập nhật ngay"}
                  </Button>
                </div>
                {release.notes && <div className="field-hint">{release.notes}</div>}
              </div>
            )}
          </Card>
        </>
      )}

      {activeTab === "text" && (
        <>
          <Card
            title="Ngôn ngữ &amp; Bộ dịch văn bản"
            description="Lưu riêng cho chức năng dịch văn bản nhập, tự dịch khi Copy và dịch thay thế."
          >
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Ngôn ngữ nguồn</span>
                <span className="field-hint">
                  Chọn Tự nhận diện để phát hiện ngôn ngữ tự động, hoặc cố định ngôn ngữ đầu vào để dịch chuẩn hơn.
                </span>
              </div>
              <select
                className="ui-select"
                aria-label="Ngôn ngữ nguồn dịch văn bản"
                value={config.text_source_language}
                onChange={(e) => onUpdateConfig({ text_source_language: e.target.value })}
              >
                {SOURCE_LANGUAGES.map(([label, code]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Ngôn ngữ đích</span>
                <span className="field-hint">
                  Ngôn ngữ đích mặc định cho khung Dịch nhanh và tự dịch khi Copy.
                </span>
              </div>
              <select
                className="ui-select"
                aria-label="Ngôn ngữ đích dịch văn bản"
                value={config.text_target_language}
                onChange={(e) => onUpdateConfig({ text_target_language: e.target.value })}
              >
                {LANGUAGES.map(([label, code]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Dịch vụ / Bộ dịch cho văn bản</span>
                <span className="field-hint">
                  Có thể chọn bộ dịch hoặc model AI riêng cho Dịch văn bản mà không ảnh hưởng OCR / Live.
                </span>
              </div>
              <select
                className="ui-select"
                aria-label="Bộ dịch văn bản"
                value={currentTextServiceValue(config)}
                onChange={(e) => {
                  const parsed = parseTextServiceValue(e.target.value);
                  onUpdateConfig(parsed);
                }}
              >
                <option value="">Theo mặc định ứng dụng ({defaultServiceLabel})</option>
                {serviceOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </Card>

          <Card
            title="Chế độ Dịch &amp; thay thế tại chỗ (Replace)"
            description="Bôi đen văn bản ở ứng dụng bất kỳ rồi nhấn phím tắt để dịch và dán đè ngay tại chỗ."
          >
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Bật chế độ Dịch &amp; thay thế tại chỗ</span>
                <span className="field-hint">
                  Khi tắt, phím tắt thay thế sẽ ngừng hoạt động để tránh dán nhầm khi gõ văn bản.
                </span>
              </div>
              <Toggle
                checked={config.replace_enabled}
                onChange={(v) => onUpdateConfig({ replace_enabled: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Ngôn ngữ đích khi thay thế</span>
                <span className="field-hint">
                  Độc lập với ngôn ngữ đọc — mặc định sang Tiếng Anh để nhắn tin, viết email hoặc tìm kiếm nhanh.
                </span>
              </div>
              <select
                className="ui-select"
                aria-label="Ngôn ngữ đích khi thay thế"
                disabled={!config.replace_enabled}
                value={config.replace_target_language}
                onChange={(e) => onUpdateConfig({ replace_target_language: e.target.value })}
              >
                {LANGUAGES.map(([label, code]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Phím tắt Dịch &amp; thay thế</span>
                <span className="field-hint">
                  Đồng bộ trực tiếp với trang Phím tắt toàn cục.
                </span>
              </div>
              {renderHotkeyControl(
                "selected_text_replace",
                "Dịch & thay thế tại chỗ",
                !config.replace_enabled
              )}
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Giữ định dạng &amp; xuống dòng</span>
                <span className="field-hint">
                  Giữ nguyên khoảng trắng đầu/cuối và cấu trúc xuống dòng. Tắt để gộp dòng gọn khi dịch đoạn copy từ PDF.
                </span>
              </div>
              <Toggle
                checked={config.replace_preserve_formatting}
                onChange={(v) => onUpdateConfig({ replace_preserve_formatting: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Hiện bản gốc để hoàn tác sau khi thay thế</span>
                <span className="field-hint">
                  Hiển thị thanh lưu bản gốc trên HUD và Dịch nhanh để sao chép/hoàn tác lại chỉ với một bấm.
                </span>
              </div>
              <Toggle
                checked={config.replace_show_undo_original}
                onChange={(v) => onUpdateConfig({ replace_show_undo_original: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Khôi phục clipboard cũ sau khi dán</span>
                <span className="field-hint">
                  Trả lại nội dung clipboard trước đó sau khi dán đè; tắt nếu muốn giữ bản dịch trong clipboard.
                </span>
              </div>
              <Toggle
                checked={config.replace_restore_clipboard}
                onChange={(v) => onUpdateConfig({ replace_restore_clipboard: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Độ trễ trước khi dán (ms)</span>
                <span className="field-hint">
                  Từ 20 ms đến 500 ms (mặc định 60 ms). Tăng lên nếu ứng dụng đích phản hồi chậm khi nhấn Ctrl+V.
                </span>
              </div>
              <input
                type="number"
                className="ui-input"
                style={{ width: 110 }}
                min={20}
                max={500}
                step={10}
                value={config.replace_paste_delay_ms}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (!Number.isNaN(val)) {
                    onUpdateConfig({ replace_paste_delay_ms: Math.max(20, Math.min(500, val)) });
                  }
                }}
              />
            </div>
          </Card>

          <Card title="Phím tắt &amp; Tự động hoá dịch văn bản">
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Phím tắt gửi dịch trong ô nhập</span>
                <span className="field-hint">
                  Chọn tổ hợp phím để kích hoạt dịch nhanh ngay trong khung nhập văn bản.
                </span>
              </div>
              <div className="segmented">
                <Button
                  variant={config.text_submit_shortcut === "ctrl_enter" ? "primary" : "secondary"}
                  onClick={() => onUpdateConfig({ text_submit_shortcut: "ctrl_enter" })}
                >
                  Ctrl + Enter
                </Button>
                <Button
                  variant={config.text_submit_shortcut === "enter" ? "primary" : "secondary"}
                  onClick={() => onUpdateConfig({ text_submit_shortcut: "enter" })}
                >
                  Enter (Shift+Enter xuống dòng)
                </Button>
              </div>
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Phím tắt mở nhanh ô dịch văn bản</span>
                <span className="field-hint">Đưa cửa sổ Dịch nhanh lên trước từ bất kỳ ứng dụng nào.</span>
              </div>
              {renderHotkeyControl("quick_translate", "Mở dịch văn bản nhập")}
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Tự sao chép kết quả sau khi dịch</span>
                <span className="field-hint">
                  Tự động đưa bản dịch vào clipboard sau khi dịch văn bản (không gây lặp với tự dịch Ctrl+C).
                </span>
              </div>
              <Toggle
                checked={config.text_auto_copy_result}
                onChange={(v) => onUpdateConfig({ text_auto_copy_result: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Tự động dịch khi nhấn Ctrl+C</span>
                <span className="field-hint">
                  Tự phát hiện văn bản copy ở bất kỳ ứng dụng nào (bỏ qua mật khẩu từ trình quản lý mật khẩu).
                </span>
              </div>
              <Toggle
                checked={config.auto_translate_clipboard}
                onChange={(v) => onUpdateConfig({ auto_translate_clipboard: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Phím tắt bật/tắt tự dịch khi Copy</span>
                <span className="field-hint">Bật hoặc tắt nhanh theo dõi clipboard toàn cục.</span>
              </div>
              {renderHotkeyControl("toggle_auto_clipboard", "Bật/tắt tự dịch khi copy")}
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Giới hạn ký tự tối đa khi tự dịch Ctrl+C</span>
                <span className="field-hint">
                  Bỏ qua đoạn văn bản copy dài hơn ngưỡng này (200 – 20.000 ký tự, mặc định 5.000).
                </span>
              </div>
              <input
                type="number"
                className="ui-input"
                style={{ width: 110 }}
                min={200}
                max={20000}
                step={500}
                value={config.auto_clipboard_max_chars}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (!Number.isNaN(val)) {
                    onUpdateConfig({
                      auto_clipboard_max_chars: Math.max(200, Math.min(20000, val)),
                    });
                  }
                }}
              />
            </div>
          </Card>

          <Card title="Lịch sử dịch">
            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Lưu lịch sử các bản dịch</span>
                <span className="field-hint">
                  Ghi lại bản gốc và bản dịch để tra cứu hoặc sao chép lại nhanh trong trang Dịch nhanh.
                </span>
              </div>
              <Toggle
                checked={config.text_keep_history}
                onChange={(v) => onUpdateConfig({ text_keep_history: v })}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Số mục lịch sử tối đa</span>
                <span className="field-hint">Từ 5 đến 200 bản dịch gần nhất (mặc định 30).</span>
              </div>
              <input
                type="number"
                className="ui-input"
                style={{ width: 110 }}
                min={5}
                max={200}
                step={5}
                disabled={!config.text_keep_history}
                value={config.text_history_limit}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (!Number.isNaN(val)) {
                    onUpdateConfig({ text_history_limit: Math.max(5, Math.min(200, val)) });
                  }
                }}
              />
            </div>

            <div className="field-row">
              <div className="field-meta">
                <span className="field-label">Giữ lịch sử qua các lần mở ứng dụng</span>
                <span className="field-hint">
                  Lưu danh sách lịch sử xuống máy để không bị mất khi đóng ứng dụng.
                </span>
              </div>
              <Toggle
                checked={config.text_persist_history}
                onChange={(v) => onUpdateConfig({ text_persist_history: v })}
              />
            </div>
          </Card>
        </>
      )}

      <Dialog
        open={confirmInstall}
        title={`Cài đặt bản cập nhật ${release?.version}?`}
        description="Ứng dụng sẽ tải bộ cài đặt từ GitHub Releases, tự đóng để cài đặt im lặng rồi mở lại."
        confirmLabel="Cập nhật"
        onClose={() => setConfirmInstall(false)}
        onConfirm={handleInstall}
      />
    </div>
  );
}
