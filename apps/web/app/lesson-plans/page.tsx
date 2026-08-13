"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ResizableColumns } from "../components/resizable-columns";
import { useToast } from "../components/toast-provider";
import { longTaskApiUrl } from "../components/api-url";

type CurriculumNode = {
  node_id: string;
  node_type: string;
  code: string;
  name: string;
  children: CurriculumNode[];
};

type CurriculumOption = { id: string; label: string; type: string };

type TeachingPhase = {
  phase: string;
  minutes: number;
  teacher_activity: string;
  student_activity: string;
  assessment: string;
};

type RecommendedQuestion = {
  question_id: string;
  stem: string;
  difficulty: number;
  usage: string;
  verification_status: string;
};

type LessonPlanContent = {
  title: string;
  objectives: string[];
  key_points: string[];
  difficulties: string[];
  teaching_flow: TeachingPhase[];
  homework: string[];
  board_plan: string[];
  teacher_notes: string[];
  recommended_questions: RecommendedQuestion[];
};

type EditableListField = "objectives" | "key_points" | "difficulties" | "homework" | "board_plan" | "teacher_notes";
type LessonPlanBlock = EditableListField | "teaching_flow";

type LessonPlanBlockRewriteResult = {
  block: LessonPlanBlock;
  value: string[] | TeachingPhase[];
  provider: string;
  model: string;
  mode: string;
  warnings: string[];
};

type PendingRewrite = {
  block: LessonPlanBlock;
  before: string[] | TeachingPhase[];
  after: string[] | TeachingPhase[];
  mode: string;
};

type LessonPlan = {
  lesson_plan_id: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
  lifecycle_state: "active" | "trashed";
  request: {
    curriculum_node_id: string;
    lesson_type: string;
    duration_minutes: number;
    student_profile: string;
    focus: string;
    question_count: number;
  };
  curriculum: {
    volume: string;
    chapter: string;
    section: string;
    topic: string;
    knowledge_points: string[];
  };
  content: LessonPlanContent;
  generation: {
    provider: string;
    model: string;
    mode: string;
    warnings: string[];
  };
  locked_blocks: LessonPlanBlock[];
};

type LessonPlanSummary = {
  lesson_plan_id: string;
  title: string;
  status: string;
  version: number;
  topic: string;
  lifecycle_state: "active" | "trashed";
  provider: string;
  updated_at: string;
};

const apiBase = "";

const lessonTypeLabels: Record<string, string> = {
  new_lesson: "新授课",
  review: "复习课",
  exercise: "习题课",
};

const blockLabels: Record<LessonPlanBlock, string> = {
  objectives: "教学目标",
  key_points: "教学重点",
  difficulties: "教学难点",
  teaching_flow: "教学流程",
  homework: "分层作业",
  board_plan: "板书设计",
  teacher_notes: "教师备注",
};

const rewriteDefaults: Record<LessonPlanBlock, string> = {
  objectives: "让目标更具体、可观察、可评价",
  key_points: "突出本课核心概念与关键条件",
  difficulties: "补充认知冲突、易错点和纠错支架",
  teaching_flow: "增强课堂追问、学生活动和评价证据之间的对应",
  homework: "优化分层梯度并要求学生写出关键依据",
  board_plan: "压缩文字并突出概念、方法和易错检查",
  teacher_notes: "补充实施提醒和课后观察重点",
};

function curriculumOptions(root: CurriculumNode): CurriculumOption[] {
  const items: CurriculumOption[] = [];
  function visit(node: CurriculumNode, volume = "", chapter = "") {
    const volumeName = node.node_type === "volume" ? node.name : volume;
    const chapterName = node.node_type === "chapter" ? node.name : chapter;
    if (node.node_type === "section" || node.node_type === "knowledge_point") {
      const prefix = node.node_type === "knowledge_point" ? "　└ " : "";
      items.push({ id: node.node_id, label: `${volumeName} · ${chapterName} / ${prefix}${node.code} ${node.name}`, type: node.node_type });
    }
    node.children?.forEach((child) => visit(child, volumeName, chapterName));
  }
  visit(root);
  return items;
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    return payload.detail ?? `请求失败（HTTP ${response.status}）`;
  } catch {
    return `请求失败（HTTP ${response.status}）`;
  }
}

