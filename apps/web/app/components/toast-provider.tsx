"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export type ToastTone = "info" | "success" | "warning" | "error" | "loading";

type ToastOptions = {
  duration?: number;
};

type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
  duration: number;
  leaving: boolean;
};

type ToastApi = {
  show: (message: string, tone?: ToastTone, options?: ToastOptions) => void;
  auto: (message?: string | null) => void;
  info: (message: string, options?: ToastOptions) => void;
  success: (message: string, options?: ToastOptions) => void;
  warning: (message: string, options?: ToastOptions) => void;
  error: (message: string, options?: ToastOptions) => void;
  loading: (message: string, options?: ToastOptions) => void;
  clear: () => void;
};

const ToastContext = createContext<ToastApi | null>(null);
const EXIT_DURATION = 180;
const DEFAULT_DURATION: Record<ToastTone, number> = {
  info: 1400,
  success: 1400,
  warning: 2600,
  error: 2600,
  loading: 1800,
};

function inferTone(message: string): ToastTone {
  if (/失败|错误|异常|无法|不可用|HTTP|接口暂时/.test(message)) return "error";
  if (/请先|请至少|必须|不能|还不能|暂不可|太小|未通过|阻塞|缺少|缺失/.test(message)) return "warning";
  if (/成功|已保存|已创建|已生成|已确认|已完成|已发布|已加入|已删除|已替换|已应用|已导入|已锁定|已解锁|检查通过|自动检查通过/.test(message)) return "success";
  return "info";
}

function toastGlyph(tone: ToastTone) {
  if (tone === "success") return "✓";
  if (tone === "warning") return "!";
  if (tone === "error") return "×";
  if (tone === "loading") return "";
  return "i";
}

export function ToastProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [toast, setToast] = useState<ToastItem | null>(null);
  const idRef = useRef(0);
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const removeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deadlineRef = useRef(0);
  const remainingRef = useRef(0);

  const cancelTimers = useCallback(() => {
    if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    if (removeTimerRef.current) clearTimeout(removeTimerRef.current);
    dismissTimerRef.current = null;
    removeTimerRef.current = null;
  }, []);

  const dismiss = useCallback((targetId?: number) => {
    if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    dismissTimerRef.current = null;
    setToast((current) => {
      if (!current || (targetId && current.id !== targetId) || current.leaving) return current;
      const leavingId = current.id;
      removeTimerRef.current = setTimeout(() => {
        setToast((latest) => latest?.id === leavingId ? null : latest);
        removeTimerRef.current = null;
      }, EXIT_DURATION);
      return { ...current, leaving: true };
    });
  }, []);

  const scheduleDismiss = useCallback((targetId: number, delay: number) => {
    if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    remainingRef.current = delay;
    deadlineRef.current = Date.now() + delay;
    dismissTimerRef.current = setTimeout(() => dismiss(targetId), delay);
  }, [dismiss]);

  const show = useCallback((message: string, tone: ToastTone = "info", options?: ToastOptions) => {
    const normalized = message.trim();
    if (!normalized) return;
    cancelTimers();
    const next: ToastItem = {
      id: ++idRef.current,
      message: normalized,
      tone,
      duration: options?.duration ?? DEFAULT_DURATION[tone],
      leaving: false,
    };
    setToast(next);
  }, [cancelTimers]);

  const clear = useCallback(() => dismiss(), [dismiss]);
  const auto = useCallback((message?: string | null) => {
    if (!message?.trim()) {
      clear();
      return;
    }
    show(message, inferTone(message));
  }, [clear, show]);
  const info = useCallback((message: string, options?: ToastOptions) => show(message, "info", options), [show]);
  const success = useCallback((message: string, options?: ToastOptions) => show(message, "success", options), [show]);
  const warning = useCallback((message: string, options?: ToastOptions) => show(message, "warning", options), [show]);
  const error = useCallback((message: string, options?: ToastOptions) => show(message, "error", options), [show]);
  const loading = useCallback((message: string, options?: ToastOptions) => show(message, "loading", options), [show]);

  useEffect(() => {
    if (!toast || toast.leaving) return;
    scheduleDismiss(toast.id, toast.duration);
    return () => {
      if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    };
  }, [scheduleDismiss, toast]);

  useEffect(() => {
    if (!toast) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss(toast.id);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismiss, toast]);

  useEffect(() => cancelTimers, [cancelTimers]);

  const pause = useCallback(() => {
    if (!toast || toast.leaving || !dismissTimerRef.current) return;
    clearTimeout(dismissTimerRef.current);
    dismissTimerRef.current = null;
    remainingRef.current = Math.max(160, deadlineRef.current - Date.now());
  }, [toast]);

  const resume = useCallback(() => {
    if (!toast || toast.leaving || dismissTimerRef.current) return;
    scheduleDismiss(toast.id, remainingRef.current || toast.duration);
  }, [scheduleDismiss, toast]);

  const api = useMemo<ToastApi>(() => ({ show, auto, info, success, warning, error, loading, clear }), [show, auto, info, success, warning, error, loading, clear]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region" aria-label="操作提示">
        {toast && (
          <div
            className={`app-toast tone-${toast.tone}${toast.leaving ? " is-leaving" : ""}`}
            role={toast.tone === "error" ? "alert" : "status"}
            aria-live={toast.tone === "error" ? "assertive" : "polite"}
            aria-atomic="true"
            onPointerEnter={pause}
            onPointerLeave={resume}
            onFocusCapture={pause}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) resume();
            }}
          >
            <span className="app-toast-icon" aria-hidden="true">{toastGlyph(toast.tone)}</span>
            <span className="app-toast-message">{toast.message}</span>
            <button type="button" aria-label="关闭提示" onClick={() => dismiss(toast.id)}>×</button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
