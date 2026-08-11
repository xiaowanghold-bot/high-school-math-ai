"use client";

import { useAppRole } from "./role-provider";

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { ready, isAdmin, setRole } = useAppRole();

  if (!ready) return <div className="role-guard-loading">正在读取工作模式…</div>;
  if (isAdmin) return <>{children}</>;

  return <div className="page-content role-guard-page">
    <section className="role-guard-card">
      <span>管</span>
      <p>管理员功能</p>
      <h1>此页面仅在管理员模式下开放</h1>
      <div>当前处于教师模式。切换后可以处理教材目录审核、批量 PDF 加工和平台内容质量任务；教学数据不会因此改变。</div>
      <button type="button" onClick={() => setRole("admin")}>切换到管理员模式</button>
    </section>
  </div>;
}

