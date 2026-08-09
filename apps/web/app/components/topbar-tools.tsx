"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

type TaskItem = {
  id: string;
  label: string;
  description: string;
  count: number;
  href: string;
  tone: "blue" | "amber" | "green" | "slate";
};

const createActions = [
  { id: "lesson", mark: "教", label: "新建教案", description: "选择人教 A 版知识点并生成可编辑教案", href: "/lesson-plans/new" },
  { id: "paper", mark: "卷", label: "新建试卷", description: "从已验证题库选题或按模板自动组卷", href: "/papers?create=new" },
  { id: "library", mark: "资", label: "上传资料", description: "上传 PDF、Word 或图片并进行私人校对", href: "/library?create=upload" },
  { id: "solve", mark: "解", label: "开始解题", description: "输入高中数学题并生成可审核解析", href: "/solve" },
];

async function jsonOrThrow(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function TopbarTools() {
  const router = useRouter();
  const pathname = usePathname();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [panel, setPanel] = useState<"tasks" | "create" | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [taskLoading, setTaskLoading] = useState(false);
  const [taskError, setTaskError] = useState("");

  async function loadTasks() {
    setTaskLoading(true);
    setTaskError("");
    try {
      const [questionStats, libraryStats, lessons, papers] = await Promise.all([
        jsonOrThrow("/api/v1/question-bank/stats"),
        jsonOrThrow("/api/v1/library/stats"),
        jsonOrThrow("/api/v1/lesson-plans"),
        jsonOrThrow("/api/v1/exam-papers"),
      ]);
      const reviewCount = Number(questionStats.by_review_status?.pending ?? 0) + Number(questionStats.by_review_status?.changes_requested ?? 0);
      const verificationCount = Object.entries(questionStats.by_verification_status ?? {}).reduce(
        (total, [status, count]) => status === "passed" ? total : total + Number(count), 0,
      );
      setTasks([
        { id: "question-review", label: "题目待教师审核", description: "检查题干、答案、解析与来源", count: reviewCount, href: "/search", tone: "blue" },
        { id: "math-review", label: "题目待数学核验", description: "未通过独立验证，暂不能用于正式组卷", count: verificationCount, href: "/search?verification=needs_math_review", tone: "amber" },
        { id: "library-review", label: "私人资料待处理", description: `其中 ${Number(libraryStats.needs_ocr ?? 0)} 份等待 OCR 或转录`, count: Number(libraryStats.pending_review ?? 0), href: "/library", tone: "green" },
        { id: "lesson-drafts", label: "教案草稿", description: "继续编辑教学目标、课堂流程和作业", count: Number(lessons.total ?? 0), href: "/lesson-plans", tone: "slate" },
        { id: "paper-drafts", label: "试卷草稿", description: "继续选题、调整分值或导出已保存版本", count: Number(papers.total ?? 0), href: "/papers", tone: "slate" },
      ]);
    } catch {
      setTaskError("任务数据暂时无法读取，请确认 API 已启动后重试。");
    } finally {
      setTaskLoading(false);
    }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setPanel(null);
      if (event.key === "/" && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement)) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const keyword = query.trim();
    if (!keyword) {
      searchRef.current?.focus();
      return;
    }
    const href = `/search?q=${encodeURIComponent(keyword)}`;
    router.push(href);
    window.dispatchEvent(new CustomEvent("math-ai:global-search", { detail: keyword }));
    setPanel(null);
  }

  function openTasks() {
    setPanel("tasks");
    loadTasks();
  }

  function startCreate(action: (typeof createActions)[number]) {
    setPanel(null);
    const targetPath = action.href.split("?")[0];
    if (pathname === targetPath) {
      window.dispatchEvent(new CustomEvent("math-ai:create", { detail: action.id }));
    }
    router.push(action.href);
  }

  const activeTaskCount = tasks.reduce((total, task) => total + task.count, 0);

  return <>
    <header className="topbar">
      <form className="global-search" role="search" onSubmit={submitSearch}>
        <span aria-hidden="true">⌕</span>
        <input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} aria-label="全局搜索" placeholder="搜索知识点、题型或直接描述你要找的题目" />
        {query && <button className="global-search-clear" type="button" aria-label="清空搜索" onClick={() => { setQuery(""); searchRef.current?.focus(); }}>×</button>}
        <button className="global-search-submit" type="submit">搜索</button>
      </form>
      <button className="ghost-button topbar-task-button" type="button" onClick={openTasks}>任务中心{activeTaskCount > 0 && <span>{activeTaskCount > 99 ? "99+" : activeTaskCount}</span>}</button>
      <button className="primary-button" type="button" onClick={() => setPanel("create")}>＋ 新建</button>
    </header>

    {panel && <div className="topbar-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setPanel(null); }}>
      <section className={`topbar-dialog ${panel}`} role="dialog" aria-modal="true" aria-labelledby={`${panel}-dialog-title`}>
        <header><div><p>{panel === "tasks" ? "WORK QUEUE" : "QUICK START"}</p><h2 id={`${panel}-dialog-title`}>{panel === "tasks" ? "任务中心" : "新建内容"}</h2></div><button type="button" aria-label="关闭" onClick={() => setPanel(null)}>×</button></header>
        {panel === "tasks" ? <>
          <div className="task-dialog-summary"><strong>{taskLoading ? "—" : activeTaskCount}</strong><span>项待处理记录</span><button type="button" disabled={taskLoading} onClick={loadTasks}>{taskLoading ? "读取中…" : "刷新"}</button></div>
          {taskError ? <div className="topbar-dialog-error">{taskError}</div> : <div className="task-dialog-list">{tasks.map((task) => <button type="button" key={task.id} onClick={() => { setPanel(null); router.push(task.href); }}><span className={task.tone}>{task.count}</span><div><strong>{task.label}</strong><small>{task.description}</small></div><b>→</b></button>)}{taskLoading && !tasks.length && <div className="topbar-dialog-loading">正在汇总题库、资料、教案和试卷…</div>}</div>}
        </> : <div className="create-dialog-list">{createActions.map((action) => <button type="button" key={action.id} onClick={() => startCreate(action)}><span>{action.mark}</span><div><strong>{action.label}</strong><small>{action.description}</small></div><b>→</b></button>)}</div>}
      </section>
    </div>}
  </>;
}
