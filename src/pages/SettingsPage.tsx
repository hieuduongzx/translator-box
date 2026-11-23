import { useEffect, useState } from "react";
import { open as openExternal } from "@tauri-apps/plugin-shell";
import {
  Download,
  ExternalLink,
  Monitor,
  Moon,
  RefreshCw,
  Settings,
  Sun,
} from "lucide-react";
import { Button, Card, Dialog, Toggle, useToast } from "../components/ui";
import { api } from "../lib/api";
import { LANGUAGES } from "../lib/constants";
import type { AppConfig, AppMeta, ReleaseInfo } from "../types";

interface Props {
  config: AppConfig;
  meta: AppMeta | null;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
}

export function SettingsPage({ config, meta, onUpdateConfig }: Props) {
  const { toast } = useToast();
  const [checking, setChecking] = useState(false);
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<{ downloaded: number; total: number } | null>(null);
  const [confirmInstall, setConfirmInstall] = useState(false);

  useEffect(() => {
    const unlisten = api.onUpdateProgress((p) => setProgress(p));
    return () => {
      unlisten.then((fn) => fn()).catch(() => {});
    };
  }, []);

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
            Giao diện chung, tuỳ chọn tự động dịch và kiểm tra cập nhật ứng dụng.
          </p>
        </div>
      </div>

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

      <Card title="Hành vi dịch mặc định">
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
            <span className="field-label">Ngôn ngữ đích mặc định</span>
            <span className="field-hint">Dùng cho OCR vùng màn hình, Live và tự dịch clipboard.</span>
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

        <div className="field-row">
          <div className="field-meta">
            <span className="field-label">Ngôn ngữ đích cho "Dịch & thay thế tại chỗ"</span>
            <span className="field-hint">
              Độc lập với ngôn ngữ đọc — mặc định sang Tiếng Anh để gõ chat/tìm kiếm nhanh.
            </span>
          </div>
          <select
            className="ui-select"
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
              {meta?.name ?? "Translator2k"} · v{meta?.version ?? "2.0.0"}
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
