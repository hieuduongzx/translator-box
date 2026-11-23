import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import type { ToastItem } from "../../hooks/useToast";

export interface ToastProps {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}

export function Toast({ toasts, onDismiss }: ToastProps) {
  if (toasts.length === 0) return null;

  const iconFor = (kind: ToastItem["kind"]) => {
    switch (kind) {
      case "success":
        return <CheckCircle2 size={16} color="var(--success)" />;
      case "warning":
        return <AlertTriangle size={16} color="var(--warning)" />;
      case "error":
        return <XCircle size={16} color="var(--danger)" />;
      default:
        return <Info size={16} color="var(--accent)" />;
    }
  };

  return (
    <div className="ui-toast-stack" role="status" aria-live="polite">
      {toasts.map((item) => (
        <div key={item.id} className={`ui-toast ${item.kind}`}>
          <span className="ui-toast-icon">{iconFor(item.kind)}</span>
          <div className="ui-toast-content">
            <div className="ui-toast-title">{item.title}</div>
            {item.description && <div className="ui-toast-desc">{item.description}</div>}
          </div>
          <button
            type="button"
            className="ui-toast-close"
            title="Đóng thông báo"
            aria-label="Đóng thông báo"
            onClick={() => onDismiss(item.id)}
          >
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
