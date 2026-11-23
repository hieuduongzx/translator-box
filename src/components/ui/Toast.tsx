import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";

export type ToastType = "info" | "success" | "warning" | "error";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

let nextToastId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = nextToastId++;
      setItems((prev) => [...prev.slice(-4), { id, message, type }]);
      window.setTimeout(() => dismiss(id), 3600);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="ui-toast-container" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`ui-toast ${item.type}`}>
            <span style={{ display: "inline-flex", marginTop: 1, flexShrink: 0 }}>
              {item.type === "success" ? (
                <CheckCircle2 size={16} color="var(--success)" />
              ) : item.type === "error" ? (
                <AlertCircle size={16} color="var(--danger)" />
              ) : item.type === "warning" ? (
                <AlertCircle size={16} color="var(--warning)" />
              ) : (
                <Info size={16} color="var(--accent)" />
              )}
            </span>
            <span style={{ flex: 1 }}>{item.message}</span>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
              }}
              aria-label="Đóng thông báo"
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
