import { useCallback, useEffect, useRef, useState } from "react";

export type ToastKind = "info" | "success" | "warning" | "error";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
}

export interface UseToastResult {
  toasts: ToastItem[];
  showToast: (kind: ToastKind, title: string, description?: string, durationMs?: number) => number;
  dismissToast: (id: number) => void;
  clearToasts: () => void;
}

let nextToastId = 1;

export function useToast(maxVisible = 4, defaultDurationMs = 4500): UseToastResult {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<number, number>>(new Map());

  const dismissToast = useCallback((id: number) => {
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const clearToasts = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current.clear();
    setToasts([]);
  }, []);

  const showToast = useCallback(
    (kind: ToastKind, title: string, description?: string, durationMs = defaultDurationMs) => {
      const id = nextToastId++;
      setToasts((prev) => {
        const next = [...prev, { id, kind, title, description }];
        if (next.length <= maxVisible) return next;
        const removed = next.slice(0, next.length - maxVisible);
        for (const r of removed) {
          const t = timersRef.current.get(r.id);
          if (t !== undefined) {
            window.clearTimeout(t);
            timersRef.current.delete(r.id);
          }
        }
        return next.slice(-maxVisible);
      });

      if (durationMs > 0) {
        const timer = window.setTimeout(() => {
          timersRef.current.delete(id);
          setToasts((prev) => prev.filter((item) => item.id !== id));
        }, durationMs);
        timersRef.current.set(id, timer);
      }

      return id;
    },
    [defaultDurationMs, maxVisible],
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      timers.clear();
    };
  }, []);

  return { toasts, showToast, dismissToast, clearToasts };
}
