"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type ReviewStatus = "pending" | "draft" | "approved" | "changes_requested";
type ReviewDecision = Exclude<ReviewStatus, "pending">;
type Priority = "high" | "medium" | "low";

type CurriculumNode = {
  node_id: string; parent_id: string | null; volume: string; node_type: string;
  code: string; name: string; description: string; primary_competencies: string[];
  typical_question_types: string[]; common_errors: string[]; gaokao_priority: Priority;
  status: string; reviewed_by: string;
};
type EditableNode = Pick<CurriculumNode, "name" | "description" | "primary_competencies" | "typical_question_types" | "common_errors" | "gaokao_priority">;
type ReviewSummary = Pick<CurriculumNode, "node_id" | "parent_id" | "volume" | "node_type" | "code" | "name" | "description"> & {
  review_status: ReviewStatus; latest_reviewed_at: string | null; descendant_count: number;
};
type ReviewRecord = { review_id: string; node_id: string; decision: ReviewDecision; changes: Partial<EditableNode>; note: string; reviewer_id: string; created_at: string };
type ReviewDetail = { base_node: CurriculumNode; effective_node: CurriculumNode; review_status: ReviewStatus; descendant_count: number; history: ReviewRecord[] };
type ReviewWorkspace = { volume: string | null; volume_node_id: string | null; counts: Record<ReviewStatus | "total", number>; items: ReviewSummary[] };

const volumes = ["必修第一册", "必修第二册", "选择性必修第一册", "选择性必修第二册", "选择性必修第三册"];
const statusLabels: Record<ReviewStatus, string> = { pending: "待审核", draft: "已存草稿", approved: "已批准", changes_requested: "需修改" };
const nodeTypeLabels: Record<string, string> = { volume: "册", chapter: "章", section: "节", knowledge_point: "知识点" };
const priorityLabels: Record<Priority, string> = { high: "高", medium: "中", low: "低" };