export default function LessonPlansPage() {
  const [options, setOptions] = useState<CurriculumOption[]>([]);
  const [plans, setPlans] = useState<LessonPlanSummary[]>([]);
  const [showTrash, setShowTrash] = useState(false);
  const [selected, setSelected] = useState<LessonPlan | null>(null);
  const [draft, setDraft] = useState<LessonPlanContent | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [lockingBlock, setLockingBlock] = useState<LessonPlanBlock | null>(null);
  const [rewritingBlock, setRewritingBlock] = useState<LessonPlanBlock | null>(null);
  const [activeRewriteBlock, setActiveRewriteBlock] = useState<LessonPlanBlock | null>(null);
  const [pendingRewrite, setPendingRewrite] = useState<PendingRewrite | null>(null);
  const [lastAcceptedRewrite, setLastAcceptedRewrite] = useState<Pick<PendingRewrite, "block" | "before"> | null>(null);
  const [rewriteInstructions, setRewriteInstructions] = useState<Record<LessonPlanBlock, string>>(rewriteDefaults);
  const { auto: setMessage } = useToast();
  const [form, setForm] = useState({
    curriculum_node_id: "",
    lesson_type: "new_lesson",
    duration_minutes: 45,
    student_profile: "高一平行班，基础中等；能完成教材基础练习，但数学语言表达需要支架",
    focus: "突出概念形成过程、易错点辨析和课堂可评价性",
    question_count: 3,
  });

  const minuteTotal = useMemo(
    () => draft?.teaching_flow.reduce((sum, item) => sum + Number(item.minutes || 0), 0) ?? 0,
    [draft],
  );

  async function loadPlans(selectLatest = false) {
    const response = await fetch(`${apiBase}/api/v1/lesson-plans?lifecycle_state=${showTrash ? "trashed" : "active"}`);
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    setPlans(payload.items);
    if (selectLatest && payload.items[0]) await openPlan(payload.items[0].lesson_plan_id);
  }

  async function openPlan(id: string) {
    const response = await fetch(`${apiBase}/api/v1/lesson-plans/${id}`);
    if (!response.ok) throw new Error(await responseError(response));
    const plan: LessonPlan = await response.json();
    setSelected(plan);
    setDraft(plan.content);
    setActiveRewriteBlock(null);
    setPendingRewrite(null);
    setLastAcceptedRewrite(null);
  }

  useEffect(() => {
    loadPlans().catch((error: Error) => setMessage(error.message));
  }, [showTrash]);

  async function changeLifecycle(action: "trash" | "restore") {
    if (!selected) return;
    if (action === "trash" && !window.confirm("教案将移入回收站，正文、版本与导出信息均保留。继续吗？")) return;
    const response = await fetch(`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}/lifecycle`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, reason: action === "trash" ? "用户移入教案回收站" : "用户恢复教案" }) });
    if (!response.ok) throw new Error(await responseError(response));
    setSelected(null); setDraft(null); await loadPlans(); setMessage(action === "trash" ? "教案已移入回收站，可随时恢复。" : "教案已恢复。" );
  }

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase}/api/v1/curriculum/tree`).then((response) => {
        if (!response.ok) throw new Error("课程接口不可用");
        return response.json();
      }),
      fetch(`${apiBase}/api/v1/lesson-plans`).then((response) => {
        if (!response.ok) throw new Error("教案接口不可用");
        return response.json();
      }),
    ])
      .then(([tree, planList]) => {
        const nextOptions = curriculumOptions(tree);
        setOptions(nextOptions);
        const preferred = nextOptions.find((item) => item.id === "pep_a_r1_c3_s2") ?? nextOptions[0];
        if (preferred) setForm((current) => ({ ...current, curriculum_node_id: preferred.id }));
        setPlans(planList.items);
      })
      .catch((error: Error) => setMessage(`${error.message}，请确认 FastAPI 已启动。`));
  }, []);

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (!form.curriculum_node_id) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(longTaskApiUrl(`${apiBase}/api/v1/lesson-plans/generate`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const plan: LessonPlan = await response.json();
      setSelected(plan);
      setDraft(plan.content);
      setActiveRewriteBlock(null);
      setPendingRewrite(null);
      setLastAcceptedRewrite(null);
      await loadPlans();
      setMessage(plan.generation.mode === "live_ai" ? "AI 教案初稿已生成，请逐项审核。" : "本地预览教案已生成；配置 API Key 后将自动切换真实 AI。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "教案生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!selected || !draft) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: draft, editor_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const plan: LessonPlan = await response.json();
      setSelected(plan);
      setDraft(plan.content);
      setLastAcceptedRewrite(null);
      await loadPlans();
      setMessage(`已保存为第 ${plan.version} 版。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function isBlockLocked(block: LessonPlanBlock) {
    return selected?.locked_blocks?.includes(block) ?? false;
  }

  async function toggleBlockLock(block: LessonPlanBlock) {
    if (!selected) return;
    const locked = isBlockLocked(block);
    setLockingBlock(block);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}/blocks/${block}/lock`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ locked: !locked, editor_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const plan: LessonPlan = await response.json();
      setSelected(plan);
      await loadPlans();
      if (!locked) {
        setActiveRewriteBlock((current) => current === block ? null : current);
        setPendingRewrite((current) => current?.block === block ? null : current);
      }
      setMessage(!locked ? `${blockLabels[block]}已锁定，AI 不会改写这一部分。` : `${blockLabels[block]}已解锁，可以再次局部改写。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "锁定状态更新失败");
    } finally {
      setLockingBlock(null);
    }
  }

  async function rewriteBlock(block: LessonPlanBlock) {
    if (!selected || !draft || isBlockLocked(block)) return;
    setRewritingBlock(block);
    setMessage(null);
    try {
      const response = await fetch(longTaskApiUrl(`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}/blocks/${block}/rewrite`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: rewriteInstructions[block],
          content: draft,
          teacher_id: "owner_teacher",
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result: LessonPlanBlockRewriteResult = await response.json();
      const before = block === "teaching_flow" ? draft.teaching_flow : draft[block];
      setPendingRewrite({ block, before, after: result.value, mode: result.mode });
      setActiveRewriteBlock(null);
      setMessage(`${blockLabels[block]}已生成${result.mode === "live_ai" ? " AI" : "本地预览"}改写草稿，请先对比再决定是否接受。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "局部改写失败");
    } finally {
      setRewritingBlock(null);
    }
  }

  function applyBlockValue(block: LessonPlanBlock, value: string[] | TeachingPhase[]) {
    if (block === "teaching_flow") {
      setDraft((current) => current ? { ...current, teaching_flow: value as TeachingPhase[] } : current);
    } else {
      setDraft((current) => current ? { ...current, [block]: value as string[] } : current);
    }
  }

  function acceptPendingRewrite() {
    if (!pendingRewrite) return;
    applyBlockValue(pendingRewrite.block, pendingRewrite.after);
    setLastAcceptedRewrite({ block: pendingRewrite.block, before: pendingRewrite.before });
    setMessage(`${blockLabels[pendingRewrite.block]}改写已接受但尚未保存，可继续手工调整或撤销。`);
    setPendingRewrite(null);
  }

  function undoAcceptedRewrite() {
    if (!lastAcceptedRewrite) return;
    applyBlockValue(lastAcceptedRewrite.block, lastAcceptedRewrite.before);
    setMessage(`已撤销上次对${blockLabels[lastAcceptedRewrite.block]}的 AI 改写。`);
    setLastAcceptedRewrite(null);
  }

  function rewriteLines(value: string[] | TeachingPhase[], block: LessonPlanBlock) {
    if (block !== "teaching_flow") return (value as string[]).map((item, index) => `${index + 1}. ${item}`);
    return (value as TeachingPhase[]).map((item, index) => `${index + 1}. ${item.phase} · ${item.minutes} 分钟\n教师：${item.teacher_activity}\n学生：${item.student_activity}\n评价：${item.assessment}`);
  }

  function renderRewritePreview(block: LessonPlanBlock) {
    if (!pendingRewrite || pendingRewrite.block !== block) return null;
    return (
      <section className="rewrite-review-panel" aria-label={`${blockLabels[block]}改写对比`}>
        <header><div><strong>改写待审核</strong><span>{pendingRewrite.mode === "live_ai" ? "AI 生成" : "本地预览"}</span></div><small>接受后仍需“保存修订”才会写入版本历史</small></header>
        <div className="rewrite-compare-grid">
          <div><h4>修改前</h4>{rewriteLines(pendingRewrite.before, block).map((line, index) => <p key={index}>{line}</p>)}</div>
          <div className="rewrite-after"><h4>修改后</h4>{rewriteLines(pendingRewrite.after, block).map((line, index) => <p key={index}>{line}</p>)}</div>
        </div>
        <footer><button type="button" onClick={() => setPendingRewrite(null)}>放弃改写</button><button type="button" className="accept" onClick={acceptPendingRewrite}>接受这次改写</button></footer>
      </section>
    );
  }

  function renderBlockTools(block: LessonPlanBlock, addItem?: () => void) {
    const locked = isBlockLocked(block);
    return (
      <div className="block-tools">
        {locked && <span className="block-lock-badge">AI 已锁定</span>}
        <button type="button" disabled={lockingBlock !== null || rewritingBlock !== null} onClick={() => toggleBlockLock(block)}>
          {lockingBlock === block ? "处理中…" : locked ? "解锁 AI" : "锁定 AI"}
        </button>
        <button type="button" disabled={locked || lockingBlock !== null || rewritingBlock !== null} onClick={() => setActiveRewriteBlock((current) => current === block ? null : block)}>
          {activeRewriteBlock === block ? "收起改写" : "AI 改写"}
        </button>
        {addItem && <button type="button" onClick={addItem}>＋ 添加</button>}
      </div>
    );
  }

  function renderRewriteBar(block: LessonPlanBlock) {
    if (activeRewriteBlock !== block || isBlockLocked(block)) return null;
    return (
      <div className="block-rewrite-bar">
        <label><span>改写要求</span><input value={rewriteInstructions[block]} onChange={(event) => setRewriteInstructions({ ...rewriteInstructions, [block]: event.target.value })} /></label>
        <button type="button" disabled={rewritingBlock !== null || rewriteInstructions[block].trim().length < 2} onClick={() => rewriteBlock(block)}>
          {rewritingBlock === block ? "正在改写…" : "生成待审核草稿"}
        </button>
      </div>
    );
  }

  function updateList(field: EditableListField, index: number, value: string) {
    setDraft((current) => current ? { ...current, [field]: current[field].map((item, itemIndex) => itemIndex === index ? value : item) } : current);
  }

  function addListItem(field: EditableListField) {
    setDraft((current) => current ? { ...current, [field]: [...current[field], ""] } : current);
  }

  function removeListItem(field: EditableListField, index: number) {
    setDraft((current) => current ? { ...current, [field]: current[field].filter((_, itemIndex) => itemIndex !== index) } : current);
  }

  function updatePhase(index: number, field: keyof TeachingPhase, value: string | number) {
    setDraft((current) => current ? {
      ...current,
      teaching_flow: current.teaching_flow.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item),
    } : current);
  }

  function renderEditableList(title: string, field: EditableListField) {
    if (!draft) return null;
    return (
      <section className={`lesson-editor-card ${isBlockLocked(field) ? "ai-locked" : ""}`}>
        <header><h3>{title}</h3>{renderBlockTools(field, () => addListItem(field))}</header>
        {renderRewriteBar(field)}
        {renderRewritePreview(field)}
        <div className="lesson-list-editor">
          {draft[field].map((item, index) => (
            <div key={`${field}-${index}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <textarea value={item} onChange={(event) => updateList(field, index, event.target.value)} />
              <button type="button" aria-label={`删除${title}第${index + 1}项`} onClick={() => removeListItem(field, index)}>×</button>
            </div>
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="page-content lesson-page">
      <section className="page-title lesson-title">
        <div>
          <p className="eyebrow">AI 教案 · 人教 A 版</p>
          <h1>从教材目标到一节可执行的课。</h1>
          <p className="subtle">课程树负责边界，已验证题库提供例题，AI 生成初稿，最终决定权始终属于教师。</p>
        </div>
        <div className="lesson-safety-badge"><strong>教师审核优先</strong><span>生成内容默认仅自己可见</span></div>
      </section>


      <ResizableColumns className="lesson-builder-layout" storageKey="lesson-builder" initialLeftPercent={30} leftMin={260} rightMin={440} collapse="compact" label="调整教案设置与教案正文宽度">
        <aside className="lesson-control-panel">
          <form onSubmit={generate}>
            <div className="control-heading"><span>01</span><div><h2>生成设置</h2><p>先定义这一课要解决什么</p></div></div>
            <label>教材章节<select value={form.curriculum_node_id} onChange={(event) => setForm({ ...form, curriculum_node_id: event.target.value })}>
              {options.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select></label>
            <div className="control-grid">
              <label>课型<select value={form.lesson_type} onChange={(event) => setForm({ ...form, lesson_type: event.target.value })}>
                {Object.entries(lessonTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></label>
              <label>课时<input type="number" min="20" max="120" value={form.duration_minutes} onChange={(event) => setForm({ ...form, duration_minutes: Number(event.target.value) })} /><small>分钟</small></label>
            </div>
            <label>班级学情<textarea value={form.student_profile} onChange={(event) => setForm({ ...form, student_profile: event.target.value })} /></label>
            <label>本课侧重点<textarea value={form.focus} onChange={(event) => setForm({ ...form, focus: event.target.value })} /></label>
            <label>推荐例题数量<input type="range" min="0" max="5" value={form.question_count} onChange={(event) => setForm({ ...form, question_count: Number(event.target.value) })} /><b>{form.question_count} 道</b></label>
            <button className="lesson-generate-button" disabled={busy || !form.curriculum_node_id} type="submit">{busy ? "正在组织课程与题库…" : "生成教案初稿"}</button>
            <p className="provider-note">未配置模型时使用确定性本地模板；配置后自动使用 Responses API 结构化生成。</p>
          </form>

          <section className="lesson-history">
            <header><strong>{showTrash ? "教案回收站" : "最近教案"}</strong><button type="button" onClick={() => { setShowTrash((current) => !current); setSelected(null); setDraft(null); }}>{showTrash ? "返回" : "回收站"}</button><span>{plans.length}</span></header>
            {plans.map((plan) => (
              <button className={selected?.lesson_plan_id === plan.lesson_plan_id ? "active" : ""} type="button" key={plan.lesson_plan_id} onClick={() => openPlan(plan.lesson_plan_id).catch((error: Error) => setMessage(error.message))}>
                <span>{plan.provider === "openai" ? "AI" : "稿"}</span><div><b>{plan.title}</b><small>{plan.topic} · v{plan.version}</small></div>
              </button>
            ))}
            {!plans.length && <p>生成的第一份教案会出现在这里。</p>}
          </section>
        </aside>

        <main className="lesson-editor">
          {!draft || !selected ? (
            <div className="lesson-empty">
              <span>教</span><h2>从左侧生成第一份教案</h2><p>推荐先选择“3.2 函数的基本性质”，它已经可以联动当前验证通过的函数题库。</p>
            </div>
          ) : (
            <>
              <header className="lesson-document-heading">
                <div><p>{selected.curriculum.volume} · {selected.curriculum.chapter} · {selected.curriculum.section}</p><input aria-label="教案标题" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></div>
                <div className="document-actions">
                  <span>{selected.generation.mode === "live_ai" ? "AI 生成" : "本地预览"} · v{selected.version}</span>
                  <a href={`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}/export?format=docx`} title="导出当前已保存版本">导出 Word</a>
                  <a href={`${apiBase}/api/v1/lesson-plans/${selected.lesson_plan_id}/export?format=pdf`} title="导出当前已保存版本">导出 PDF</a>
                  <button type="button" disabled={saving || minuteTotal !== selected.request.duration_minutes} onClick={save}>{saving ? "保存中…" : "保存修订"}</button>
                  <button type="button" onClick={() => changeLifecycle(selected.lifecycle_state === "trashed" ? "restore" : "trash")}>{selected.lifecycle_state === "trashed" ? "恢复教案" : "移入回收站"}</button>
                  {lastAcceptedRewrite && <button className="undo-rewrite" type="button" onClick={undoAcceptedRewrite}>撤销 AI 改写</button>}
                </div>
              </header>

              <div className="lesson-context-strip">
                <div><span>课型</span><strong>{lessonTypeLabels[selected.request.lesson_type]}</strong></div>
                <div><span>课时</span><strong>{selected.request.duration_minutes} 分钟</strong></div>
                <div><span>知识点</span><strong>{selected.curriculum.knowledge_points.length} 个</strong></div>
                <div><span>题库例题</span><strong>{draft.recommended_questions.length} 道</strong></div>
              </div>

              {selected.generation.warnings.map((warning) => <div className="lesson-warning" key={warning}>○ {warning}</div>)}

              <div className="lesson-editor-two-column">
                {renderEditableList("教学目标", "objectives")}
                <div>
                  {renderEditableList("教学重点", "key_points")}
                  {renderEditableList("教学难点", "difficulties")}
                </div>
              </div>

              <section className={`lesson-flow-card ${isBlockLocked("teaching_flow") ? "ai-locked" : ""}`}>
                <header>
                  <div><h3>教学流程</h3><p>时间、教师活动、学生活动和评价证据</p></div>
                  <div className="flow-header-tools">
                    <strong className={minuteTotal === selected.request.duration_minutes ? "valid" : "invalid"}>{minuteTotal} / {selected.request.duration_minutes} 分钟</strong>
                    {renderBlockTools("teaching_flow")}
                  </div>
                </header>
                {renderRewriteBar("teaching_flow")}
                {renderRewritePreview("teaching_flow")}
                <div className="lesson-flow-list">
                  {draft.teaching_flow.map((phase, index) => (
                    <article key={index}>
                      <div className="phase-number">{String(index + 1).padStart(2, "0")}</div>
                      <div className="phase-fields">
                        <div className="phase-title"><input value={phase.phase} onChange={(event) => updatePhase(index, "phase", event.target.value)} /><label><input type="number" min="1" value={phase.minutes} onChange={(event) => updatePhase(index, "minutes", Number(event.target.value))} /> 分钟</label></div>
                        <label><span>教师活动</span><textarea value={phase.teacher_activity} onChange={(event) => updatePhase(index, "teacher_activity", event.target.value)} /></label>
                        <label><span>学生活动</span><textarea value={phase.student_activity} onChange={(event) => updatePhase(index, "student_activity", event.target.value)} /></label>
                        <label><span>评价证据</span><textarea value={phase.assessment} onChange={(event) => updatePhase(index, "assessment", event.target.value)} /></label>
                      </div>
                    </article>
                  ))}
                </div>
              </section>

              <section className="lesson-editor-card question-recommendations">
                <header><h3>题库联动</h3><span>仅使用独立验证通过的题目</span></header>
                {draft.recommended_questions.map((question, index) => (
                  <article key={question.question_id}><b>{String(index + 1).padStart(2, "0")}</b><div><span>{question.usage} · 难度 {question.difficulty}/5</span><p>{question.stem}</p><small>{question.question_id} · 验证通过</small></div></article>
                ))}
                {!draft.recommended_questions.length && <p className="subtle">当前课程节点暂无可用题目，后续扩充题库后可重新生成。</p>}
              </section>

              <div className="lesson-editor-two-column lower">
                {renderEditableList("分层作业", "homework")}
                {renderEditableList("板书设计", "board_plan")}
              </div>
              {renderEditableList("教师备注", "teacher_notes")}
            </>
          )}
        </main>
      </ResizableColumns>
    </div>
  );
}
