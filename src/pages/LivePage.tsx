import { useEffect, useState } from "react";
import {
  AppWindow,
  Layers,
  Move,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Scan,
  Square,
  Trash2,
} from "lucide-react";
import { Button, Card, ConfirmDialog, Select } from "../components/ui";
import { api } from "../lib/api";
import { LIVE_TRIGGER_MODES, formatHotkey } from "../lib/constants";
import { appActions, useAppSlice } from "../store/appStore";
import type { AppConfig } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
}

export function LivePage({ config, onUpdateConfig }: Props) {
  const { state: liveState, apps, loadingApps, busyAction } = useAppSlice("live");
  const [confirmClear, setConfirmClear] = useState(false);
  const [deleteRegionTarget, setDeleteRegionTarget] = useState<{ id: number; index: number } | null>(
    null
  );

  const actionTip = (desc: string, action: string) => {
    const raw = config.hotkeys[action]?.trim() || "";
    return raw ? `${desc} · Phím tắt: ${formatHotkey(raw)}` : desc;
  };

  useEffect(() => {
    void appActions.loadDesktopApps();
  }, []);

  const actionBusy = busyAction !== null;

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Radio size={24} />
            </span>
            <h1 className="page-title">Dịch Live đa vùng</h1>
          </div>
          <p className="page-subtitle">
            Theo dõi tối đa 12 vùng màn hình độc lập cho game, visual novel hoặc phụ đề phim.
          </p>
        </div>
        <div className="page-header-actions">
          <Button
            variant={liveState.running ? "danger" : "primary"}
            disabled={liveState.regions.length === 0 || actionBusy}
            data-tip={actionTip("Bắt đầu hoặc dừng dịch Live trên mọi vùng", "live_toggle")}
            data-tip-pos="bottom"
            data-tip-align="right"
            title={actionTip("Bắt đầu hoặc dừng dịch Live trên mọi vùng", "live_toggle")}
            onClick={() => void appActions.liveToggleRun()}
          >
            {liveState.running ? <Square size={16} /> : <Play size={16} />}
            {liveState.running ? "Dừng Live" : "Bắt đầu Live"}
          </Button>
          {liveState.running && (
            <Button
              variant="secondary"
              disabled={actionBusy}
              data-tip={actionTip("Ép OCR và dịch lại ngay mọi vùng Live", "live_rescan")}
              data-tip-pos="bottom"
              data-tip-align="right"
              title={actionTip("Ép OCR và dịch lại ngay mọi vùng Live", "live_rescan")}
              onClick={() => void appActions.liveRescan()}
            >
              <Scan size={16} />
              Quét lại ngay
            </Button>
          )}
        </div>
      </div>

      <Card
        title={`Danh sách vùng Live (${liveState.regions.length}/12)`}
        description={
          liveState.running
            ? liveState.paused_by_focus
              ? "Đang tạm nghỉ vì ứng dụng mục tiêu không ở tiền cảnh."
              : "Đang quét và dịch liên tục."
            : "Thêm vùng Overlay (vẽ đè chữ gốc) hoặc vùng Khung (cửa sổ phụ đề nổi riêng)."
        }
        headerRight={
          <div className="ui-card-header-actions">
            <Button
              variant="primary"
              disabled={actionBusy}
              data-tip={actionTip("Kéo chọn thêm vùng dịch liên tục kiểu overlay tại chỗ", "region_to_live")}
              data-tip-align="right"
              title={actionTip("Kéo chọn thêm vùng dịch liên tục kiểu overlay tại chỗ", "region_to_live")}
              onClick={() => void appActions.liveAddRegion("overlay")}
            >
              <Plus size={16} />
              Thêm Overlay
            </Button>
            <Button
              variant="secondary"
              disabled={actionBusy}
              data-tip={actionTip("Kéo chọn thêm vùng dịch liên tục hiện ở khung nổi riêng", "region_to_live_frame")}
              data-tip-align="right"
              title={actionTip("Kéo chọn thêm vùng dịch liên tục hiện ở khung nổi riêng", "region_to_live_frame")}
              onClick={() => void appActions.liveAddRegion("frame")}
            >
              <AppWindow size={16} />
              Thêm Khung
            </Button>
            {liveState.regions.length > 0 && (
              <Button variant="ghost" disabled={actionBusy} onClick={() => setConfirmClear(true)}>
                <Trash2 size={16} />
                Xoá tất cả
              </Button>
            )}
          </div>
        }
      >
        {liveState.regions.length === 0 ? (
          <div className="empty-state">
            <Radio size={20} />
            <span>
              Chưa có vùng Live nào. Nhấn &ldquo;Thêm Overlay&rdquo; hoặc &ldquo;Thêm Khung&rdquo; để kéo chọn trên màn hình.
            </span>
          </div>
        ) : (
          <div className="stack-8">
            {liveState.regions.map((region, idx) => {
              const [l, t, r, b] = region.bbox;
              return (
                <div key={region.id} className="history-item">
                  <div className="row-8" style={{ justifyContent: "space-between" }}>
                    <div className="row-8">
                      <strong>Vùng #{idx + 1}</strong>
                      <span className={`badge ${region.mode === "overlay" ? "accent" : "success"}`}>
                        {region.mode === "overlay" ? (
                          <>
                            <Layers size={16} /> Overlay tại chỗ
                          </>
                        ) : (
                          <>
                            <AppWindow size={16} /> Khung nổi
                          </>
                        )}
                      </span>
                      <span className="kbd">
                        {l},{t} · {r - l}×{b - t}px
                      </span>
                    </div>
                    <div className="row-8">
                      <Button
                        variant="secondary"
                        disabled={actionBusy}
                        onClick={() => void appActions.liveEditRegion(region.id)}
                      >
                        <Move size={16} />
                        Sửa vùng
                      </Button>
                      {region.mode === "frame" && (
                        <Button
                          variant="secondary"
                          onClick={() => api.openLiveOutputWindow(region.id, region.bbox)}
                        >
                          Hiện khung
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        iconOnly
                        disabled={actionBusy}
                        title={`Xoá vùng #${idx + 1}`}
                        aria-label={`Xoá vùng #${idx + 1}`}
                        onClick={() => setDeleteRegionTarget({ id: region.id, index: idx + 1 })}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>
                  {region.last_text && (
                    <div className="field-hint selectable-text">{region.last_text}</div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card title="Cấu hình quét Live">
        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Chế độ kích hoạt</span>
            <span className="field-hint">
              Hybrid vừa theo dõi thay đổi màn hình vừa quét ngay khi bấm chuột / Enter / Space.
            </span>
          </div>
          <Select
            aria-label="Chế độ kích hoạt"
            value={config.live_trigger_mode}
            onChange={(v) =>
              onUpdateConfig({
                live_trigger_mode: v as AppConfig["live_trigger_mode"],
              })
            }
            options={LIVE_TRIGGER_MODES}
          />
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Chu kỳ kiểm tra tự động (ms)</span>
            <span className="field-hint">Từ 300 ms đến 5000 ms (mặc định 900 ms).</span>
          </div>
          <input
            type="number"
            className="ui-input"
            style={{ width: 120 }}
            min={300}
            max={5000}
            step={100}
            value={config.live_interval_ms}
            onChange={(e) =>
              onUpdateConfig({ live_interval_ms: Number(e.target.value) || 900 })
            }
          />
        </div>

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Chỉ chạy khi ứng dụng đang focus</span>
            <span className="field-hint">
              Tự tạm dừng OCR khi bạn alt-tab sang cửa sổ khác để tiết kiệm CPU/API.
            </span>
          </div>
          <div className="field-control">
            <Select
              aria-label="Ứng dụng theo dõi"
              style={{ width: 240 }}
              value={config.live_focus_app_id}
              onChange={(v) => {
                const selected = apps.find((a) => a.application_id === v);
                onUpdateConfig({
                  live_focus_app_id: v,
                  live_focus_app_label: selected?.label ?? "",
                });
              }}
              options={[
                { value: "", label: "Mọi ứng dụng (không giới hạn)" },
                ...apps.map((a) => ({
                  value: a.application_id,
                  label: a.label,
                  description: a.title.slice(0, 60),
                })),
              ]}
            />
            <Button
              variant="secondary"
              iconOnly
              disabled={loadingApps}
              onClick={() => void appActions.loadDesktopApps(true)}
              title="Làm mới danh sách ứng dụng"
              aria-label="Làm mới danh sách ứng dụng"
            >
              <RefreshCw size={16} className={loadingApps ? "spin" : undefined} />
            </Button>
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={Boolean(deleteRegionTarget)}
        title={`Xoá vùng Live #${deleteRegionTarget?.index}?`}
        message="Vùng này và lớp phủ bản dịch tương ứng sẽ bị gỡ khỏi danh sách Live."
        confirmLabel="Xoá vùng"
        confirmVariant="danger"
        onCancel={() => setDeleteRegionTarget(null)}
        onConfirm={async () => {
          if (!deleteRegionTarget) return;
          const target = deleteRegionTarget;
          setDeleteRegionTarget(null);
          await appActions.liveRemoveRegion(target.id, target.index);
        }}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Xoá toàn bộ vùng Live?"
        message="Tất cả các vùng Live đã lưu và lớp phủ liên quan sẽ bị xoá."
        confirmLabel="Xoá tất cả"
        confirmVariant="danger"
        onCancel={() => setConfirmClear(false)}
        onConfirm={async () => {
          setConfirmClear(false);
          await appActions.liveClearRegions();
        }}
      />
    </div>
  );
}