function lines(value: string) { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function editable(node: CurriculumNode): EditableNode {
  return { name: node.name, description: node.description, primary_competencies: [...node.primary_competencies], typical_question_types: [...node.typical_question_types], common_errors: [...node.common_errors], gaokao_priority: node.gaokao_priority };
}
async function responseError(response: Response) {
  try { const payload = await response.json(); return payload.detail ?? `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}

export default function CurriculumReviewPage() {
  const [volume, setVolume] = useState(volumes[0]);
  const [nodeType, setNodeType] = useState("section");
  const [reviewStatus, setReviewStatus] = useState("");
  const [query, setQuery] = useState("");
  const [workspace, setWorkspace] = useState<ReviewWorkspace | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [draft, setDraft] = useState<EditableNode | null>(null);
  const [note, setNote] = useState("");
  const [cascade, setCascade] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("volume");
    if (requested && volumes.includes(requested)) setVolume(requested);
  }, []);

  const loadWorkspace = useCallback(async () => {
    setLoading(true); setError("");
    const params = new URLSearchParams({ volume, node_type: nodeType, limit: "1000" });
    if (query.trim()) params.set("query", query.trim());
    if (reviewStatus) params.set("review_status", reviewStatus);
    try {
      const response = await fetch(`/api/v1/curriculum/reviews?${params}`);
      if (!response.ok) throw new Error(await responseError(response));
      const payload: ReviewWorkspace = await response.json();
      setWorkspace(payload);
      setSelectedId((current) => payload.items.some((item) => item.node_id === current) ? current : payload.items[0]?.node_id ?? "");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "目录审核接口暂不可用"); }
    finally { setLoading(false); }
  }, [nodeType, query, reviewStatus, volume]);

  useEffect(() => { const timer = window.setTimeout(loadWorkspace, 180); return () => window.clearTimeout(timer); }, [loadWorkspace]);

  const loadDetail = useCallback(async (nodeId: string) => {
    if (!nodeId) { setDetail(null); setDraft(null); return; }
    setError("");
    try {
      const response = await fetch(`/api/v1/curriculum/reviews/${encodeURIComponent(nodeId)}`);
      if (!response.ok) throw new Error(await responseError(response));
      const payload: ReviewDetail = await response.json();
      setDetail(payload); setDraft(editable(payload.effective_node)); setNote(""); setCascade(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取目录节点"); }
  }, []);
  useEffect(() => { loadDetail(selectedId); }, [loadDetail, selectedId]);

  const changedFields = useMemo(() => {
    if (!detail || !draft) return 0;
    const base = editable(detail.base_node);
    return (Object.keys(base) as (keyof EditableNode)[]).filter((key) => JSON.stringify(base[key]) !== JSON.stringify(draft[key])).length;
  }, [detail, draft]);

  async function submit(decision: ReviewDecision, targetId = selectedId, useCascade = cascade) {
    if (!targetId) return;
    if (decision === "changes_requested" && !note.trim()) { setError("退回修改时请填写审核意见。"); return; }
    setSaving(true); setError(""); setMessage("");
    try {
      const response = await fetch(`/api/v1/curriculum/reviews/${encodeURIComponent(targetId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, changes: targetId === selectedId && draft ? draft : {}, note: targetId === selectedId ? note : "教师批量批准本册目录", reviewer_id: "owner_teacher", cascade: useCascade }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json(); setMessage(result.message);
      await loadWorkspace(); if (targetId === selectedId) await loadDetail(selectedId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "审核保存失败"); }
    finally { setSaving(false); }
  }

  async function approveVolume() {
    if (!workspace?.volume_node_id) return;
    if (window.confirm(`将把“${volume}”及全部下级节点标记为已批准。原始目录不会被改写，是否继续？`)) await submit("approved", workspace.volume_node_id, true);
  }

  function setListField(field: "primary_competencies" | "typical_question_types" | "common_errors", value: string) {
    setDraft((current) => current ? { ...current, [field]: lines(value) } : current);
  }
  const original = detail ? editable(detail.base_node) : null;

  return <div className="page-content curriculum-review-page">
    <section className="page-title curriculum-review-title">
      <div><p className="eyebrow">教材治理 · 教师私有工作区</p><h1>教材目录审核台</h1><p className="subtle">逐项修订人教 A 版目录；每次提交留存记录，并同步用于搜索、题库标注和教案生成。</p></div>
      <div className="curriculum-page-actions"><a className="review-secondary-button" href="/curriculum">返回教材目录</a><button className="primary-button" type="button" disabled={saving || !workspace?.volume_node_id} onClick={approveVolume}>批准本册全部</button></div>
    </section>
    <div className="curriculum-review-safety"><strong>原始目录受保护</strong><span>审核结果以独立版本记录保存；草稿可供您的备课流程试用，只有“已批准”才表示教师终审完成。</span></div>
    {error && <div className="notice warning">{error}</div>}{message && <div className="notice review-success">{message}</div>}

    <section className="catalog-review-layout">
      <aside className="catalog-review-sidebar">
        <div className="catalog-review-filters">
          <label><span>教材册次</span><select value={volume} onChange={(e) => setVolume(e.target.value)}>{volumes.map((item) => <option key={item}>{item}</option>)}</select></label>
          <div className="catalog-review-filter-row">
            <label><span>节点层级</span><select value={nodeType} onChange={(e) => setNodeType(e.target.value)}><option value="volume">册</option><option value="chapter">章</option><option value="section">节</option><option value="knowledge_point">知识点</option></select></label>
            <label><span>审核状态</span><select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}><option value="">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          </div>
          <label><span>筛选目录</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入编号、名称或描述" /></label>
        </div>
        <div className="catalog-review-counts">{(["pending", "draft", "approved", "changes_requested"] as ReviewStatus[]).map((status) => <button type="button" className={reviewStatus === status ? "active" : ""} key={status} onClick={() => setReviewStatus(reviewStatus === status ? "" : status)}><strong>{workspace?.counts[status] ?? 0}</strong><span>{statusLabels[status]}</span></button>)}</div>
        <div className="catalog-review-list-heading"><strong>{nodeTypeLabels[nodeType]}目录</strong><span>{workspace?.items.length ?? 0} 项</span></div>
        <div className="catalog-review-list">
          {loading && <p className="catalog-review-empty">正在读取审核目录…</p>}
          {!loading && !workspace?.items.length && <p className="catalog-review-empty">当前筛选条件下没有目录节点。</p>}
          {workspace?.items.map((item) => <button type="button" key={item.node_id} className={selectedId === item.node_id ? "selected" : ""} onClick={() => setSelectedId(item.node_id)}><span className={`review-status-dot ${item.review_status}`} /><span><b>{item.code} {item.name}</b><small>{nodeTypeLabels[item.node_type]} · {item.descendant_count ? `${item.descendant_count} 个下级` : "末级节点"}</small></span><em className={item.review_status}>{statusLabels[item.review_status]}</em></button>)}
        </div>
      </aside>

      <main className="catalog-review-editor">{!detail || !draft || !original ? <div className="catalog-review-editor-empty"><strong>选择左侧目录开始审核</strong><p>建议先审核“节”，再进入知识点逐项校对。</p></div> : <>
        <header className="catalog-review-editor-heading"><div><p>{detail.effective_node.volume} · {nodeTypeLabels[detail.effective_node.node_type]}</p><h2>{detail.effective_node.code} {detail.effective_node.name}</h2><span>节点 ID：{detail.effective_node.node_id}</span></div><div className="catalog-review-heading-status"><em className={detail.review_status}>{statusLabels[detail.review_status]}</em><small>{changedFields ? `${changedFields} 项相对原始目录有变更` : "与原始目录一致"}</small></div></header>
        <div className="catalog-review-form">
          <ReviewField label="目录名称" original={original.name} changed={draft.name !== original.name}><input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></ReviewField>
          <div className="catalog-review-form-row"><ReviewField label="高考优先级" original={priorityLabels[original.gaokao_priority]} changed={draft.gaokao_priority !== original.gaokao_priority}><select value={draft.gaokao_priority} onChange={(e) => setDraft({ ...draft, gaokao_priority: e.target.value as Priority })}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></ReviewField><div className="catalog-review-readonly"><span>下级节点</span><strong>{detail.descendant_count}</strong><small>级联操作会同时影响这些节点</small></div></div>
          <ReviewField label="教学说明" original={original.description} changed={draft.description !== original.description}><textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={4} /></ReviewField>
          <ReviewField label="核心素养（每行一项）" original={original.primary_competencies.join("、")} changed={JSON.stringify(draft.primary_competencies) !== JSON.stringify(original.primary_competencies)}><textarea value={draft.primary_competencies.join("\n")} onChange={(e) => setListField("primary_competencies", e.target.value)} rows={3} /></ReviewField>
          <div className="catalog-review-form-row"><ReviewField label="典型题型（每行一项）" original={original.typical_question_types.join("、")} changed={JSON.stringify(draft.typical_question_types) !== JSON.stringify(original.typical_question_types)}><textarea value={draft.typical_question_types.join("\n")} onChange={(e) => setListField("typical_question_types", e.target.value)} rows={5} /></ReviewField><ReviewField label="常见错误（每行一项）" original={original.common_errors.join("、")} changed={JSON.stringify(draft.common_errors) !== JSON.stringify(original.common_errors)}><textarea value={draft.common_errors.join("\n")} onChange={(e) => setListField("common_errors", e.target.value)} rows={5} /></ReviewField></div>
          <ReviewField label="审核意见" hint="退回修改时必填；草稿和批准时可作为版本备注。"><textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="记录修改依据、待核对项或批准说明" /></ReviewField>
        </div>
        <div className="catalog-review-actions">{detail.effective_node.node_type !== "knowledge_point" && <label><input type="checkbox" checked={cascade} onChange={(e) => setCascade(e.target.checked)} />同时处理全部下级节点（{detail.descendant_count} 项）</label>}<div><button type="button" className="review-secondary-button" disabled={saving} onClick={() => submit("draft")}>保存草稿</button><button type="button" className="review-danger-button" disabled={saving} onClick={() => submit("changes_requested")}>退回修改</button><button type="button" className="primary-button" disabled={saving} onClick={() => submit("approved")}>{saving ? "正在保存…" : "批准通过"}</button></div></div>
        <section className="catalog-review-history"><header><h3>审核记录</h3><span>{detail.history.length} 条</span></header>{!detail.history.length && <p>暂无记录。第一次保存后，这里会保留审核时间、处理人和意见。</p>}{detail.history.map((record) => <article key={record.review_id}><span className={`review-status-dot ${record.decision}`} /><div><strong>{statusLabels[record.decision]}</strong><p>{record.note || "未填写备注"}</p><small>{record.reviewer_id} · {new Date(record.created_at).toLocaleString("zh-CN", { hour12: false })}</small></div></article>)}</section>
      </>}</main>
    </section>
  </div>;
}

function ReviewField({ label, original, changed = false, hint, children }: { label: string; original?: string; changed?: boolean; hint?: string; children: React.ReactNode }) {
  return <label className={`catalog-review-field ${changed ? "changed" : ""}`}><span>{label}{changed && <em>已修改</em>}</span>{children}{hint && <small>{hint}</small>}{changed && original !== undefined && <small className="catalog-review-original">原始值：{original || "（空）"}</small>}</label>;
}
