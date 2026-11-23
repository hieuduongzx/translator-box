import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Download,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { formatBytes, UseUpdaterResult } from "../../hooks/useUpdater";

export interface UpdateBannerProps {
  appName: string;
  updater: UseUpdaterResult;
}

export const UpdateBanner: React.FC<UpdateBannerProps> = ({ appName, updater }) => {
  const { state, percent, bannerDismissed } = updater;
  const [showNotes, setShowNotes] = useState(false);

  if (!state || bannerDismissed) return null;

  const visibleStatuses = new Set([
    "available",
    "downloading",
    "verifying",
    "ready",
    "installing",
    "error",
  ]);
  if (!visibleStatuses.has(state.status)) return null;
  if (state.status === "error" && !state.available && !state.error) return null;

  const ver = state.available?.version;
  const notes = state.available?.notes ?? [];
  const toneClass =
    state.status === "ready"
      ? "updater-banner-ready"
      : state.status === "error"
        ? "updater-banner-error"
        : "updater-banner-info";

  return (
    <div className={`updater-banner ${toneClass}`} role="status" aria-live="polite">
      <div className="updater-banner-row">
        <div className="updater-banner-main">
          <span className="updater-banner-icon">
            {state.status === "ready" ? (
              <CheckCircle2 size={16} />
            ) : state.status === "error" ? (
              <AlertTriangle size={16} />
            ) : state.status === "downloading" ||
              state.status === "verifying" ||
              state.status === "installing" ? (
              <Loader2 size={16} className="updater-spin" />
            ) : (
              <Download size={16} />
            )}
          </span>

          <div className="updater-banner-text">
            {state.status === "available" && (
              <>
                <strong>
                  Có bản cập nhật mới {appName} v{ver}
                </strong>
                <span className="updater-banner-meta">
                  Hiện tại: v{state.currentVersion}
                  {state.available?.size ? ` · ${formatBytes(state.available.size)}` : ""}
                </span>
              </>
            )}

            {state.status === "downloading" && (
              <>
                <strong>
                  Đang tải nền {appName} v{ver} ({percent}%)
                </strong>
                <span className="updater-banner-meta tabular">
                  {formatBytes(state.downloadedBytes)} / {formatBytes(state.totalBytes)}
                  {state.speedBps > 0 ? ` · ${formatBytes(state.speedBps)}/s` : ""}
                </span>
              </>
            )}

            {state.status === "verifying" && (
              <>
                <strong>Đang kiểm tra tệp cập nhật v{ver}...</strong>
                <span className="updater-banner-meta">Đang xác minh tính toàn vẹn trước khi cài đặt</span>
              </>
            )}

            {state.status === "ready" && (
              <>
                <strong>
                  Đã tải xong {appName} v{ver}
                </strong>
                <span className="updater-banner-meta">
                  {state.installOnExit
                    ? "Đã hẹn tự động cài đặt khi bạn đóng ứng dụng"
                    : "Sẵn sàng cập nhật an toàn — không mất cài đặt"}
                </span>
              </>
            )}

            {state.status === "installing" && (
              <>
                <strong>Đang áp dụng bản cập nhật v{ver}...</strong>
                <span className="updater-banner-meta">Ứng dụng sẽ tự khởi động lại trong giây lát</span>
              </>
            )}

            {state.status === "error" && (
              <>
                <strong>Không thể cập nhật</strong>
                <span className="updater-banner-meta">{state.error}</span>
              </>
            )}
          </div>
        </div>

        <div className="updater-banner-actions">
          {notes.length > 0 && state.status !== "installing" && (
            <button
              type="button"
              className="updater-btn updater-btn-ghost"
              onClick={() => setShowNotes((v) => !v)}
            >
              {showNotes ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              Chi tiết
            </button>
          )}

          {state.status === "available" && (
            <button
              type="button"
              className="updater-btn updater-btn-primary"
              onClick={() => updater.downloadUpdate()}
            >
              <Download size={16} /> Tải ngay
            </button>
          )}

          {state.status === "downloading" && (
            <button
              type="button"
              className="updater-btn updater-btn-secondary"
              onClick={() => updater.cancelDownload()}
            >
              Hủy
            </button>
          )}

          {state.status === "ready" && (
            <>
              <button
                type="button"
                className="updater-btn updater-btn-secondary"
                onClick={() => updater.setInstallOnExit(!state.installOnExit)}
                title="Tự động cập nhật khi bạn đóng ứng dụng"
              >
                <Clock size={16} />
                {state.installOnExit ? "Đã hẹn cài khi thoát" : "Cài khi thoát"}
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

          {state.status === "error" && (
            <button
              type="button"
              className="updater-btn updater-btn-secondary"
              onClick={() =>
                state.available ? updater.downloadUpdate() : updater.checkForUpdates(true)
              }
            >
              <RefreshCw size={16} /> Thử lại
            </button>
          )}

          {state.status !== "installing" && state.status !== "verifying" && (
            <button
              type="button"
              className="updater-icon-close"
              onClick={updater.dismissBanner}
              title="Ẩn thông báo"
              aria-label="Ẩn thông báo cập nhật"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {state.status === "downloading" && (
        <div className="updater-progress-track" aria-label="Tiến độ tải cập nhật">
          <div className="updater-progress-fill" style={{ width: `${percent}%` }} />
        </div>
      )}

      {showNotes && notes.length > 0 && (
        <ul className="updater-notes-list">
          {notes.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
};
