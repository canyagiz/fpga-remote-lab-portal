import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";

type ToastVariant = "error" | "success";

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  showError: (message: string) => void;
  showSuccess: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (message: string, variant: ToastVariant) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, message, variant }]);
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const showError = useCallback((message: string) => show(message, "error"), [show]);
  const showSuccess = useCallback((message: string) => show(message, "success"), [show]);

  return (
    <ToastContext.Provider value={{ showError, showSuccess }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-16 z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="alert"
            className={
              "pointer-events-auto flex max-w-md animate-in fade-in slide-in-from-top-2 items-center gap-3 rounded-full border px-4 py-2 shadow-lg backdrop-blur-sm " +
              (t.variant === "error"
                ? "border-destructive/30 bg-destructive/90 text-destructive-foreground"
                : "border-success/30 bg-success/90 text-success-foreground")
            }
          >
            <span className="text-sm font-medium">{t.message}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              className="shrink-0 rounded-full p-0.5 leading-none opacity-80 hover:opacity-100"
            >
              &times;
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
