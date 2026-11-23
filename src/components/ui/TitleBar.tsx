import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, Copy, X } from "lucide-react";
import type { StatusEvent } from "../../types";

export interface TitleBarProps {
  title: string;
  iconSrc?: string;
  status?: StatusEvent;
}

export function TitleBar({ title, iconSrc = "/icon.png", status }: TitleBarProps) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    const win = getCurrentWindow();
    win.isMaximized().then(setMaximized).catch(() => {});
    const unlisten = win.onResized(() => {
      win.isMaximized().then(setMaximized).catch(() => {});
    });
    return () => {
      unlisten.then((fn) => fn()).catch(() => {});
    };
  }, []);

  const handleMinimize = () => getCurrentWindow().minimize();
  const handleToggleMax = async () => {
    const win = getCurrentWindow();
    await win.toggleMaximize();
    setMaximized(await win.isMaximized());
  };
  const handleClose = () => getCurrentWindow().close();

  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="titlebar-left" data-tauri-drag-region>
        <img src={iconSrc} alt="" className="titlebar-icon" data-tauri-drag-region />
        <span className="titlebar-title" data-tauri-drag-region>
          {title}
        </span>
        {status && (
          <span className="titlebar-status" data-tauri-drag-region>
            <span className={`status-dot ${status.state}`} />
            <span>{status.text}</span>
          </span>
        )}
      </div>
      <div className="titlebar-controls">
        <button
          type="button"
          className="titlebar-btn"
          onClick={handleMinimize}
          aria-label="Thu nhỏ"
          title="Thu nhỏ"
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          className="titlebar-btn"
          onClick={handleToggleMax}
          aria-label={maximized ? "Khôi phục" : "Phóng to"}
          title={maximized ? "Khôi phục" : "Phóng to"}
        >
          {maximized ? <Copy size={16} /> : <Square size={16} />}
        </button>
        <button
          type="button"
          className="titlebar-btn close"
          onClick={handleClose}
          aria-label="Đóng xuống khay hệ thống"
          title="Ẩn xuống khay hệ thống"
        >
          <X size={16} />
        </button>
      </div>
    </header>
  );
}
