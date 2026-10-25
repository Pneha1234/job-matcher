"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

type Toast = { message: string; undo?: () => void | Promise<void> };
const ToastContext = createContext<(message: string, undo?: Toast["undo"]) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const [shown, setShown] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((message: string, undo?: Toast["undo"]) => {
    setToast({ message, undo });
    setShown(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setShown(false), 5000);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className={`fixed bottom-[22px] left-1/2 z-30 flex -translate-x-1/2 items-center gap-3.5 rounded-[10px] bg-foreground px-3.5 py-2.5 text-background shadow-lg transition-transform duration-200 ${
          shown ? "translate-y-0" : "translate-y-[140px]"
        }`}
      >
        <span>{toast?.message}</span>
        {toast?.undo && (
          <button
            type="button"
            className="font-semibold text-primary"
            onClick={async () => {
              setShown(false);
              await toast.undo?.();
            }}
          >
            Undo
          </button>
        )}
      </div>
    </ToastContext.Provider>
  );
}
