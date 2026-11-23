import React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { formatBytes, UseUpdaterResult } from "../../hooks/useUpdater";

export interface UpdateSettingsCardProps {
  appName: string;
  updater: UseUpdaterResult;
  currentVersion?: string;
}

function formatCheckedAt(iso: string | null): string {
  if (!iso) return "Chưa kiểm tra";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Chưa kiểm tra";
  return d.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export const UpdateSettingsCard: React.FC<UpdateSettingsCardProps> = ({
  appName,
  updater,
  currentVersion,
}) => {
  const { state, percent } = updater;
  const checking = state?.status === "checking";
  const downloading = state?.status === "downloading";
  const verifying = state?.status === "verifying";
  const ready = state?.status === "ready";
  const available = state?.status === "available";
  const installing = state?.status === "installing";
  const busy = checking || downloading || verifying || installing;

  const kindLabel = state?.detectedKind === "installer" ? "Bản cài đặt" : "Bản Portable";
  const currentVer = currentVersion || state?.currentVersion || "—";
  const latestVer =
    state?.available?.version ||
    (state?.status === "up-to-date" ? currentVer : null);

  return (
    <div className="ui-card updater-settings-card" data-app-name={appName}>
      <div className="updater-settings-header">
        <div>
          <div className="updater-settings-title">Cập nhật</div>
          <div className="updater-settings-subtitle">
            Kiểm tra và tải bản mới trực tiếp từ Cloudflare R2, có xác minh SHA-256 và chữ ký số.
          </div>
        </div>
        <div className="updater-settings-badges">
          <span className="updater-pill updater-pill-info">
            Hiện tại: v{currentVer}
          </span>
          {latestVer && (
            <span className="updater-pill updater-pill-muted">
              Mới nhất: v{latestVer}
            </span>
          )}
          <span className="updater-pill updater-pill-muted">{kindLabel}</span>
        </div>
      </div>

      <div className="updater-toggle-row">
        <div className="updater-toggle-info">
          <div className="updater-toggle-label">Tự động cập nhật</div>
          <div className="updater-toggle-desc">
            Tự kiểm tra khi mở ứng dụng và định kỳ mỗi 6 giờ, tải sẵn bản mới ở chế độ nền.
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={state?.autoUpdate ?? true}
          aria-label="Bật hoặc tắt tự động cập nhật"
          className={`updater-switch ${(state?.autoUpdate ?? true) ? "on" : ""}`}
          onClick={() => updater.setAutoUpdate(!(state?.autoUpdate ?? true))}
        >
          <span className="updater-switch-thumb" />
        </button>
      </div>

      <div className="updater-status-box">
        <div className="updater-status-line">
          {checking && (
            <>
              <Loader2 size={16} className="updater-spin" />
              <span>Đang kiểm tra bản cập nhật mới...</span>
            </>
          )}
          {state?.status === "up-to-date" && (
            <>
              <CheckCircle2 size={16} color="var(--success)" />
              <span>Bạn đang dùng phiên bản mới nhất (v{state.currentVersion}).</span>
            </>
          )}
          {state?.status === "idle" && (
            <>
              <Clock size={16} color="var(--text-muted)" />
              <span>Nhấn "Kiểm tra cập nhật" để kiểm tra ngay.</span>
            </>
          )}
          {available && state?.available && (
            <>
              <Download size={16} color="var(--accent)" />
              <span>
                Có bản mới <strong>v{state.available.version}</strong> (
                {formatBytes(state.available.size)})
              </span>
            </>
          )}
          {downloading && state?.available && (
            <>
              <Loader2 size={16} className="updater-spin" color="var(--accent)" />
              <span className="tabular">
                Đang tải v{state.available.version}: {percent}% ({formatBytes(state.downloadedBytes)}{" "}
                / {formatBytes(state.totalBytes)}
                {state.speedBps > 0 ? ` · ${formatBytes(state.speedBps)}/s` : ""})
              </span>
            </>
          )}
          {verifying && (
            <>
              <Loader2 size={16} className="updater-spin" color="var(--accent)" />
              <span>Đang kiểm tra mã băm SHA-256 và chữ ký số...</span>
            </>
          )}
          {ready && state?.available && (
            <>
              <CheckCircle2 size={16} color="var(--success)" />
              <span>
                Đã tải xong <strong>v{state.available.version}</strong> —{" "}
                {state.installOnExit
                  ? "sẽ tự cài đặt khi thoát ứng dụng."
                  : "sẵn sàng khởi động lại để cập nhật."}
              </span>
            </>
          )}
          {installing && (
            <>
              <Loader2 size={16} className="updater-spin" color="var(--accent)" />
              <span>Đang cài đặt bản cập nhật...</span>
            </>
          )}
          {state?.status === "error" && (
            <>
              <AlertTriangle size={16} color="var(--danger)" />
              <span style={{ color: "var(--danger)" }}>{state.error}</span>
            </>
          )}
        </div>

        {downloading && (
          <div className="updater-progress-track">
            <div className="updater-progress-fill" style={{ width: `${percent}%` }} />
          </div>
        )}

        {state?.available?.notes && state.available.notes.length > 0 && (
          <ul className="updater-notes-list updater-notes-in-card">
            {state.available.notes.map((line, idx) => (
              <li key={idx}>{line}</li>
            ))}
          </ul>
        )}

        <div className="updater-status-footer">
          <span className="updater-last-checked">
            Kiểm tra lần cuối: {formatCheckedAt(state?.lastCheckedAt ?? null)}
          </span>
          <div className="updater-settings-actions">
            <button
              type="button"
              className="updater-btn updater-btn-secondary"
              disabled={busy}
              onClick={() => updater.checkForUpdates(state?.autoUpdate ?? true)}
            >
              <RefreshCw size={16} className={checking ? "updater-spin" : ""} />
              Kiểm tra cập nhật
            </button>

            {available && (
              <button
                type="button"
                className="updater-btn updater-btn-primary"
                onClick={() => updater.downloadUpdate()}
              >
                <Download size={16} /> Tải v{state?.available?.version}
              </button>
            )}

            {downloading && (
              <button
                type="button"
                className="updater-btn updater-btn-secondary"
                onClick={() => updater.cancelDownload()}
              >
                Hủy tải
              </button>
            )}

            {ready && (
              <>
                <button
                  type="button"
                  className="updater-btn updater-btn-secondary"
                  onClick={() => updater.setInstallOnExit(!state?.installOnExit)}
                >
                  <Clock size={16} />
                  {state?.installOnExit ? "Đã hẹn cài khi thoát" : "Cài khi thoát"}
                </button>
                <button
                  type="button"
                  className="updater-btn updater-btn-primary"
                  onClick={() => updater.installNow(true)}
                >
                  <RefreshCw size={16} /> Khởi động lại để cập nhật
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
