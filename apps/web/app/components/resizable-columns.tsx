"use client";

import { CSSProperties, KeyboardEvent, PointerEvent, ReactNode, useEffect, useRef, useState } from "react";

type ResizableColumnsProps = {
  children: ReactNode;
  className?: string;
  storageKey: string;
  initialLeftPercent?: number;
  leftMin?: number;
  rightMin?: number;
  collapse?: "wide" | "compact";
  label?: string;
};

const HANDLE_WIDTH = 14;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function ResizableColumns({
  children,
  className = "",
  storageKey,
  initialLeftPercent = 35,
  leftMin = 280,
  rightMin = 480,
  collapse = "compact",
  label = "调整左右区域宽度",
}: ResizableColumnsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const valueRef = useRef(initialLeftPercent);
  const [leftPercent, setLeftPercent] = useState(initialLeftPercent);
  const [dragging, setDragging] = useState(false);
  const [constrained, setConstrained] = useState(false);
  const panes = Array.isArray(children) ? children : [children];

  useEffect(() => {
    const stored = window.localStorage.getItem(`math-studio:split:${storageKey}`);
    const parsed = stored ? Number(stored) : Number.NaN;
    if (Number.isFinite(parsed)) {
      const next = clamp(parsed, 15, 80);
      valueRef.current = next;
      setLeftPercent(next);
    }
  }, [storageKey]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      setConstrained(entry.contentRect.width < leftMin + rightMin + HANDLE_WIDTH + 36);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [leftMin, rightMin]);

  function percentFromClientX(clientX: number) {
    const bounds = containerRef.current?.getBoundingClientRect();
    if (!bounds) return valueRef.current;
    const usableWidth = Math.max(1, bounds.width - HANDLE_WIDTH);
    const minimum = Math.min(leftMin, usableWidth * 0.45);
    const maximum = Math.max(minimum, usableWidth - Math.min(rightMin, usableWidth * 0.55));
    const leftWidth = clamp(clientX - bounds.left, minimum, maximum);
    return (leftWidth / usableWidth) * 100;
  }

  function commit(next: number) {
    const safe = clamp(next, 15, 80);
    valueRef.current = safe;
    setLeftPercent(safe);
    window.localStorage.setItem(`math-studio:split:${storageKey}`, safe.toFixed(2));
  }

  function startDrag(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    setDragging(true);
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = "none";

    const move = (moveEvent: globalThis.PointerEvent) => {
      const next = percentFromClientX(moveEvent.clientX);
      valueRef.current = next;
      setLeftPercent(next);
    };
    const stop = () => {
      setDragging(false);
      document.body.style.userSelect = previousUserSelect;
      window.localStorage.setItem(
        `math-studio:split:${storageKey}`,
        valueRef.current.toFixed(2),
      );
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

  function adjustWithKeyboard(event: KeyboardEvent<HTMLButtonElement>) {
    let next = valueRef.current;
    if (event.key === "ArrowLeft") next -= event.shiftKey ? 10 : 2;
    else if (event.key === "ArrowRight") next += event.shiftKey ? 10 : 2;
    else if (event.key === "Home") next = 20;
    else if (event.key === "End") next = 75;
    else return;
    event.preventDefault();
    commit(next);
  }

  const style = {
    "--resizable-left": `${leftPercent}%`,
    "--resizable-left-min": `${leftMin}px`,
    "--resizable-right-min": `${rightMin}px`,
  } as CSSProperties;

  return <div ref={containerRef} className={`resizable-columns ${className}`} data-collapse={collapse} data-constrained={constrained || undefined} data-dragging={dragging || undefined} style={style}>
    {panes[0]}
    <button
      className="column-resizer"
      type="button"
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(leftPercent)}
      aria-disabled={constrained}
      title="左右拖动调整宽度；双击恢复默认；方向键可微调"
      onPointerDown={startDrag}
      onKeyDown={adjustWithKeyboard}
      onDoubleClick={() => commit(initialLeftPercent)}
    ><span aria-hidden="true" /></button>
    {panes[1]}
  </div>;
}
