"use client";

const previewStates = [
  ["默认", "tone-info", "i"],
  ["悬停", "tone-info is-hover", "i"],
  ["聚焦", "tone-info is-focus", "i"],
  ["按下", "tone-info is-active", "i"],
  ["禁用", "tone-info is-disabled", "i"],
  ["处理中", "tone-loading", ""],
  ["失败", "tone-error", "×"],
  ["成功", "tone-success", "✓"],
] as const;

export function ToastProviderPreview() {
  return (
    <section className="toast-preview-grid" aria-label="弹窗提示组件状态预览">
      {previewStates.map(([label, className, glyph]) => (
        <article key={label}>
          <small>{label}</small>
          <div className={`app-toast ${className}`}>
            <span className="app-toast-icon" aria-hidden="true">{glyph}</span>
            <span className="app-toast-message">操作反馈会在此短暂显示。</span>
            <button type="button" aria-label={`关闭${label}提示`} disabled={label === "禁用"}>×</button>
          </div>
        </article>
      ))}
    </section>
  );
}
