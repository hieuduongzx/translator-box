import { useEffect, useState } from "react";
import { CheckCircle2, Cpu, Download, RefreshCw, ScanText } from "lucide-react";
import { Button, Card } from "../components/ui";
import type { ToastKind } from "../hooks";
import { api } from "../lib/api";
import { OCR_BACKENDS, OCR_ENGINES, OCR_LANGUAGES } from "../lib/constants";
import type { AppConfig, OcrEngineStatusInfo, OcrModelInfo } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onToast: (message: string, kind?: ToastKind) => void;
}

export function OcrPage({ config, onUpdateConfig, onToast: toast }: Props) {
  const [status, setStatus] = useState<OcrEngineStatusInfo | null>(null);
  const [models, setModels] = useState<OcrModelInfo[]>([]);
  const [checking, setChecking] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const refresh = async () => {
    setChecking(true);
    try {
      const [st, list] = await Promise.all([
        api.getOcrStatus(config.ocr_engine, config.ocr_model, config.ocr_backend),
        api.listOcrModels(),
      ]);
      setStatus(st);
      setModels(list);
    } catch {
      // ignore
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [config.ocr_engine, config.ocr_model, config.ocr_backend]);

  const handleDownload = async (modelId: string) => {
    setDownloadingId(modelId);
    try {
      const next = await api.downloadOcrModel(modelId);
      setModels(next);
      await refresh();
      toast("Đã tải xong model OCR ngoại tuyến", "success");
    } catch (err) {
      toast(String(err), "error");
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <ScanText size={24} />
            </span>
            <h1 className="page-title">Nhận dạng chữ (OCR)</h1>
          </div>
          <p className="page-subtitle">
            Chạy hoàn toàn ngoại tuyến bằng Windows OCR (WinRT) hoặc PP-OCRv5/v6 trên ONNX Runtime.
          </p>
        </div>
        <div className="page-header-actions">
          <Button variant="secondary" disabled={checking} onClick={refresh}>
            <RefreshCw size={16} className={checking ? "spin" : undefined} />
            {checking ? "Đang kiểm tra…" : "Kiểm tra trạng thái"}
          </Button>
        </div>
      </div>

      <Card
        title="Cấu hình bộ nhận dạng OCR"
        headerRight={
          status && (
            <span className={`badge ${status.available ? "success" : "warning"}`}>
              {status.available ? "Sẵn sàng" : "Cần tải mô hình"}
            </span>
          )
        }
      >
        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Bộ nhận dạng</span>
            <span className="field-hint">
              {OCR_ENGINES.find((e) => e.value === config.ocr_engine)?.desc}
            </span>
          </div>
          <div className="field-control">
            <select
              className="ui-select"
              value={config.ocr_engine}
              onChange={(e) =>
                onUpdateConfig({ ocr_engine: e.target.value as AppConfig["ocr_engine"] })
              }
            >
              {OCR_ENGINES.map((eng) => (
                <option key={eng.value} value={eng.value}>
                  {eng.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Ngôn ngữ chữ nguồn (Windows OCR)</span>
            <span className="field-hint">
              Áp dụng khi dùng Windows OCR; mô hình ONNX đa ngôn ngữ tự nhận diện nhiều hệ chữ.
            </span>
          </div>
          <div className="field-control">
            <select
              className="ui-select"
              value={config.ocr_language}
              onChange={(e) => onUpdateConfig({ ocr_language: e.target.value })}
            >
              {OCR_LANGUAGES.map(([label, code]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Thiết bị xử lý ONNX</span>
            <span className="field-hint">
              DirectML tận dụng GPU Windows phổ thông; CPU ổn định trên mọi máy.
            </span>
          </div>
          <div className="field-control">
            <select
              className="ui-select"
              value={config.ocr_backend}
              onChange={(e) => onUpdateConfig({ ocr_backend: e.target.value })}
            >
              {OCR_BACKENDS.map(([label, val]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {status && (
          <div className="row-8 field-hint" style={{ paddingTop: 12 }}>
            <Cpu size={16} />
            <span>{status.detail}</span>
          </div>
        )}
      </Card>

      <Card
        title="Mô hình OCR ngoại tuyến (ONNX)"
        description="Chọn và tải mô hình PP-OCR lưu tại ~/.screen-translator-2k/models/rapidocr."
      >
        <div className="stack-8">
          {models.map((m) => {
            const selected = config.ocr_model === m.id;
            const isDownloading = downloadingId === m.id;
            return (
              <div
                key={m.id}
                className="history-item"
                style={{
                  borderColor: selected ? "var(--accent)" : undefined,
                }}
              >
                <div className="row-8" style={{ justifyContent: "space-between" }}>
                  <div>
                    <div className="row-8">
                      <strong>{m.label}</strong>
                      <span className="kbd">~{m.size_mb} MB</span>
                      {m.installed && (
                        <span className="badge success">
                          <CheckCircle2 size={16} /> Đã cài
                        </span>
                      )}
                    </div>
                    <div className="field-hint">{m.languages}</div>
                  </div>
                  <div className="row-8">
                    {!m.installed && (
                      <Button
                        variant="secondary"
                        disabled={Boolean(downloadingId)}
                        onClick={() => handleDownload(m.id)}
                      >
                        <Download size={16} />
                        {isDownloading ? "Đang tải…" : "Tải model"}
                      </Button>
                    )}
                    <Button
                      variant={selected ? "primary" : "secondary"}
                      onClick={() => onUpdateConfig({ ocr_model: m.id })}
                    >
                      {selected ? "Đang chọn" : "Chọn"}
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
