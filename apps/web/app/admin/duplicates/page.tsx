"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminGuard } from "../../components/admin-guard";
import { MathText } from "../../components/math-text";
import { ResizableColumns } from "../../components/resizable-columns";
import { useToast } from "../../components/toast-provider";
import "./duplicates.css";

type Question = {
  question_id: string;
  stem_plain: string;
  answer_value: string | null;
  question_type: string;
  chapter: string | null;
  difficulty: number;
  verification_status: string;
  source_document: string;
  source_page_start: number | null;
  source_page_end: number | null;
};

type Relation = "exact_duplicate" | "same_problem_different_source" | "same_problem_different_solution" | "variant" | "not_duplicate";
type Status = "proposed" | "confirmed" | "rejected" | "stale";

type Candidate = {
  candidate_id: string;
  left: Question;
  right: Question;
  suggested_relation: Relation;
  teacher_relation: Relation | null;
  confidence: number;
  signals: string[];
  status: Status;
  reviewer_id: string | null;
  review_note: string;
  updated_at: string;
};

type Stats = {
  total: number;
  proposed: number;
  confirmed: number;
  rejected: number;
  stale: number;
  exact_duplicate: number;
  same_problem: number;
  variant: number;
};

type Workspace = { items: Candidate[]; stats: Stats };

const emptyStats: Stats = { total: 0, proposed: 0, confirmed: 0, rejected: 0, stale: 0, exact_duplicate: 0, same_problem: 0, variant: 0 };
const relationLabels: Record<Relation, string> = {
  exact_duplicate: "完全重复",
  same_problem_different_source: "同题不同来源",
  same_problem_different_solution: "同题异解",
  variant: "保留为变式",
  not_duplicate: "非重复",
};
const statusLabels: Record<Status, string> = { proposed: "待确认", confirmed: "已确认", rejected: "已排除", stale: "已过期" };

async function readError(response: Response) {
  try {
    const body = await response.json();
    return String(body.detail || `HTTP ${response.status}`);
  } catch {
    return `HTTP ${response.status}`;
  }
}

function sourcePages(question: Question) {
  if (!question.source_page_start) return "页码未记录";
  return `第 ${question.source_page_start}${question.source_page_end && question.source_page_end !== question.source_page_start ? `—${question.source_page_end}` : ""} 页`;
}

function QuestionSide({ label, question }: { label: string; question: Question }) {
  return <article className="duplicate-question-side">
    <header><span>{label}</span><a href={`/search?q=${encodeURIComponent(question.question_id)}`}>完整审核 ↗</a></header>
    <div className="duplicate-question-meta"><b>{question.question_id}</b><span>{question.chapter || "知识点待映射"}</span><span>难度 {question.difficulty}</span></div>
    <div className="duplicate-stem"><MathText text={question.stem_plain} /></div>
    <dl>
      <div><dt>当前答案</dt><dd>{question.answer_value ? <MathText text={question.answer_value} /> : "未录入"}</dd></div>
      <div><dt>来源</dt><dd>{question.source_document}</dd></div>
      <div><dt>定位</dt><dd>{sourcePages(question)}</dd></div>
    </dl>
  </article>;
}

