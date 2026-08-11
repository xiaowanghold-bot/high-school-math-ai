"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAppRole } from "./role-provider";

type TaskItem = {
  id: string;
  label: string;
  description: string;
  count: number;
  href: string;
  tone: "blue" | "amber" | "green" | "slate";
};

type CreateAction = { id: string; mark: string; label: string; description: string; href: string };

const teacherCreateActions: CreateAction[] = [
  { id: "lesson", mark: "教", label: "新建教案", description: "选择人教 A 版知识点并生成可编辑教案", href: "/lesson-plans/new" },
  { id: "paper", mark: "卷", label: "新建试卷", description: "从已验证题库选题或按模板自动组卷", href: "/papers?create=new" },
  { id: "library", mark: "资", label: "上传资料", description: "上传 PDF、Word 或图片并进行私人校对", href: "/library?create=upload" },
  { id: "solve", mark: "解", label: "开始解题", description: "输入高中数学题并生成可审核解析", href: "/solve" },
];
const adminCreateActions: CreateAction[] = [
  { id: "pdf-import", mark: "导", label: "导入 PDF 资料", description: "登记来源与权利后进入逐页拆题加工", href: "/imports" },
  { id: "question-review", mark: "题", label: "审核题库内容", description: "处理公式、数学验证、教材映射和发布门禁", href: "/search" },
  { id: "curriculum-review", mark: "册", label: "审核教材目录", description: "维护人教 A 版章节、知识点与高考优先级", href: "/curriculum/review" },
  { id: "library-admin", mark: "资", label: "管理私人资料", description: "查看上传资料、OCR 状态与拆题候选", href: "/library" },
];

