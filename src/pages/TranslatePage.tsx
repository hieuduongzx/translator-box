import { useState } from "react";
import {
  ArrowLeftRight,
  Camera,
  Clipboard,
  Copy,
  Eraser,
  Image as ImageIcon,
  Languages,
  Layers,
  Loader2,
  PictureInPicture2,
  Replace,
  RotateCcw,
  Send,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import { Button, Card, ConfirmDialog } from "../components/ui";
import { usePersistentState, type ToastKind } from "../hooks";
import { api } from "../lib/api";
import {
  LANGUAGES,
  SOURCE_LANGUAGES,
  SOURCE_KIND_LABELS,
  currentServiceValue,
  currentTextServiceValue,
  formatHotkey,
  getServiceOptions,
  parseTextServiceValue,
} from "../lib/constants";
import { appActions, useAppSlice } from "../store/appStore";
import type { AppConfig, HistoryEntry, ReplaceCompletedPayload } from "../types";

interface Props {
  config: AppConfig;
  history: HistoryEntry[];
  lastReplace: ReplaceCompletedPayload | null;
  onDismissReplace: () => void;
  onOpenTextSettings: () => void;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onHistoryCleared: () => void;
  onToast: (message: string, kind?: ToastKind) => void;
}

export function TranslatePage({
  config,
  history,
  lastReplace,
  onDismissReplace,
  onOpenTextSettings,
  onUpdateConfig,
  onHistoryCleared,
  onToast: toast,
}: Props) {
  const { sourceText, resultText, imagePreview, busy, statusText } = useAppSlice("translate");
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [historyFilter, setHistoryFilter] = usePersistentState<string>(
    "translator2k.ui.historyFilter",
    "all",
    { validate: (v): v is string => typeof v === "string" && v.length > 0 }
  );

  const filteredHistory =
    historyFilter === "all"
      ? history
      : history.filter((item) => item.source_kind === historyFilter);

  const serviceOptions = getServiceOptions(config);
  const defaultServiceLabel =
    serviceOptions.find((o) => o.value === currentServiceValue(config))?.label ?? "Google Dịch";

  const actionTip = (desc: string, action: string) => {
    const raw = config.hotkeys[action]?.trim() || "";
    return raw ? `${desc} · Phím tắt: ${formatHotkey(raw)}` : desc;
  };

  const handleTranslate = () => {
    void appActions.translateText(config);
  };

  const handleCopy = async (text: string, label = "Đã sao chép bản dịch") => {
    if (!text.trim()) return;
    try {
      await api.copyText(text);
      toast(label, "success");
    } catch (err) {
      toast(String(err), "error");
    }
  };

  const handleClearOverlays = async () => {
    await api.clearOverlays();
    toast("Đã xoá mọi overlay trên màn hình", "info");
  };

  const handleToggleHud = async () => {
    try {
      const visible = await api.toggleHudWindow();
      toast(visible ? "Đã bật khung HUD nổi" : "Đã ẩn khung HUD nổi", "info");
    } catch (err) {
      toast(String(err), "error");
    }
  };

  const handleSwapLanguages = () => {
    if (config.text_source_language === "auto") return;
    const prevSource = config.text_source_language;
    const prevTarget = config.text_target_language;
    onUpdateConfig({
      text_source_language: prevTarget,
      text_target_language: prevSource,
    });
  };

  const submitPlaceholder =
    config.text_submit_shortcut === "enter"
      ? "Nhập hoặc dán văn bản cần dịch… (Enter để dịch, Shift+Enter xuống dòng)"
      : "Nhập hoặc dán văn bản cần dịch… (Ctrl+Enter để dịch)";

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Languages size={24} />
            </span>
            <h1 className="page-title">Dịch nhanh &amp; Màn hình</h1>
          </div>
          <p className="page-subtitle">
            Dịch văn bản, chọn vùng màn hình vẽ overlay tại chỗ, hoặc xử lý ảnh từ clipboard.
          </p>
        </div>
        <div className="page-header-actions">
          <Button
            variant="secondary"
            data-tip="Mở tab Cài đặt riêng cho Dịch văn bản & Replace"
            data-tip-pos="bottom"
            data-tip-align="right"
            title="Mở tab Cài đặt riêng cho Dịch văn bản & Replace"
            onClick={onOpenTextSettings}
          >
            <SlidersHorizontal size={16} />
            Cài đặt dịch
          </Button>
          <Button
            variant="secondary"
            data-tip="Mở hoặc ẩn thanh HUD nổi gọn nhẹ trên màn hình"
            data-tip-pos="bottom"
            data-tip-align="right"
            title="Mở hoặc ẩn thanh HUD nổi gọn nhẹ trên màn hình"
            onClick={handleToggleHud}
          >
            <PictureInPicture2 size={16} />
            HUD nổi
          </Button>
          <Button
            variant="secondary"
            data-tip="Xoá toàn bộ lớp phủ bản dịch đang hiện trên màn hình (hoặc bấm vào overlay / nhấn Esc)"
            data-tip-pos="bottom"
            data-tip-align="right"
            title="Xoá toàn bộ lớp phủ bản dịch đang hiện trên màn hình"
            onClick={handleClearOverlays}
          >
            <Eraser size={16} />
            Xoá overlay
          </Button>
        </div>
      </div>

      {busy && (
        <div className="task-busy-banner" role="status" aria-live="polite">
          <Loader2 size={16} className="ui-spin" />
          <span>{statusText || "Đang xử lý tác vụ dịch…"}</span>
        </div>
      )}

      {lastReplace && config.replace_show_undo_original && (
        <div className="undo-banner">
          <div className="undo-banner-body">
            <div className="row-8">
              <span className="badge accent">
                <RotateCcw size={16} />
                Bản gốc vừa thay thế ({lastReplace.timestamp})
              </span>
              <span className="field-hint">Nhấn Ctrl+Z ở ứng dụng đích hoặc sao chép lại bản gốc:</span>
            </div>
            <div className="undo-banner-text">{lastReplace.original}</div>
          </div>
          <div className="row-8">
            <Button
              variant="secondary"
              onClick={() => handleCopy(lastReplace.original, "Đã sao chép bản gốc để hoàn tác")}
            >
              <Copy size={16} />
              Chép bản gốc
            </Button>
            <Button
              variant="ghost"
              iconOnly
              title="Đóng thông báo hoàn tác"
              aria-label="Đóng thông báo hoàn tác"
              onClick={onDismissReplace}
            >
              <X size={16} />
            </Button>
          </div>
        </div>
      )}

      <Card title="Tác vụ tức thì" description="Rê chuột vào từng nút để xem mô tả và phím tắt toàn cục tương ứng.">
        <div className="row-8">
          <Button
            variant="primary"
            disabled={busy}
            data-tip={actionTip("Chọn vùng, dịch một lần và vẽ đè lên chữ gốc (bấm vào overlay hoặc Esc để đóng)", "region_to_overlay")}
            data-tip-align="left"
            title={actionTip("Chọn vùng, dịch một lần và vẽ đè lên chữ gốc", "region_to_overlay")}
            onClick={() =>
              void appActions.runTranslateAction(
                "region_to_overlay",
                api.regionToOverlay,
                "Chọn vùng để vẽ overlay bản dịch…",
                "Đã hiện overlay (bấm vào overlay hoặc nhấn Esc để đóng)"
              )
            }
          >
            <Layers size={16} />
            Vùng → Overlay tại chỗ
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("Chọn vùng, OCR và đưa bản dịch vào khung", "region_to_text")}
            title={actionTip("Chọn vùng, OCR và đưa bản dịch vào khung", "region_to_text")}
            onClick={() =>
              void appActions.runTranslateAction(
                "region_to_text",
                api.regionToText,
                "Chọn vùng màn hình cần dịch…",
                "Đã OCR và dịch vùng màn hình"
              )
            }
          >
            <Camera size={16} />
            Vùng → Khung dịch
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("OCR ảnh clipboard, xoá chữ gốc và vẽ bản dịch đè lên ảnh", "clipboard_image_replace")}
            title={actionTip("OCR ảnh clipboard, xoá chữ gốc và vẽ bản dịch đè lên ảnh", "clipboard_image_replace")}
            onClick={() =>
              void appActions.runTranslateAction(
                "clipboard_image_replace",
                api.clipboardImageReplace,
                "Đang OCR & dịch ảnh từ clipboard…",
                "Đã dịch ảnh từ clipboard"
              )
            }
          >
            <ImageIcon size={16} />
            Dịch ảnh clipboard
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("OCR ảnh clipboard rồi xuất bản dịch dạng chữ", "clipboard_image_to_text")}
            title={actionTip("OCR ảnh clipboard rồi xuất bản dịch dạng chữ", "clipboard_image_to_text")}
            onClick={() =>
              void appActions.runTranslateAction(
                "clipboard_image_to_text",
                api.clipboardImageToText,
                "Đang trích xuất chữ từ ảnh clipboard…",
                "Đã trích xuất văn bản ảnh clipboard"
              )
            }
          >
            <Clipboard size={16} />
            Ảnh clipboard → Chữ
          </Button>
          <Button
            variant="secondary"
            disabled={busy || !config.replace_enabled}
            data-tip={
              config.replace_enabled
                ? actionTip("Copy văn bản đang bôi đen, dịch rồi dán đè tại chỗ", "selected_text_replace")
                : "Đang tắt trong Cài đặt → Dịch văn bản"
            }
            data-tip-align="left"
            title={actionTip("Copy văn bản đang bôi đen, dịch rồi dán đè tại chỗ", "selected_text_replace")}
            onClick={() =>
              void appActions.runTranslateAction(
                "selected_text_replace",
                api.selectedTextReplace,
                "Đang dịch & thay thế tại chỗ…",
                "Đã thay thế văn bản tại chỗ"
              )
            }
          >
            <Replace size={16} />
            Dịch &amp; thay thế
          </Button>
        </div>
      </Card>

      <Card
        title="Dịch văn bản trực tiếp"
        headerRight={
          <div className="row-8">
            <select
              className="ui-select"
              aria-label="Bộ dịch văn bản"
              value={currentTextServiceValue(config)}
              onChange={(e) => {
                const parsed = parseTextServiceValue(e.target.value);
                onUpdateConfig(parsed);
              }}
            >
              <option value="">Mặc định ({defaultServiceLabel})</option>
              {serviceOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              className="ui-select"
              aria-label="Ngôn ngữ nguồn"
              value={config.text_source_language}
              onChange={(e) => onUpdateConfig({ text_source_language: e.target.value })}
            >
              {SOURCE_LANGUAGES.map(([label, code]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
            <Button
              variant="ghost"
              iconOnly
              disabled={config.text_source_language === "auto"}
              title={
                config.text_source_language === "auto"
                  ? "Chọn ngôn ngữ nguồn cụ thể để đảo chiều"
                  : "Đảo chiều ngôn ngữ nguồn và đích"
              }
              aria-label="Đảo chiều ngôn ngữ"
              onClick={handleSwapLanguages}
            >
              <ArrowLeftRight size={16} />
            </Button>
            <select
              className="ui-select"
              aria-label="Ngôn ngữ đích"
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
        }
      >
        <div className="grid-2">
          <div className="stack-8">
            <textarea
              className="ui-textarea"
              rows={6}
              placeholder={submitPlaceholder}
              value={sourceText}
              onChange={(e) => appActions.setSourceText(e.target.value)}
              onKeyDown={(e) => {
                if (config.text_submit_shortcut === "enter") {
                  if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey) {
                    e.preventDefault();
                    handleTranslate();
                  }
                } else if (e.ctrlKey && e.key === "Enter") {
                  e.preventDefault();
                  handleTranslate();
                }
              }}
            />
            <div className="row-8">
              <Button variant="primary" disabled={busy || !sourceText.trim()} onClick={handleTranslate}>
                {busy ? <Loader2 size={16} className="ui-spin" /> : <Send size={16} />}
                {busy ? "Đang dịch…" : "Dịch ngay"}
              </Button>
              <Button
                variant="ghost"
                disabled={busy || (!sourceText && !resultText && !imagePreview)}
                onClick={() => appActions.clearTranslate()}
              >
                Xoá ô nhập
              </Button>
            </div>
          </div>

          <div className="stack-8">
            <textarea
              className="ui-textarea"
              rows={6}
              readOnly
              placeholder="Bản dịch sẽ hiển thị tại đây…"
              value={resultText}
            />
            <div className="row-8">
              <Button
                variant="secondary"
                disabled={!resultText.trim()}
                onClick={() => handleCopy(resultText)}
              >
                <Copy size={16} />
                Sao chép bản dịch
              </Button>
              {config.text_auto_copy_result && (
                <span className="field-hint">Tự sao chép đang bật</span>
              )}
            </div>
          </div>
        </div>

        {imagePreview && (
          <div style={{ marginTop: 16 }}>
            <div className="field-label" style={{ marginBottom: 8 }}>
              Ảnh đã xoá chữ gốc và vẽ bản dịch
            </div>
            <img
              src={imagePreview}
              alt="Ảnh đã dịch"
              style={{
                maxWidth: "100%",
                maxHeight: 420,
                borderRadius: "var(--radius)",
                border: "1px solid var(--border)",
              }}
            />
          </div>
        )}
      </Card>

      <Card
        title={`Lịch sử dịch (${filteredHistory.length}/${config.text_history_limit})`}
        headerRight={
          <div className="row-8">
            {!config.text_keep_history && (
              <span className="badge warning">Đang tắt lưu lịch sử</span>
            )}
            <select
              className="ui-select"
              aria-label="Lọc lịch sử theo nguồn"
              value={historyFilter}
              onChange={(e) => setHistoryFilter(e.target.value)}
            >
              <option value="all">Tất cả nguồn</option>
              <option value="text">Văn bản</option>
              <option value="replace">Dịch &amp; thay thế</option>
              <option value="clipboard">Tự dịch Copy</option>
              <option value="overlay">Overlay tại chỗ</option>
              <option value="screen">Vùng màn hình</option>
              <option value="clipboard-image">Ảnh clipboard</option>
            </select>
            {history.length > 0 && (
              <Button variant="ghost" onClick={() => setConfirmClearHistory(true)}>
                <Trash2 size={16} />
                Xoá lịch sử
              </Button>
            )}
          </div>
        }
      >
        {filteredHistory.length === 0 ? (
          <div className="empty-state">
            <Languages size={20} />
            <span>
              {!config.text_keep_history
                ? "Tính năng lưu lịch sử đang tắt trong Cài đặt → Dịch văn bản."
                : history.length === 0
                  ? "Chưa có bản dịch nào được lưu."
                  : "Không có bản dịch nào khớp bộ lọc đang chọn."}
            </span>
          </div>
        ) : (
          <div className="stack-8">
            {filteredHistory.slice(0, config.text_history_limit).map((item) => (
              <div key={item.id} className="history-item">
                <div className="row-8" style={{ justifyContent: "space-between" }}>
                  <div className="row-8">
                    <span className="badge">
                      {SOURCE_KIND_LABELS[item.source_kind] ?? item.source_kind}
                    </span>
                    <span className="field-hint">{item.timestamp}</span>
                  </div>
                  <div className="row-8">
                    {item.source_kind === "replace" && (
                      <Button
                        variant="ghost"
                        onClick={() => handleCopy(item.original, "Đã sao chép bản gốc")}
                      >
                        <RotateCcw size={16} />
                        Bản gốc
                      </Button>
                    )}
                    <Button variant="ghost" onClick={() => handleCopy(item.translated)}>
                      <Copy size={16} />
                      Sao chép
                    </Button>
                  </div>
                </div>
                <div className="field-hint selectable-text">{item.original}</div>
                <div className="selectable-text" style={{ fontWeight: 500 }}>
                  {item.translated}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={confirmClearHistory}
        title="Xoá toàn bộ lịch sử dịch?"
        message="Hành động này sẽ xoá toàn bộ danh sách lịch sử dịch đã lưu."
        confirmLabel="Xoá lịch sử"
        confirmVariant="danger"
        onCancel={() => setConfirmClearHistory(false)}
        onConfirm={async () => {
          await api.clearHistory();
          onHistoryCleared();
          setConfirmClearHistory(false);
          toast("Đã xoá lịch sử dịch", "info");
        }}
      />
    </div>
  );
}