function DuplicateDashboard() {
  const { auto: toast } = useToast();
  const [workspace, setWorkspace] = useState<Workspace>({ items: [], stats: emptyStats });
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState<"all" | Status>("all");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (nextFilter: "all" | Status) => {
    setLoading(true);
    try {
      const query = nextFilter === "all" ? "" : `?status=${nextFilter}`;
      const response = await fetch(`/api/v1/question-similarity${query}`, { cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const next: Workspace = await response.json();
      setWorkspace(next);
      setSelectedId((current) => next.items.some((item) => item.candidate_id === current) ? current : next.items[0]?.candidate_id || "");
    } catch (error) {
      toast(error instanceof Error ? `候选关系读取失败：${error.message}` : "候选关系读取失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(filter); }, [filter, load]);

  const selected = useMemo(() => workspace.items.find((item) => item.candidate_id === selectedId) || workspace.items[0] || null, [selectedId, workspace.items]);

  async function scan() {
    setBusy(true);
    toast("正在扫描题库并建立候选关系…");
    try {
      const response = await fetch("/api/v1/question-similarity/scan", { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const result = await response.json();
      toast(`扫描完成：检查 ${result.scanned_questions} 道题，新增 ${result.new_candidates} 组候选`);
      await load(filter);
    } catch (error) {
      toast(error instanceof Error ? `题库扫描失败：${error.message}` : "题库扫描失败");
    } finally {
      setBusy(false);
    }
  }

  async function review(relation: Relation) {
    if (!selected || selected.status === "stale") return;
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/question-similarity/${selected.candidate_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ relation, note, reviewer_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const result = await response.json();
      toast(result.message);
      setNote("");
      await load(filter);
    } catch (error) {
      toast(error instanceof Error ? `关系保存失败：${error.message}` : "关系保存失败");
    } finally {
      setBusy(false);
    }
  }

  function chooseFilter(next: "all" | Status) {
    setFilter(next);
  }

  return <div className="page-content duplicate-page">
    <section className="page-title duplicate-title">
      <div><p className="eyebrow">题库治理 · 重复与变式识别</p><h1>题目关系校对台</h1><p className="subtle">系统只提出候选，教师确认关系；当前阶段不会删除、合并或覆盖任何原题。</p></div>
      <button className="primary-button" type="button" disabled={busy} onClick={scan}>{busy ? "处理中…" : "扫描题库"}</button>
    </section>

    <section className="duplicate-metrics" aria-label="题目关系指标">
      <article><span>待教师确认</span><strong>{loading ? "—" : workspace.stats.proposed}</strong><small>优先处理</small></article>
      <article><span>完全重复</span><strong>{loading ? "—" : workspace.stats.exact_duplicate}</strong><small>候选或已确认</small></article>
      <article><span>同题关系</span><strong>{loading ? "—" : workspace.stats.same_problem}</strong><small>不同来源 / 异解</small></article>
      <article><span>变式关系</span><strong>{loading ? "—" : workspace.stats.variant}</strong><small>保留独立题目</small></article>
      <article><span>内容已变化</span><strong>{loading ? "—" : workspace.stats.stale}</strong><small>需重新扫描</small></article>
    </section>

    <section className="duplicate-toolbar">
      <div className="duplicate-filters" role="group" aria-label="候选状态筛选">
        {(["all", "proposed", "confirmed", "rejected", "stale"] as const).map((value) => <button type="button" className={filter === value ? "active" : ""} key={value} onClick={() => chooseFilter(value)}>{value === "all" ? "全部" : statusLabels[value]}{value !== "all" && <span>{workspace.stats[value]}</span>}</button>)}
      </div>
      <p>相似度仅用于排序，不代表教师结论。</p>
    </section>

    {loading && !workspace.items.length ? <div className="duplicate-empty"><span>比</span><h2>正在读取题目关系…</h2></div> : !workspace.items.length ? <div className="duplicate-empty"><span>比</span><h2>{workspace.stats.total ? "当前筛选下没有候选" : "还没有建立题目关系候选"}</h2><p>{workspace.stats.total ? "切换上方状态查看其他记录。" : "点击“扫描题库”，系统会规范化题号、来源前缀、公式与数字结构，再提交候选给教师。"}</p>{!workspace.stats.total && <button type="button" disabled={busy} onClick={scan}>开始首次扫描</button>}</div> : <ResizableColumns className="duplicate-workspace" storageKey="question-duplicates" initialLeftPercent={30} leftMin={240} rightMin={430} collapse="wide" label="调整候选列表与关系校对区宽度">
      <aside className="duplicate-candidate-list">
        <header><strong>{workspace.items.length} 组关系</strong><span>按置信度排序</span></header>
        <div>{workspace.items.map((item, index) => <button type="button" className={selected?.candidate_id === item.candidate_id ? "active" : ""} key={item.candidate_id} onClick={() => { setSelectedId(item.candidate_id); setNote(item.review_note); }}>
          <span>{String(index + 1).padStart(2, "0")}</span><div><header><b>{relationLabels[item.teacher_relation || item.suggested_relation]}</b><em className={item.status}>{statusLabels[item.status]}</em></header><p>{item.left.stem_plain.replace(/\s+/g, " ").slice(0, 72)}</p><small>{item.left.source_document} ↔ {item.right.source_document}</small></div><strong>{Math.round(item.confidence * 100)}%</strong>
        </button>)}</div>
      </aside>
      {selected ? <main className="duplicate-review-panel">
        <header><div><p>候选 {selected.candidate_id.slice(-8)}</p><h2>{relationLabels[selected.teacher_relation || selected.suggested_relation]}</h2></div><div className="duplicate-confidence"><span>系统置信度</span><strong>{Math.round(selected.confidence * 100)}%</strong><em className={selected.status}>{statusLabels[selected.status]}</em></div></header>
        <section className="duplicate-signals"><strong>判定依据</strong>{selected.signals.map((signal) => <span key={signal}>✓ {signal}</span>)}</section>
        <div className="duplicate-comparison"><QuestionSide label="题目 A" question={selected.left} /><QuestionSide label="题目 B" question={selected.right} /></div>
        {selected.status === "stale" ? <section className="duplicate-stale-note"><strong>这组判断已经过期</strong><p>其中至少一道题的内容已改变。请先重新扫描，再基于新版本确认关系。</p></section> : <section className="duplicate-decision">
          <header><div><strong>教师确认关系</strong><p>只保存关系记录，不改变两道题的正文、解析和发布状态。</p></div>{selected.teacher_relation && <span>当前：{relationLabels[selected.teacher_relation]}</span>}</header>
          <div className="duplicate-decision-buttons">
            {(Object.keys(relationLabels) as Relation[]).map((relation) => <button type="button" className={`${relation} ${selected.teacher_relation === relation ? "selected" : ""}`} disabled={busy} key={relation} onClick={() => void review(relation)}>{relationLabels[relation]}</button>)}
          </div>
          <label><span>校对备注（可选）</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="例如：题干完全相同，但第二份资料提供了另一种向量解法。" /></label>
        </section>}
      </main> : <div />}
    </ResizableColumns>}
  </div>;
}

export default function DuplicatePage() {
  return <AdminGuard><DuplicateDashboard /></AdminGuard>;
}
