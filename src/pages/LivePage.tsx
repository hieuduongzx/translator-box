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
import { Button, Card, Dialog, useToast } from "../components/ui";
import { api } from "../lib/api";
import { LIVE_TRIGGER_MODES, formatHotkey } from "../lib/constants";
import type { AppConfig, DesktopApplication, LiveStatePayload } from "../types";

interface Props {
  config: AppConfig;
  liveState: LiveStatePayload;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onLiveStateChange: (state: LiveStatePayload) => void;
}

export function LivePage({
  config,
  liveState,
  onUpdateConfig,
  onLiveStateChange,
}: Props) {
  const { toast } = useToast();
  const [apps, setApps] = useState<DesktopApplication[]>([]);
  const [loadingApps, setLoadingApps] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [deleteRegionTarget, setDeleteRegionTarget] = useState<{ id: number; index: number } | null>(
    null
  );

  const actionTip = (desc: string, action: string) => {
    const raw = config.hotkeys[action]?.trim() || "";
    return raw ? `${desc} · Phím tắt: ${formatHotkey(raw)}` : desc;
  };

  const refreshApps = async () => {
    setLoadingApps(true);
    try {
      const list = await api.listDesktopApps();
      setApps(list);
    } catch {
      // ignore
    } finally {
      setLoadingApps(false);
    }
  };

  useEffect(() => {
    refreshApps();
  }, []);

  const handleAddRegion = async (mode: "overlay" | "frame") => {
    try {
      const added = await api.liveAddRegion(mode);
      if (added) {
        const next = await api.getLiveState();
        onLiveStateChange(next);
        if (mode === "frame") {
          await api.openLiveOutputWindow(added.id, added.bbox);
        }
        toast(
          mode === "overlay" ? "Đã thêm vùng Live Overlay" : "Đã thêm vùng Live Khung nổi",
          "success"
        );
      }
    } catch (err) {
      toast(String(err), "error");
    }
  };

  const handleToggleRun = async () => {
    try {
      if (liveState.running) {
        const st = await api.liveStop();
        onLiveStateChange(st);
        toast("Đã dừng dịch Live", "info");
      } else {
        for (const r of liveState.regions) {
          if (r.mode === "frame") {
            await api.openLiveOutputWindow(r.id, r.bbox);
          }
        }
        const st = await api.liveStart();
        onLiveStateChange(st);
        toast("Đã bắt đầu dịch Live", "success");
      }
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
            disabled={liveState.regions.length === 0}
            data-tip={actionTip("Bắt đầu hoặc dừng dịch Live trên mọi vùng", "live_toggle")}
            data-tip-pos="bottom"
            data-tip-align="right"
            title={actionTip("Bắt đầu hoặc dừng dịch Live trên mọi vùng", "live_toggle")}
            onClick={handleToggleRun}
          >
            {liveState.running ? <Square size={16} /> : <Play size={16} />}
            {liveState.running ? "Dừng Live" : "Bắt đầu Live"}
          </Button>
          {liveState.running && (
            <Button
              variant="secondary"
              data-tip={actionTip("Ép OCR và dịch lại ngay mọi vùng Live", "live_rescan")}
              data-tip-pos="bottom"
              data-tip-align="right"
              title={actionTip("Ép OCR và dịch lại ngay mọi vùng Live", "live_rescan")}
              onClick={async () => {
                await api.liveRescan();
                toast("Đang quét lại toàn bộ vùng Live…", "info");
              }}
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
              data-tip={actionTip("Kéo chọn thêm vùng dịch liên tục kiểu overlay tại chỗ", "region_to_live")}
              data-tip-align="right"
              title={actionTip("Kéo chọn thêm vùng dịch liên tục kiểu overlay tại chỗ", "region_to_live")}
              onClick={() => handleAddRegion("overlay")}
            >
              <Plus size={16} />
              Thêm Overlay
            </Button>
            <Button
              variant="secondary"
              data-tip={actionTip("Kéo chọn thêm vùng dịch liên tục hiện ở khung nổi riêng", "region_to_live_frame")}
              data-tip-align="right"
              title={actionTip("Kéo chọn thêm vùng dịch liên tục hiện ở khung nổi riêng", "region_to_live_frame")}
              onClick={() => handleAddRegion("frame")}
            >
              <AppWindow size={16} />
              Thêm Khung
            </Button>
            {liveState.regions.length > 0 && (
              <Button variant="ghost" onClick={() => setConfirmClear(true)}>
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
                        onClick={async () => {
                          try {
                            const st = await api.liveEditRegion(region.id);
                            onLiveStateChange(st);
                          } catch (err) {
                            toast(String(err), "error");
                          }
                        }}
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
          <select
            className="ui-select"
            value={config.live_trigger_mode}
            onChange={(e) =>
              onUpdateConfig({
                live_trigger_mode: e.target.value as AppConfig["live_trigger_mode"],
              })
            }
          >
            {LIVE_TRIGGER_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
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
            <select
              className="ui-select"
              style={{ width: 240 }}
              value={config.live_focus_app_id}
              onChange={(e) => {
                const selected = apps.find((a) => a.application_id === e.target.value);
                onUpdateConfig({
                  live_focus_app_id: e.target.value,
                  live_focus_app_label: selected?.label ?? "",
                });
              }}
            >
              <option value="">Mọi ứng dụng (không giới hạn)</option>
              {apps.map((a) => (
                <option key={a.application_id} value={a.application_id}>
                  {a.label} — {a.title.slice(0, 32)}
                </option>
              ))}
            </select>
            <Button
              variant="secondary"
              iconOnly
              disabled={loadingApps}
              onClick={refreshApps}
              title="Làm mới danh sách ứng dụng"
              aria-label="Làm mới danh sách ứng dụng"
            >
              <RefreshCw size={16} className={loadingApps ? "spin" : undefined} />
            </Button>
          </div>
        </div>
      </Card>

      <Dialog
        open={Boolean(deleteRegionTarget)}
        title={`Xoá vùng Live #${deleteRegionTarget?.index}?`}
        description="Vùng này và lớp phủ bản dịch tương ứng sẽ bị gỡ khỏi danh sách Live."
        confirmLabel="Xoá vùng"
        danger
        onClose={() => setDeleteRegionTarget(null)}
        onConfirm={async () => {
          if (!deleteRegionTarget) return;
          const st = await api.liveRemoveRegion(deleteRegionTarget.id);
          onLiveStateChange(st);
          toast(`Đã xoá vùng #${deleteRegionTarget.index}`, "info");
          setDeleteRegionTarget(null);
        }}
      />

      <Dialog
        open={confirmClear}
        title="Xoá toàn bộ vùng Live?"
        description="Tất cả các vùng Live đã lưu và lớp phủ liên quan sẽ bị xoá."
        confirmLabel="Xoá tất cả"
        danger
        onClose={() => setConfirmClear(false)}
        onConfirm={async () => {
          const st = await api.liveClearRegions();
          onLiveStateChange(st);
          setConfirmClear(false);
          toast("Đã xoá toàn bộ vùng Live", "info");
        }}
      />
    </div>
  );
}
