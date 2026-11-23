import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button, type ButtonVariant } from "./Button";

export interface DialogProps {
  open: boolean;
  title: string;
  description?: string;
  wide?: boolean;
  maxWidth?: number;
  disableClose?: boolean;
  onClose: () => void;
  footer?: ReactNode;
  children?: ReactNode;
}

export function Dialog({
  open,
  title,
  description,
  wide = false,
  maxWidth,
  disableClose = false,
  onClose,
  footer,
  children,
}: DialogProps) {
  useEffect(() => {
    if (!open || disableClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, disableClose, onClose]);

  if (!open) return null;

  const handleClose = () => {
    if (!disableClose) onClose();
  };

  return (
    <div
      className="ui-dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        className={`ui-dialog${wide ? " wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={maxWidth ? { maxWidth } : undefined}
      >
        <div className="ui-dialog-header">
          <div>
            <h2 className="ui-dialog-title">{title}</h2>
            {description && <p className="ui-dialog-desc">{description}</p>}
          </div>
          <Button
            variant="ghost"
            iconOnly
            disabled={disableClose}
            onClick={handleClose}
            title="Đóng"
            aria-label="Đóng hộp thoại"
          >
            <X size={16} />
          </Button>
        </div>

        {children && <div className="ui-dialog-body">{children}</div>}
        {footer && <div className="ui-dialog-footer">{footer}</div>}
      </div>
    </div>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: ButtonVariant;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Xác nhận",
  cancelLabel = "Hủy",
  confirmVariant = "danger",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      title={title}
      disableClose={loading}
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" disabled={loading} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button variant={confirmVariant} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="ui-confirm-msg">{message}</div>
    </Dialog>
  );
}
