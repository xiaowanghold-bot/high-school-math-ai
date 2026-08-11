"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AdminGuard } from "../components/admin-guard";

type AdminMetrics = {
  questionTotal: number;
  pendingQuestions: number;
  pendingMath: number;
  pendingCurriculum: number;
  importFiles: number;
  importPages: number;
  pendingLibrary: number;
};

const emptyMetrics: AdminMetrics = { questionTotal: 0, pendingQuestions: 0, pendingMath: 0, pendingCurriculum: 0, importFiles: 0, importPages: 0, pendingLibrary: 0 };

async function readJson(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function AdminDashboard() {
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      readJson("/api/v1/question-bank/stats"),
      readJson("/api/v1/curriculum/reviews?limit=1"),
      readJson("/api/v1/imports"),
      readJson("/api/v1/library/stats"),
    ]).then(([questions, curriculum, imports, library]) => {
      const byReview = questions.by_review_status ?? {};
      const byVerification = questions.by_verification_status ?? {};
      const pendingMath = Object.entries(byVerification).reduce((total, [status, count]) => status === "passed" ? total : total + Number(count), 0);
      setMetrics({
        questionTotal: Number(questions.total ?? 0),
        pendingQuestions: Number(byReview.pending ?? 0) + Number(byReview.changes_requested ?? 0),
        pendingMath,
        pendingCurriculum: Number(curriculum.counts?.pending ?? 0) + Number(curriculum.counts?.changes_requested ?? 0),
        importFiles: Number(imports.stats?.files ?? 0),
        importPages: Number(imports.stats?.pages ?? 0),
        pendingLibrary: Number(library.pending_review ?? 0),
      });
    }).catch(() => setError("管理数据暂时无法读取，请确认 API 已启动。"))
      .finally(() => setLoading(false));
  }, []);

  return <div className="page-content admin-dashboard">
    <section className="page-title"><div><p className="eyebrow">平台管理 · 单人运营台</p><h1>管理总览</h1><p className="subtle">集中处理题库质量、教材目录、资料来源和 PDF 内容生产任务。</p></div><span className="admin-mode-badge">管理员模式</span></section>
    <div className="admin-prototype-note"><strong>当前权限阶段</strong><span>工作模式与页面门禁已经启用；正式账号登录、服务端鉴权、套餐和用户管理将在商业上线阶段接入。</span></div>
    {error && <div className="notice warning">{error}</div>}
    <section className="admin-metric-grid" aria-label="管理指标">
      <div><span>题库总量</span><strong>{loading ? "—" : metrics.questionTotal}</strong><small>{metrics.pendingQuestions} 道待内容审核</small></div>
      <div><span>数学核验</span><strong>{loading ? "—" : metrics.pendingMath}</strong><small>未通过独立验证</small></div>
      <div><span>教材目录</span><strong>{loading ? "—" : metrics.pendingCurriculum}</strong><small>待审核或需修改</small></div>
      <div><span>PDF 加工</span><strong>{loading ? "—" : metrics.importFiles}</strong><small>{metrics.importPages} 页已登记</small></div>
    </section>
    <section className="admin-work-grid">
      <Link href="/search" className="admin-work-card blue"><span>题</span><div><p>内容质量</p><h2>题库审核与数学核验</h2><small>处理题干、公式、答案、教材映射、来源和发布门禁。</small><strong>{metrics.pendingQuestions + metrics.pendingMath} 项待处理 →</strong></div></Link>
      <Link href="/curriculum/review" className="admin-work-card green"><span>册</span><div><p>教材治理</p><h2>人教 A 版目录审核</h2><small>维护章节、知识点、核心素养、典型题型与高考优先级。</small><strong>{metrics.pendingCurriculum} 项待处理 →</strong></div></Link>
      <Link href="/imports" className="admin-work-card amber"><span>导</span><div><p>内容生产</p><h2>批量 PDF 加工中心</h2><small>从来源登记、逐页分析、题目边界一直处理到公式与图片校对。</small><strong>{metrics.importFiles} 份 · {metrics.importPages} 页 →</strong></div></Link>
      <Link href="/library" className="admin-work-card slate"><span>资</span><div><p>资料治理</p><h2>私人资料与权利记录</h2><small>查看上传资料、OCR 状态、拆题候选和来源声明。</small><strong>{metrics.pendingLibrary} 项待处理 →</strong></div></Link>
    </section>
  </div>;
}

export default function AdminPage() {
  return <AdminGuard><AdminDashboard /></AdminGuard>;
}

