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
  library_state: "active" | "removed";
  removed_at: string | null;
  removal_reason: string | null;
};

type Relation = "exact_duplicate" | "same_problem_different_source" | "same_problem_different_solution" | "variant" | "not_duplicate";
type Status = "proposed" | "confirmed" | "rejected" | "stale";

type Candidate = {
  candidate_id: string;
  left: Question;
  right: Question;
  members: Question[];
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
type PendingLibraryAction = { action: "remove" | "restore"; questionIds: string[] } | null;

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
  return <article className={`duplicate-question-side ${question.library_state}`}>
    <header><span>{label}{question.library_state === "removed" && <em>已移出</em>}</span><a href={`/search?q=${encodeURIComponent(question.question_id)}`}>完整审核 ↗</a></header>
    <div className="duplicate-question-meta"><b>{question.question_id}</b><span>{question.chapter || "知识点待映射"}</span><span>难度 {question.difficulty}</span></div>
    <div className="duplicate-stem"><MathText text={question.stem_plain} /></div>
    <dl>
      <div><dt>当前答案</dt><dd>{question.answer_value ? <MathText text={question.answer_value} /> : "未录入"}</dd></div>
      <div><dt>来源</dt><dd>{question.source_document}</dd></div>
      <div><dt>定位</dt><dd>{sourcePages(question)}</dd></div>
      {question.library_state === "removed" && <div><dt>移出原因</dt><dd>{question.removal_reason || "重复题校对"}</dd></div>}
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
  const [selectedQuestionIds, setSelectedQuestionIds] = useState<string[]>([]);
  const [pendingLibraryAction, setPendingLibraryAction] = useState<PendingLibraryAction>(null);

  const load = useCallback(async (nextFilter: "all" | Status) => {
    setLoading(true);
    try {
      const query = nextFilter === "all" ? "" : `?status=${nextFilter}`;
      const response = await fetch(`/api/v1/question-similarity${query}`, { cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const next: Workspace = await response.json();
      setWorkspace(next);
      setSelectedId((current) => next.items.some((item) => item.candidate_id === current) ? current : next.items[0]?.candidate_id || "");
      setSelectedQuestionIds([]);
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

  function toggleQuestion(questionId: string) {
    setSelectedQuestionIds((current) => current.includes(questionId) ? current.filter((value) => value !== questionId) : [...current, questionId]);
  }

  function prepareLibraryAction(action: "remove" | "restore") {
    if (!selected) return;
    const eligible = selected.members.filter((question) => selectedQuestionIds.includes(question.question_id) && (action === "remove" ? question.library_state === "active" : question.library_state === "removed"));
    if (!eligible.length) {
      toast(action === "remove" ? "请至少勾选一道当前在库的题目" : "请至少勾选一道已移出的题目");
      return;
    }
    setPendingLibraryAction({ action, questionIds: eligible.map((question) => question.question_id) });
  }

  async function confirmLibraryAction() {
    if (!selected || !pendingLibraryAction) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/question-similarity/${selected.candidate_id}/library-state`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_ids: pendingLibraryAction.questionIds, action: pendingLibraryAction.action, actor_id: "owner_teacher", reason: note.trim() || "重复题校对" }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const result = await response.json();
      toast(result.library.message);
      setPendingLibraryAction(null);
      setSelectedQuestionIds([]);
      await load(filter);
    } catch (error) {
      toast(error instanceof Error ? `题库状态修改失败：${error.message}` : "题库状态修改失败");
    } finally {
      setBusy(false);
    }
  }

  function chooseFilter(next: "all" | Status) {
    setFilter(next);
  }

  return <div className="page-content duplicate-page">
    <section className="page-title duplicate-title">
      <div><p className="eyebrow">题库治理 · 重复与变式识别</p><h1>题目关系校对台</h1><p className="subtle">教师确认关系后可将任意题目软移出正常题库；原题、图片、来源和审核历史仍可恢复。</p></div>
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
        <section className="duplicate-library-manager">
          <header><div><strong>题库保留与移出</strong><p>勾选一道或多道题后操作。软移出后不再参与搜题、组卷、教案和推荐，但可以在这里恢复。</p></div><span>{selected.members.filter((question) => question.library_state === "active").length}/{selected.members.length} 道在库</span></header>
          <div className="duplicate-member-list">{selected.members.map((question) => <label className={`${question.library_state} ${selectedQuestionIds.includes(question.question_id) ? "selected" : ""}`} key={question.question_id}>
            <input type="checkbox" checked={selectedQuestionIds.includes(question.question_id)} onChange={() => toggleQuestion(question.question_id)} />
            <span /><div><strong>{question.question_id}</strong><p>{question.stem_plain.replace(/\s+/g, " ").slice(0, 90)}</p><small>{question.source_document}</small></div><em>{question.library_state === "active" ? "正常在库" : "已软移出"}</em>
          </label>)}</div>
          {selected.status !== "confirmed" && <p className="duplicate-library-lock">请先在下方确认重复、同题或变式关系，再调整题目的在库状态。</p>}
          <footer><button type="button" className="restore" disabled={busy || selected.status !== "confirmed"} onClick={() => prepareLibraryAction("restore")}>恢复所选</button><button type="button" className="remove" disabled={busy || selected.status !== "confirmed"} onClick={() => prepareLibraryAction("remove")}>移出所选</button></footer>
        </section>
        {selected.status === "stale" ? <section className="duplicate-stale-note"><strong>这组判断已经过期</strong><p>其中至少一道题的内容已改变。请先重新扫描，再基于新版本确认关系。</p></section> : <section className="duplicate-decision">
          <header><div><strong>教师确认关系</strong><p>只保存关系记录，不改变两道题的正文、解析和发布状态。</p></div>{selected.teacher_relation && <span>当前：{relationLabels[selected.teacher_relation]}</span>}</header>
          <div className="duplicate-decision-buttons">
            {(Object.keys(relationLabels) as Relation[]).map((relation) => <button type="button" className={`${relation} ${selected.teacher_relation === relation ? "selected" : ""}`} disabled={busy} key={relation} onClick={() => void review(relation)}>{relationLabels[relation]}</button>)}
          </div>
          <label><span>校对备注（可选）</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="例如：题干完全相同，但第二份资料提供了另一种向量解法。" /></label>
        </section>}
      </main> : <div />}
    </ResizableColumns>}
    {pendingLibraryAction && <div className="duplicate-confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setPendingLibraryAction(null); }}><section className="duplicate-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="duplicate-confirm-title">
      <span>{pendingLibraryAction.action === "remove" ? "移" : "恢"}</span><h2 id="duplicate-confirm-title">{pendingLibraryAction.action === "remove" ? `确认软移出 ${pendingLibraryAction.questionIds.length} 道题？` : `确认恢复 ${pendingLibraryAction.questionIds.length} 道题？`}</h2>
      <p>{pendingLibraryAction.action === "remove" ? "这些题将立即停止参与搜题、组卷、教案和推荐。正文、解析、图片、来源与审核记录不会删除。" : "这些题将重新进入正常题库，并再次参与搜题、组卷、教案和推荐。"}</p>
      <ul>{pendingLibraryAction.questionIds.map((questionId) => <li key={questionId}>{questionId}</li>)}</ul>
      <footer><button type="button" disabled={busy} onClick={() => setPendingLibraryAction(null)}>取消</button><button type="button" className={pendingLibraryAction.action} disabled={busy} onClick={() => void confirmLibraryAction()}>{busy ? "处理中…" : pendingLibraryAction.action === "remove" ? "确认软移出" : "确认恢复"}</button></footer>
    </section></div>}
  </div>;
}

export default function DuplicatePage() {
  return <AdminGuard><DuplicateDashboard /></AdminGuard>;
}
