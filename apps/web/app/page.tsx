"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

type CurriculumNode = {
  node_id: string;
  node_type: string;
  code: string;
  name: string;
  children: CurriculumNode[];
};

type LessonPlanSummary = {
  lesson_plan_id: string;
  title: string;
  topic: string;
  version: number;
  updated_at: string;
};

type PaperSummary = {
  exam_paper_id: string;
  title: string;
  question_count: number;
  version: number;
  updated_at: string;
};

type DashboardChapter = {
  nodeId: string;
  volumeId: string;
  number: string;
  name: string;
  sectionCount: number;
  knowledgePointCount: number;
};

type RecentWork = {
  id: string;
  kind: "教案" | "试卷";
  title: string;
  detail: string;
  updatedAt: string;
  href: string;
};

function greetingForHour(hour: number) {
  if (hour < 5 || hour >= 23) return "夜深了";
  if (hour < 11) return "上午好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function countKnowledgePoints(chapter: CurriculumNode) {
  return chapter.children.reduce(
    (total, section) => total + section.children.length,
    0,
  );
}

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近更新";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export default function DashboardPage() {
  const [greeting, setGreeting] = useState("你好");
  const [chapters, setChapters] = useState<DashboardChapter[]>([]);
  const [lessonPlans, setLessonPlans] = useState<LessonPlanSummary[]>([]);
  const [papers, setPapers] = useState<PaperSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadIssue, setLoadIssue] = useState(false);

  useEffect(() => {
    function updateGreeting() {
      setGreeting(greetingForHour(new Date().getHours()));
    }
    updateGreeting();
    const timer = window.setInterval(updateGreeting, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    Promise.allSettled([
      fetchJson<CurriculumNode>("/api/v1/curriculum/tree"),
      fetchJson<{ items: LessonPlanSummary[] }>("/api/v1/lesson-plans?limit=30&lifecycle_state=active"),
      fetchJson<{ items: PaperSummary[] }>("/api/v1/exam-papers?limit=30&lifecycle_state=active"),
    ]).then(([curriculumResult, lessonResult, paperResult]) => {
      if (curriculumResult.status === "fulfilled") {
        const root = curriculumResult.value;
        const volumes = root.node_type === "volume"
          ? [root]
          : root.children.filter((item) => item.node_type === "volume");
        const firstVolume = volumes[0];
        setChapters((firstVolume?.children ?? []).map((chapter) => ({
          nodeId: chapter.node_id,
          volumeId: firstVolume.node_id,
          number: chapter.code.padStart(2, "0"),
          name: chapter.name,
          sectionCount: chapter.children.length,
          knowledgePointCount: countKnowledgePoints(chapter),
        })));
      }
      if (lessonResult.status === "fulfilled") setLessonPlans(lessonResult.value.items);
      if (paperResult.status === "fulfilled") setPapers(paperResult.value.items);
      setLoadIssue(
        curriculumResult.status === "rejected"
        || lessonResult.status === "rejected"
        || paperResult.status === "rejected",
      );
      setLoading(false);
    });
  }, []);

  const recentWork = useMemo<RecentWork[]>(() => [
    ...lessonPlans.map((plan) => ({
      id: plan.lesson_plan_id,
      kind: "教案" as const,
      title: plan.title,
      detail: `${plan.topic} · v${plan.version}`,
      updatedAt: plan.updated_at,
      href: `/lesson-plans?open=${encodeURIComponent(plan.lesson_plan_id)}`,
    })),
    ...papers.map((paper) => ({
      id: paper.exam_paper_id,
      kind: "试卷" as const,
      title: paper.title,
      detail: `${paper.question_count} 道题 · v${paper.version}`,
      updatedAt: paper.updated_at,
      href: `/papers?open=${encodeURIComponent(paper.exam_paper_id)}`,
    })),
  ].sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()).slice(0, 4), [lessonPlans, papers]);

  return (
    <div className="page-content dashboard-page" data-state={loading ? "loading" : loadIssue ? "error" : "success"}>
      <section className="welcome-row">
        <div>
          <p className="eyebrow">2026 秋季 · 人教 A 版</p>
          <h1>{greeting}，开始准备下一节数学课。</h1>
          <p className="subtle">从教材章节进入，或者直接告诉 AI 这节课要解决什么问题。</p>
        </div>
      </section>

      <section className="quick-grid" aria-label="快捷操作">
        <Link href="/lesson-plans/new" className="quick-card accent-blue"><span>备</span><div><h2>生成一份教案</h2><p>按章节、课型和学情生成可编辑初稿</p></div><b>→</b></Link>
        <Link href="/search" className="quick-card accent-teal"><span>题</span><div><h2>搜索与挑选题目</h2><p>自然语言、知识点和公式混合检索</p></div><b>→</b></Link>
        <Link href="/papers?create=new" className="quick-card accent-amber"><span>卷</span><div><h2>创建一份试卷</h2><p>控制知识点、题型、难度和分值</p></div><b>→</b></Link>
        <Link href="/solve" className="quick-card accent-purple"><span>解</span><div><h2>分析一道题目</h2><p>查看标准解法、易错点与可信度证据</p></div><b>→</b></Link>
      </section>

      <section className="section-block">
        <div className="section-heading"><div><p className="eyebrow">按教材备课</p><h2>必修第一册</h2></div><Link href="/curriculum">查看完整教材目录 →</Link></div>
        {chapters.length ? <div className="chapter-list">
          {chapters.map((chapter) => (
            <Link
              className="chapter"
              href={`/curriculum?volume=${encodeURIComponent(chapter.volumeId)}&chapter=${encodeURIComponent(chapter.nodeId)}`}
              key={chapter.nodeId}
              aria-label={`进入${chapter.name}教材备课`}
            >
              <span className="chapter-number">{chapter.number}</span>
              <div><h3>{chapter.name}</h3><p>{chapter.sectionCount} 节 · {chapter.knowledgePointCount} 个知识点</p></div>
              <span className="chapter-action">选择本章 <b>→</b></span>
            </Link>
          ))}
        </div> : <div className="dashboard-skeleton" aria-live="polite">{loading ? "正在读取教材目录…" : "教材目录暂时不可用，请稍后刷新。"}</div>}
      </section>

      <section className="two-column dashboard-work-grid">
        <div className="panel recent-work-panel">
          <div className="section-heading compact"><h2>最近工作</h2><div className="section-heading-links"><Link href="/lesson-plans">全部教案</Link><Link href="/papers">全部试卷</Link></div></div>
          {recentWork.length ? <div className="recent-work-list">
            {recentWork.map((item) => <Link href={item.href} key={`${item.kind}-${item.id}`}>
              <span className={item.kind === "教案" ? "lesson" : "paper"}>{item.kind.slice(0, 1)}</span>
              <div><strong>{item.title}</strong><small>{item.detail}</small></div>
              <time dateTime={item.updatedAt}>{formatUpdatedAt(item.updatedAt)}</time>
              <b>→</b>
            </Link>)}
          </div> : <div className="empty-state"><strong>{loading ? "正在读取最近工作…" : "还没有教案或试卷"}</strong><p>{loadIssue ? "部分服务暂时不可用，刷新后可重试。" : "先从教材目录选择一节课，创建第一份教案。"}</p>{!loading && <Link href="/curriculum">从教材开始备课</Link>}</div>}
        </div>
        <aside className="panel teacher-assets-panel" aria-label="我的备课资料">
          <div className="section-heading compact"><div><h2>我的备课资料</h2><p>只显示你可以继续使用的内容</p></div><Link href="/curriculum">选择教材</Link></div>
          <div className="teacher-assets-list">
            <Link href="/lesson-plans"><span>教案</span><strong>{loading ? "—" : lessonPlans.length}</strong><small>查看与继续编辑</small><b>→</b></Link>
            <Link href="/papers"><span>试卷</span><strong>{loading ? "—" : papers.length}</strong><small>查看与继续组卷</small><b>→</b></Link>
            <Link href="/curriculum"><span>本册</span><strong>{loading ? "—" : chapters.length}</strong><small>按章节开始备课</small><b>→</b></Link>
          </div>
        </aside>
      </section>
    </div>
  );
}
