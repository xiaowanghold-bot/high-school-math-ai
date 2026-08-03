"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { MathText } from "../components/math-text";

type Question = {
  question_id: string;
  status: string;
  review_status: string;
  visibility: string;
  question_type: string;
  stem_plain: string;
  answer_value: string | null;
  volume: string | null;
  chapter: string | null;
  section: string | null;
  knowledge_point_ids: string[];
  difficulty: number;
  verification_status: string;
  source_document: string;
  source_page_start: number | null;
  source_page_end: number | null;
  publication_blockers: string[];
};

type QuestionDetail = Question & {
  raw: {
    stem?: { plain_text?: string; latex?: string };
    options?: { key: string; plain_text?: string; latex?: string }[];
    solutions?: { method?: string; steps_latex?: string[]; final_answer?: string; review_status?: string }[];
    verification?: { status?: string; details?: string[]; computed_answer?: string | null; computed_canonical_value?: string };
    source?: { source_reference?: string | null };
    curation?: { disposition?: string; adaptation_candidate?: { change?: string; result?: string } | null };
  };
  reviews: { reviewer_id: string; decision: string; note: string; reviewed_at: string }[];
};

type Stats = {
  total: number;
  by_review_status: Record<string, number>;
  by_verification_status: Record<string, number>;
  by_chapter: Record<string, number>;
  publishable: number;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const verificationLabels: Record<string, string> = {
  needs_formula_review: "待公式校正",
  needs_math_review: "待数学验算",
  source_inconsistency_detected: "来源存在矛盾",
  passed: "验证通过",
};

const reviewLabels: Record<string, string> = {
  pending: "待教师审核",
  approved: "教师已通过",
  changes_requested: "需要修改",
  rejected: "已拒绝",
};

const blockerLabels: Record<string, string> = {
  teacher_review_required: "缺少教师审核",
  independent_verification_required: "缺少独立数学验证",
  approved_original_solution_required: "缺少审核通过的原创解析",
  source_attribution_confirmation_required: "题源归因尚未确认",
  commercial_rights_required: "缺少商业使用权依据",
  question_rejected: "题目已被拒绝",
};

const moduleShortcuts = [
  { label: "全部", chapter: "" },
  { label: "集合", chapter: "第一章 集合与常用逻辑用语" },
  { label: "函数", chapter: "第三章 函数的概念与性质" },
  { label: "圆锥曲线", chapter: "第三章 圆锥曲线的方程" },
  { label: "概率", chapter: "第七章 随机变量及其分布" },
];

export default function SearchPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Question[]>([]);
  const [total, setTotal] = useState(0);
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [chapter, setChapter] = useState("");
  const [verification, setVerification] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<QuestionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const searchUrl = useMemo(() => {
    const params = new URLSearchParams({ page_size: "50" });
    if (query) params.set("query", query);
    if (chapter) params.set("chapter", chapter);
    if (verification) params.set("verification_status", verification);
    return `${apiBase}/api/v1/questions?${params.toString()}`;
  }, [query, chapter, verification]);

  const loadStats = () =>
    fetch(`${apiBase}/api/v1/question-bank/stats`)
      .then((response) => response.json())
      .then(setStats);

  useEffect(() => {
    loadStats().catch(() => setMessage("题库统计接口暂时不可用。"));
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetch(searchUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        if (!active) return;
        setItems(payload.items);
        setTotal(payload.total);
        setSelectedId((current) =>
          current && payload.items.some((item: Question) => item.question_id === current)
            ? current
            : payload.items[0]?.question_id ?? null,
        );
      })
      .catch(() => active && setMessage("题库接口暂时不可用，请确认后端已启动。"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [searchUrl]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    fetch(`${apiBase}/api/v1/questions/${selectedId}`)
      .then((response) => response.json())
      .then(setDetail)
      .catch(() => setMessage("无法读取题目详情。"));
  }, [selectedId]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(queryInput.trim());
  }

  async function review(decision: "approved" | "changes_requested" | "rejected") {
    if (!selectedId) return;
    const notes = {
      approved: "教师已确认校正后题干、答案、原创解析与教材映射。",
      changes_requested: "教师要求继续校正题干、公式或标签。",
      rejected: "教师判定该题不进入当前题库。",
    };
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note: notes[decision], reviewer_id: "owner_teacher" }),
    });
    if (!response.ok) {
      setMessage("审核保存失败，请稍后重试。");
      return;
    }
    setMessage(decision === "approved" ? "审核已保存；发布门禁仍会独立检查。" : "审核结论已保存。  ");
    const updated = await fetch(`${apiBase}/api/v1/questions/${selectedId}`).then((item) => item.json());
    setDetail(updated);
    setItems((current) => current.map((item) => item.question_id === selectedId ? { ...item, ...updated } : item));
    loadStats();
  }

  async function checkPublish() {
    if (!selectedId) return;
    const decision = await fetch(`${apiBase}/api/v1/questions/${selectedId}/publish`, { method: "POST" })
      .then((response) => response.json());
    setMessage(
      decision.allowed
        ? "全部门禁通过，题目已发布。"
        : `暂不可发布：${decision.blockers.map((item: string) => blockerLabels[item] ?? item).join("、")}`,
    );
  }

  async function showImportStatus() {
    const batches = await fetch(`${apiBase}/api/v1/question-bank/import-batches`).then((response) => response.json());
    const latest = batches[0];
    setMessage(
      latest
        ? `最近导入：${latest.batch_id}，共 ${latest.declared_count} 题；当前状态为私有、不可直接发布。`
        : "还没有题目导入记录。",
    );
  }

  const pending = stats?.by_review_status.pending ?? 0;
  const formulaIssues = stats?.by_verification_status.needs_formula_review ?? 0;
  const sourceIssues = stats?.by_verification_status.source_inconsistency_detected ?? 0;
  const verifiedCount = stats?.by_verification_status.passed ?? 0;

  return (
    <div className="page-content question-workspace">
      <section className="page-title question-title">
        <div>
          <p className="eyebrow">智能搜题 · 教师审核台</p>
          <h1>先把每一道题变得可信。</h1>
          <p className="subtle">当前仅展示题目事实，原PDF版式与原解析不进入产品内容。</p>
        </div>
        <button className="primary-button" type="button" onClick={showImportStatus}>导入记录</button>
      </section>

      {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}

      <section className="quality-strip" aria-label="题库质量概览">
        <div><span>试点题目</span><strong>{stats?.total ?? "—"}</strong><small>本地私有题库</small></div>
        <div><span>待教师审核</span><strong>{pending}</strong><small>逐题确认</small></div>
        <div className="metric-passed"><span>独立验证通过</span><strong>{verifiedCount}</strong><small>含计算证据</small></div>
        <div><span>待公式校正</span><strong>{formulaIssues}</strong><small>禁止直接展示</small></div>
        <div className={sourceIssues ? "metric-alert" : ""}><span>来源矛盾</span><strong>{sourceIssues}</strong><small>需重点复核</small></div>
        <div><span>当前可发布</span><strong>{stats?.publishable ?? 0}</strong><small>全部门禁通过</small></div>
      </section>

      <form className="question-filters" onSubmit={submitSearch}>
        <label className="search-field"><span>⌕</span><input aria-label="搜索题目" value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder="搜索题干、章节或来源，例如：集合、椭圆、概率" /></label>
        <select value={chapter} onChange={(event) => setChapter(event.target.value)} aria-label="按章节筛选">
          <option value="">全部章节</option>
          {Object.keys(stats?.by_chapter ?? {}).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select value={verification} onChange={(event) => setVerification(event.target.value)} aria-label="按验证状态筛选">
          <option value="">全部质量状态</option>
          <option value="passed">验证通过</option>
          <option value="needs_formula_review">待公式校正</option>
          <option value="needs_math_review">待数学验算</option>
          <option value="source_inconsistency_detected">来源存在矛盾</option>
        </select>
        <button className="primary-button" type="submit">检索</button>
      </form>

      <nav className="module-shortcuts" aria-label="按数学模块快速筛选">
        <span>快速进入</span>
        {moduleShortcuts.map((item) => (
          <button
            className={chapter === item.chapter ? "active" : ""}
            key={item.label}
            type="button"
            onClick={() => setChapter(item.chapter)}
          >
            {item.label}
            {item.chapter && stats?.by_chapter[item.chapter] !== undefined
              ? <small>{stats.by_chapter[item.chapter]}</small>
              : null}
          </button>
        ))}
      </nav>

      <div className="question-layout">
        <section className="question-results" aria-label="题目列表">
          <div className="results-heading"><strong>{loading ? "正在检索…" : `${total} 道题`}</strong><span>仅限当前教师账号</span></div>
          <div className="result-list">
            {items.map((item, index) => (
              <button className={selectedId === item.question_id ? "question-row selected" : "question-row"} type="button" key={item.question_id} onClick={() => setSelectedId(item.question_id)}>
                <span className="question-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="question-main">
                  <span className="question-tags"><em>{item.question_type === "single_choice" ? "单选题" : "解答题"}</em><i className={`quality-tag ${item.verification_status}`}>{verificationLabels[item.verification_status] ?? item.verification_status}</i></span>
                  <b>{item.stem_plain}</b>
                  <small>{item.chapter} · 难度 {item.difficulty}/5</small>
                </span>
                <span className="review-mark">{reviewLabels[item.review_status] ?? item.review_status}</span>
              </button>
            ))}
            {!loading && items.length === 0 && <div className="empty-state"><strong>没有匹配题目</strong><p>换一个关键词或清空筛选条件。</p></div>}
          </div>
        </section>

        <aside className="question-detail" aria-label="题目审核详情">
          {!detail && <div className="empty-state"><strong>请选择一道题</strong><p>右侧将显示来源、答案与审核动作。</p></div>}
          {detail && <>
            <header className="detail-heading"><div><p>{detail.volume}{detail.section ? ` · ${detail.section}` : ""}</p><h2>{detail.chapter}</h2></div><span>难度 {detail.difficulty}</span></header>
            {detail.verification_status === "passed"
              ? <div className="verification-passed"><strong>独立验证通过</strong><p>公式已对照原页重建，答案已由规则模块独立计算并匹配唯一选项。</p></div>
              : <div className="formula-warning"><strong>{verificationLabels[detail.verification_status]}</strong><p>{detail.verification_status === "source_inconsistency_detected" ? "独立计算与来源选项不一致，该题已隔离，不能审核发布。" : "当前文本来自PDF定位层，必须对照原页重建公式后才能公开展示。"}</p></div>}
            <div className="stem-card"><p><MathText text={detail.raw.stem?.latex || detail.stem_plain} /></p></div>
            {!!detail.raw.options?.length && <ol className="option-list">{detail.raw.options.map((option) => <li key={option.key}><b>{option.key}</b><span><MathText text={option.latex || option.plain_text || "选项内容需重建"} /></span></li>)}</ol>}
            <div className="answer-line"><span>{detail.verification_status === "passed" ? "独立验证答案" : "独立验证结论"}</span><strong>{detail.raw.verification?.computed_answer || (detail.verification_status === "source_inconsistency_detected" ? "无正确选项" : detail.answer_value || "待独立求解")}</strong></div>
            {!!detail.raw.solutions?.[0]?.steps_latex?.length && <div className="solution-card"><header><span>自有解析草稿</span><strong>{detail.raw.solutions[0].method}</strong></header><ol>{detail.raw.solutions[0].steps_latex?.map((step, index) => <li key={index}><MathText text={step} /></li>)}</ol><small>需由教师确认后才可作为正式解析</small></div>}
            {detail.raw.curation?.adaptation_candidate && <div className="adaptation-card"><strong>可修订为新题</strong><p>{detail.raw.curation.adaptation_candidate.change}；{detail.raw.curation.adaptation_candidate.result}。</p></div>}
            <dl className="source-meta">
              <div><dt>来源文件</dt><dd>{detail.source_document}</dd></div>
              <div><dt>定位页</dt><dd>{detail.source_page_start ?? "—"}{detail.source_page_end && detail.source_page_end !== detail.source_page_start ? `–${detail.source_page_end}` : ""}</dd></div>
              <div><dt>审核状态</dt><dd>{reviewLabels[detail.review_status] ?? detail.review_status}</dd></div>
            </dl>
            <div className="gate-list"><h3>发布门禁</h3>{detail.publication_blockers.map((item) => <span key={item}>○ {blockerLabels[item] ?? item}</span>)}</div>
            <div className="review-actions">
              <button type="button" className="approve" disabled={detail.verification_status !== "passed"} onClick={() => review("approved")}>教师通过</button>
              <button type="button" onClick={() => review("changes_requested")}>需要修改</button>
              <button type="button" className="reject" onClick={() => review("rejected")}>拒绝入库</button>
            </div>
            <button className="publish-check" type="button" onClick={checkPublish}>检查是否可以发布</button>
          </>}
        </aside>
      </div>
    </div>
  );
}
