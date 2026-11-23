import { useEffect } from "react";
import { CheckCircle2, Cpu, Download, Loader2, RefreshCw, ScanText, X } from "lucide-react";
import { Button, Card, Select } from "../components/ui";
import { OCR_BACKENDS, OCR_ENGINES, OCR_LANGUAGES, pairsToOptions } from "../lib/constants";
import { appActions, useAppSlice } from "../store/appStore";
import type { AppConfig } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
}

function formatMb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function OcrPage({ config, onUpdateConfig }: Props) {
  const {
    status,
    models,
    checking,
    downloadingId,
    cancellingDownload,
    downloadProgress,
    downloadError,
  } = useAppSlice("ocr");

  useEffect(() => {
    void appActions.refreshOcr({
      ocr_engine: config.ocr_engine,
      ocr_model: config.ocr_model,
      ocr_backend: config.ocr_backend,
    });
  }, [config.ocr_engine, config.ocr_model, config.ocr_backend]);

  const handleRefresh = () => {
    void appActions.refreshOcr(
      {
        ocr_engine: config.ocr_engine,
        ocr_model: config.ocr_model,
        ocr_backend: config.ocr_backend,
      },
      true
    );
  };

  const handleDownload = (modelId: string) => {
    void appActions.downloadOcrModel(modelId, {
      ocr_engine: config.ocr_engine,
      ocr_model: config.ocr_model,
      ocr_backend: config.ocr_backend,
    });
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
          <Button variant="secondary" disabled={checking} onClick={handleRefresh}>
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
            <Select
              aria-label="Bộ máy OCR"
              value={config.ocr_engine}
              onChange={(v) => onUpdateConfig({ ocr_engine: v as AppConfig["ocr_engine"] })}
              options={OCR_ENGINES.map((eng) => ({ value: eng.value, label: eng.label, description: eng.desc }))}
            />
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
            <Select
              aria-label="Ngôn ngữ OCR"
              value={config.ocr_language}
              onChange={(v) => onUpdateConfig({ ocr_language: v })}
              options={pairsToOptions(OCR_LANGUAGES)}
            />
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
            <Select
              aria-label="Thiết bị chạy OCR"
              value={config.ocr_backend}
              onChange={(v) => onUpdateConfig({ ocr_backend: v })}
              options={pairsToOptions(OCR_BACKENDS)}
            />
          </div>
        </div>

        {status && (
          <div className="row-8 field-hint" style={{ paddingTop: 12 }}>
            <Cpu size={16} />
            <span>{status.detail}</span>
          </div>
        )}
      </Card>

      {downloadError && !downloadingId && (
        <Card>
          <span style={{ color: "var(--danger)", fontWeight: 500 }}>{downloadError}</span>
        </Card>
      )}

      <Card
        title="Mô hình OCR ngoại tuyến (ONNX)"
        description="Chọn và tải mô hình PP-OCR lưu tại ~/.screen-translator-2k/models/rapidocr."
      >
        <div className="stack-8">
          {models.map((m) => {
            const selected = config.ocr_model === m.id;
            const isDownloading = downloadingId === m.id;
            const prog = isDownloading && downloadProgress?.modelId === m.id ? downloadProgress : null;
            const pct = prog ? Math.min(100, Math.max(0, Math.round(prog.percent))) : 0;

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
                      {isDownloading && (
                        <span className="badge accent">
                          <Loader2 size={14} className="ui-spin" />
                          {pct > 0 ? `Đang tải ${pct}%` : "Đang tải…"}
                        </span>
                      )}
                    </div>
                    <div className="field-hint">{m.languages}</div>
                  </div>
                  <div className="row-8">
                    {isDownloading ? (
                      <Button
                        variant="ghost"
                        disabled={cancellingDownload}
                        onClick={() => appActions.cancelOcrDownload()}
                      >
                        <X size={16} />
                        {cancellingDownload ? "Đang huỷ…" : "Huỷ tải"}
                      </Button>
                    ) : (
                      !m.installed && (
                        <Button
                          variant="secondary"
                          disabled={Boolean(downloadingId)}
                          onClick={() => handleDownload(m.id)}
                        >
                          <Download size={16} />
                          Tải model
                        </Button>
                      )
                    )}
                    <Button
                      variant={selected ? "primary" : "secondary"}
                      onClick={() => onUpdateConfig({ ocr_model: m.id })}
                    >
                      {selected ? "Đang chọn" : "Chọn"}
                    </Button>
                  </div>
                </div>

                {isDownloading && prog && (
                  <div className="task-progress-box">
                    <div className="task-progress-meta">
                      <span>
                        Tệp {prog.fileIndex}/{prog.fileTotal} · {prog.currentFile}
                      </span>
                      <span>
                        {prog.totalBytes > 0
                          ? `${formatMb(prog.downloadedBytes)} / ${formatMb(prog.totalBytes)} (${pct}%)`
                          : `${pct}%`}
                      </span>
                    </div>
                    <div className="task-progress-track">
                      <div className="task-progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
