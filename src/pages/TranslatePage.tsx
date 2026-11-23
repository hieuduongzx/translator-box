import { useState } from "react";
import {
  Camera,
  Clipboard,
  Copy,
  Eraser,
  Image as ImageIcon,
  Languages,
  Layers,
  PictureInPicture2,
  Replace,
  Send,
  Trash2,
} from "lucide-react";
import { Button, Card, Dialog, useToast } from "../components/ui";
import { api } from "../lib/api";
import {
  LANGUAGES,
  SOURCE_KIND_LABELS,
  currentServiceValue,
  formatHotkey,
  getServiceOptions,
  parseServiceValue,
} from "../lib/constants";
import type { AppConfig, HistoryEntry } from "../types";

interface Props {
  config: AppConfig;
  history: HistoryEntry[];
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onHistoryCleared: () => void;
}

export function TranslatePage({
  config,
  history,
  onUpdateConfig,
  onHistoryCleared,
}: Props) {
  const { toast } = useToast();
  const [sourceText, setSourceText] = useState("");
  const [resultText, setResultText] = useState("");
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);

  const serviceOptions = getServiceOptions(config);

  const actionTip = (desc: string, action: string) => {
    const raw = config.hotkeys[action]?.trim() || "";
    return raw ? `${desc} · Phím tắt: ${formatHotkey(raw)}` : desc;
  };

  const handleTranslate = async () => {
    const trimmed = sourceText.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setImagePreview(null);
    try {
      const res = await api.translateText(trimmed, config.target_language);
      setResultText(res.translated);
    } catch (err) {
      toast(String(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (
    fn: () => Promise<{ original: string; translated: string; image_data_url: string | null }>,
    okMsg?: string
  ) => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fn();
      if (res.original) setSourceText(res.original);
      if (res.translated) setResultText(res.translated);
      setImagePreview(res.image_data_url);
      if (okMsg && (res.translated || res.image_data_url)) {
        toast(okMsg, "success");
      }
    } catch (err) {
      toast(String(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleCopy = async (text: string) => {
    if (!text.trim()) return;
    try {
      await api.copyText(text);
      toast("Đã sao chép bản dịch", "success");
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
            data-tip="Xoá toàn bộ lớp phủ bản dịch đang hiện trên màn hình"
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

      <Card title="Tác vụ tức thì" description="Rê chuột vào từng nút để xem mô tả và phím tắt toàn cục tương ứng.">
        <div className="row-8">
          <Button
            variant="primary"
            disabled={busy}
            data-tip={actionTip("Chọn vùng, dịch một lần và vẽ đè lên chữ gốc", "region_to_overlay")}
            data-tip-align="left"
            title={actionTip("Chọn vùng, dịch một lần và vẽ đè lên chữ gốc", "region_to_overlay")}
            onClick={() => runAction(api.regionToOverlay, "Đã hiện overlay bản dịch tại chỗ")}
          >
            <Layers size={16} />
            Vùng → Overlay tại chỗ
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("Chọn vùng, OCR và đưa bản dịch vào khung", "region_to_text")}
            title={actionTip("Chọn vùng, OCR và đưa bản dịch vào khung", "region_to_text")}
            onClick={() => runAction(api.regionToText, "Đã OCR và dịch vùng màn hình")}
          >
            <Camera size={16} />
            Vùng → Khung dịch
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("OCR ảnh clipboard, xoá chữ gốc và vẽ bản dịch đè lên ảnh", "clipboard_image_replace")}
            title={actionTip("OCR ảnh clipboard, xoá chữ gốc và vẽ bản dịch đè lên ảnh", "clipboard_image_replace")}
            onClick={() => runAction(api.clipboardImageReplace, "Đã dịch ảnh từ clipboard")}
          >
            <ImageIcon size={16} />
            Dịch ảnh clipboard
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("OCR ảnh clipboard rồi xuất bản dịch dạng chữ", "clipboard_image_to_text")}
            title={actionTip("OCR ảnh clipboard rồi xuất bản dịch dạng chữ", "clipboard_image_to_text")}
            onClick={() => runAction(api.clipboardImageToText, "Đã trích xuất văn bản ảnh clipboard")}
          >
            <Clipboard size={16} />
            Ảnh clipboard → Chữ
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            data-tip={actionTip("Copy văn bản đang bôi đen, dịch rồi dán đè tại chỗ", "selected_text_replace")}
            data-tip-align="left"
            title={actionTip("Copy văn bản đang bôi đen, dịch rồi dán đè tại chỗ", "selected_text_replace")}
            onClick={() => runAction(api.selectedTextReplace, "Đã thay thế văn bản tại chỗ")}
          >
            <Replace size={16} />
            Dịch & thay thế
          </Button>
        </div>
      </Card>

      <Card
        title="Dịch văn bản trực tiếp"
        headerRight={
          <div className="row-8">
            <select
              className="ui-select"
              aria-label="Dịch vụ dịch"
              value={currentServiceValue(config)}
              onChange={(e) => {
                const parsed = parseServiceValue(e.target.value);
                onUpdateConfig({
                  translator: parsed.translator,
                  ...(parsed.llm_model ? { llm_model: parsed.llm_model } : {}),
                });
              }}
            >
              {serviceOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <Languages size={16} color="var(--text-muted)" />
            <select
              className="ui-select"
              aria-label="Ngôn ngữ đích"
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
        }
      >
        <div className="grid-2">
          <div className="stack-8">
            <textarea
              className="ui-textarea"
              rows={6}
              placeholder="Nhập hoặc dán văn bản cần dịch… (Ctrl+Enter để dịch)"
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              onKeyDown={(e) => {
                if (e.ctrlKey && e.key === "Enter") {
                  e.preventDefault();
                  handleTranslate();
                }
              }}
            />
            <div className="row-8">
              <Button variant="primary" disabled={busy || !sourceText.trim()} onClick={handleTranslate}>
                <Send size={16} />
                {busy ? "Đang dịch…" : "Dịch ngay"}
              </Button>
              <Button
                variant="ghost"
                disabled={!sourceText && !resultText && !imagePreview}
                onClick={() => {
                  setSourceText("");
                  setResultText("");
                  setImagePreview(null);
                }}
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
        title={`Lịch sử dịch trong phiên (${history.length})`}
        headerRight={
          history.length > 0 && (
            <Button variant="ghost" onClick={() => setConfirmClearHistory(true)}>
              <Trash2 size={16} />
              Xoá lịch sử
            </Button>
          )
        }
      >
        {history.length === 0 ? (
          <div className="empty-state">
            <Languages size={20} />
            <span>Chưa có bản dịch nào trong phiên này.</span>
          </div>
        ) : (
          <div className="stack-8">
            {history.slice(0, 12).map((item) => (
              <div key={item.id} className="history-item">
                <div className="row-8" style={{ justifyContent: "space-between" }}>
                  <div className="row-8">
                    <span className="badge">
                      {SOURCE_KIND_LABELS[item.source_kind] ?? item.source_kind}
                    </span>
                    <span className="field-hint">{item.timestamp}</span>
                  </div>
                  <Button variant="ghost" onClick={() => handleCopy(item.translated)}>
                    <Copy size={16} />
                    Sao chép
                  </Button>
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

      <Dialog
        open={confirmClearHistory}
        title="Xoá toàn bộ lịch sử dịch?"
        description="Hành động này sẽ xoá danh sách các bản dịch gần đây trong phiên hiện tại."
        confirmLabel="Xoá lịch sử"
        danger
        onClose={() => setConfirmClearHistory(false)}
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