async function jsonOrThrow(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function TopbarTools() {
  const router = useRouter();
  const pathname = usePathname();
  const { isAdmin } = useAppRole();
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
      const [questionStats, libraryStats, lessons, papers, imports, curriculum] = await Promise.all([
        jsonOrThrow("/api/v1/question-bank/stats"),
        jsonOrThrow("/api/v1/library/stats"),
        jsonOrThrow("/api/v1/lesson-plans"),
        jsonOrThrow("/api/v1/exam-papers"),
        jsonOrThrow("/api/v1/imports"),
        jsonOrThrow("/api/v1/curriculum/reviews?limit=1"),
      ]);
      const reviewCount = Number(questionStats.by_review_status?.pending ?? 0) + Number(questionStats.by_review_status?.changes_requested ?? 0);
      const verificationCount = Object.entries(questionStats.by_verification_status ?? {}).reduce(
        (total, [status, count]) => status === "passed" ? total : total + Number(count), 0,
      );
      const teacherTasks: TaskItem[] = [
        { id: "question-review", label: "题目待教师审核", description: "检查题干、答案、解析与来源", count: reviewCount, href: "/search", tone: "blue" },
        { id: "math-review", label: "题目待数学核验", description: "未通过独立验证，暂不能用于正式组卷", count: verificationCount, href: "/search?verification=needs_math_review", tone: "amber" },
        { id: "library-review", label: "私人资料待处理", description: `其中 ${Number(libraryStats.needs_ocr ?? 0)} 份等待 OCR 或转录`, count: Number(libraryStats.pending_review ?? 0), href: "/library", tone: "green" },
        { id: "lesson-drafts", label: "教案草稿", description: "继续编辑教学目标、课堂流程和作业", count: Number(lessons.total ?? 0), href: "/lesson-plans", tone: "slate" },
        { id: "paper-drafts", label: "试卷草稿", description: "继续选题、调整分值或导出已保存版本", count: Number(papers.total ?? 0), href: "/papers", tone: "slate" },
      ];
      const adminTasks: TaskItem[] = [
        { id: "question-review", label: "题库内容待审核", description: "检查题干、答案、解析、来源和发布门禁", count: reviewCount, href: "/search", tone: "blue" },
        { id: "math-review", label: "独立数学核验待处理", description: "未通过验证的题目不能进入正式内容链", count: verificationCount, href: "/search?verification=needs_math_review", tone: "amber" },
        { id: "curriculum-review", label: "教材目录待审核", description: "维护章节、知识点和高考优先级", count: Number(curriculum.counts?.pending ?? 0) + Number(curriculum.counts?.changes_requested ?? 0), href: "/curriculum/review", tone: "green" },
        { id: "pdf-import", label: "PDF 加工任务", description: `${Number(imports.stats?.scan_pages ?? 0)} 页等待 OCR`, count: Number(imports.stats?.ready_files ?? 0), href: "/imports", tone: "slate" },
        { id: "library-review", label: "私人资料待处理", description: "检查来源声明、OCR 和拆题候选", count: Number(libraryStats.pending_review ?? 0), href: "/library", tone: "slate" },
      ];
      setTasks(isAdmin ? adminTasks : teacherTasks);
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

  function startCreate(action: CreateAction) {
    setPanel(null);
    const targetPath = action.href.split("?")[0];
    if (pathname === targetPath) {
      window.dispatchEvent(new CustomEvent("math-ai:create", { detail: action.id }));
    }
    router.push(action.href);
  }

  const activeTaskCount = tasks.reduce((total, task) => total + task.count, 0);
  const createActions = isAdmin ? adminCreateActions : teacherCreateActions;

  return <>
    <header className="topbar">
      <form className="global-search" role="search" onSubmit={submitSearch}>
        <span aria-hidden="true">⌕</span>
        <input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} aria-label="全局搜索" placeholder="搜索知识点、题型或直接描述你要找的题目" />
        {query && <button className="global-search-clear" type="button" aria-label="清空搜索" onClick={() => { setQuery(""); searchRef.current?.focus(); }}>×</button>}
        <button className="global-search-submit" type="submit">搜索</button>
      </form>
      <button className="ghost-button topbar-task-button" type="button" onClick={openTasks}>{isAdmin ? "管理任务" : "任务中心"}{activeTaskCount > 0 && <span>{activeTaskCount > 99 ? "99+" : activeTaskCount}</span>}</button>
      <button className="primary-button" type="button" onClick={() => setPanel("create")}>＋ {isAdmin ? "管理" : "新建"}</button>
    </header>

    {panel && <div className="topbar-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setPanel(null); }}>
      <section className={`topbar-dialog ${panel}`} role="dialog" aria-modal="true" aria-labelledby={`${panel}-dialog-title`}>
        <header><div><p>{panel === "tasks" ? "WORK QUEUE" : "QUICK START"}</p><h2 id={`${panel}-dialog-title`}>{panel === "tasks" ? (isAdmin ? "管理任务" : "任务中心") : (isAdmin ? "管理操作" : "新建内容")}</h2></div><button type="button" aria-label="关闭" onClick={() => setPanel(null)}>×</button></header>
        {panel === "tasks" ? <>
          <div className="task-dialog-summary"><strong>{taskLoading ? "—" : activeTaskCount}</strong><span>项待处理记录</span><button type="button" disabled={taskLoading} onClick={loadTasks}>{taskLoading ? "读取中…" : "刷新"}</button></div>
          {taskError ? <div className="topbar-dialog-error">{taskError}</div> : <div className="task-dialog-list">{tasks.map((task) => <button type="button" key={task.id} onClick={() => { setPanel(null); router.push(task.href); }}><span className={task.tone}>{task.count}</span><div><strong>{task.label}</strong><small>{task.description}</small></div><b>→</b></button>)}{taskLoading && !tasks.length && <div className="topbar-dialog-loading">正在汇总题库、资料、教案和试卷…</div>}</div>}
        </> : <div className="create-dialog-list">{createActions.map((action) => <button type="button" key={action.id} onClick={() => startCreate(action)}><span>{action.mark}</span><div><strong>{action.label}</strong><small>{action.description}</small></div><b>→</b></button>)}</div>}
      </section>
    </div>}
  </>;
}
