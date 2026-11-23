import { useEffect, useState, type ReactNode } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Copy, Minus, Square, X } from "lucide-react";

export interface TitleBarProps {
  title: string;
  subtitle?: string;
  iconSrc?: string;
  center?: ReactNode;
  rightContent?: ReactNode;
  closeTooltip?: string;
  onClose?: () => void;
}

export function TitleBar({
  title,
  subtitle,
  iconSrc = "/app-icon.png",
  center,
  rightContent,
  closeTooltip = "Đóng",
  onClose,
}: TitleBarProps) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    try {
      const win = getCurrentWindow();
      win.isMaximized().then(setMaximized).catch(() => {});
      win
        .onResized(() => {
          win.isMaximized().then(setMaximized).catch(() => {});
        })
        .then((fn) => {
          unlisten = fn;
        })
        .catch(() => {});
    } catch {
      // Running outside Tauri webview (e.g. browser dev preview)
    }
    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  const handleMinimize = () => {
    try {
      getCurrentWindow().minimize().catch(() => {});
    } catch {
      // ignore outside Tauri
    }
  };

  const handleToggleMaximize = () => {
    try {
      getCurrentWindow().toggleMaximize().catch(() => {});
    } catch {
      // ignore outside Tauri
    }
  };

  const handleClose = () => {
    if (onClose) {
      onClose();
      return;
    }
    try {
      getCurrentWindow().close().catch(() => {});
    } catch {
      // ignore outside Tauri
    }
  };

  return (
    <header className="ui-titlebar" data-tauri-drag-region>
      <div className="ui-titlebar-left" data-tauri-drag-region>
        {iconSrc && (
          <img
            src={iconSrc}
            alt=""
            width={20}
            height={20}
            draggable={false}
            className="ui-titlebar-icon"
            data-tauri-drag-region
          />
        )}
        <span className="ui-titlebar-title" data-tauri-drag-region>
          {title}
        </span>
        {subtitle && (
          <span className="ui-titlebar-subtitle" data-tauri-drag-region>
            {subtitle}
          </span>
        )}
      </div>

      {center ? (
        <div className="ui-titlebar-center" data-tauri-drag-region>
          {center}
        </div>
      ) : (
        <div className="ui-titlebar-center" data-tauri-drag-region />
      )}

      {rightContent && <div className="ui-titlebar-right">{rightContent}</div>}

      <div className="ui-titlebar-controls">
        <button
          type="button"
          className="ui-titlebar-btn"
          title="Thu nhỏ"
          aria-label="Thu nhỏ cửa sổ"
          onClick={handleMinimize}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          className="ui-titlebar-btn"
          title={maximized ? "Khôi phục kích thước" : "Phóng to"}
          aria-label={maximized ? "Khôi phục kích thước cửa sổ" : "Phóng to cửa sổ"}
          onClick={handleToggleMaximize}
        >
          {maximized ? <Copy size={16} /> : <Square size={16} />}
        </button>
        <button
          type="button"
          className="ui-titlebar-btn ui-titlebar-btn-close"
          title={closeTooltip}
          aria-label={closeTooltip}
          onClick={handleClose}
        >
          <X size={16} />
        </button>
      </div>
    </header>
  );
}
