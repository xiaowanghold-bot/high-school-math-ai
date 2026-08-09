"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { MathText } from "../components/math-text";

type Question = { question_id: string; review_status: string; question_type: string; stem_plain: string; answer_value: string | null; chapter: string | null; section: string | null; difficulty: number; verification_status: string; source_document: string };
type PaperQuestionSnapshot = Question & { stem_latex: string | null; images: { asset_id: string }[] };
type PaperItem = { item_id: string; position: number; section_title: string; score: number; question: PaperQuestionSnapshot };
type Breakdown = { label: string; question_count: number; score: number };
type Paper = { exam_paper_id: string; status: string; version: number; title: string; duration_minutes: number; instructions: string; total_score: number; items: PaperItem[]; chapter_breakdown: Breakdown[]; difficulty_breakdown: Breakdown[]; warnings: string[]; updated_at: string };
type PaperSummary = { exam_paper_id: string; title: string; version: number; duration_minutes: number; total_score: number; question_count: number; updated_at: string };
type DraftItem = { question: Question; score: number };
type PaperProposal = { target_score: number; actual_score: number; average_difficulty: number; items: { question: Question; score: number; selection_reason: string }[]; chapter_breakdown: Breakdown[]; difficulty_breakdown: Breakdown[]; warnings: string[] };
type PaperTemplateSection = { section_title: string; question_type: string; count: number; item_scores: number[] };
type PaperTemplate = { template_id: string; name: string; description: string; region_scope: string; duration_minutes: number; target_score: number; difficulty_profile: string; sections: PaperTemplateSection[]; structure_status: string; reviewed_on: string; verification_note: string; evidence_urls: string[] };
type ExportEdition = { id: "student" | "answer" | "blueprint"; name: string; description: string };

const apiBase = "";
const questionTypeLabels: Record<string, string> = { single_choice: "单选题", multiple_choice: "多选题", fill_blank: "填空题", open_response: "解答题", composite: "综合题" };
const defaultInstructions = "答题前请填写姓名和班级；所有解答须写出必要过程。";
const questionTypeOrder = ["single_choice", "multiple_choice", "fill_blank", "open_response"];
const exportEditions: ExportEdition[] = [
  { id: "student", name: "学生卷", description: "隐藏答案与解析，可直接发给学生" },
  { id: "answer", name: "答案卷", description: "包含参考答案与完整解析" },
  { id: "blueprint", name: "双向细目表", description: "汇总章节、知识点、难度与分值" },
];

function scoreText(value: number) { return Number.isInteger(value) ? String(value) : value.toFixed(1); }
async function errorText(response: Response) { try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; } catch { return `请求失败（HTTP ${response.status}）`; } }
function summaryFromSnapshot(question: PaperQuestionSnapshot): Question { return { question_id: question.question_id, review_status: question.review_status, question_type: question.question_type, stem_plain: question.stem_plain, answer_value: question.answer_value, chapter: question.chapter, section: question.section, difficulty: question.difficulty, verification_status: question.verification_status, source_document: question.source_document }; }
function canonicalQuestionType(questionType: string) { return questionType === "composite" ? "open_response" : questionType; }

export default function PapersPage() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [papers, setPapers] = useState<PaperSummary[]>([]);
  const [templates, setTemplates] = useState<PaperTemplate[]>([]);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [title, setTitle] = useState("高中数学阶段检测");
  const [duration, setDuration] = useState(90);
  const [instructions, setInstructions] = useState(defaultInstructions);
  const [draftItems, setDraftItems] = useState<DraftItem[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [composing, setComposing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [draftWarnings, setDraftWarnings] = useState<string[]>(["保存试卷后会固定题目和图片快照。"]);
  const [autoTarget, setAutoTarget] = useState(50);
  const [autoProfile, setAutoProfile] = useState("balanced");
  const [autoChapter, setAutoChapter] = useState("");
  const [autoTypeCounts, setAutoTypeCounts] = useState<Record<string, number>>({ single_choice: 4, open_response: 2 });
  const [approvedOnly, setApprovedOnly] = useState(true);
  const [activeTemplateId, setActiveTemplateId] = useState("");
  const [isDirty, setIsDirty] = useState(false);

  const totalScore = useMemo(() => draftItems.reduce((sum, item) => sum + Number(item.score || 0), 0), [draftItems]);
  const canExport = Boolean(selected && !isDirty);
  const filteredQuestions = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return questions.filter((question) => !draftItems.some((item) => item.question.question_id === question.question_id)).filter((question) => !keyword || `${question.stem_plain} ${question.chapter} ${question.section}`.toLowerCase().includes(keyword)).slice(0, 30);
  }, [questions, draftItems, query]);
  const availableChapters = useMemo(() => Array.from(new Set(questions.map((question) => question.chapter).filter((chapter): chapter is string => Boolean(chapter)))).sort(), [questions]);
  const availableQuestionTypes = useMemo(() => Array.from(new Set(questions.map((question) => canonicalQuestionType(question.question_type)))), [questions]);
  const configuredQuestionTypes = useMemo(() => Array.from(new Set([...availableQuestionTypes, ...Object.keys(autoTypeCounts)])).sort((left, right) => (questionTypeOrder.indexOf(left) < 0 ? 99 : questionTypeOrder.indexOf(left)) - (questionTypeOrder.indexOf(right) < 0 ? 99 : questionTypeOrder.indexOf(right))), [availableQuestionTypes, autoTypeCounts]);
  const activeTemplate = useMemo(() => templates.find((template) => template.template_id === activeTemplateId) ?? null, [templates, activeTemplateId]);
  const templateSupplyIssues = useMemo(() => {
    if (!activeTemplate) return [];
    const counts = new Map<string, number>();
    questions.filter((question) => (!autoChapter || question.chapter === autoChapter) && question.review_status !== "rejected" && (!approvedOnly || question.review_status === "approved")).forEach((question) => { const type = canonicalQuestionType(question.question_type); counts.set(type, (counts.get(type) ?? 0) + 1); });
    return activeTemplate.sections.flatMap((section) => { const available = counts.get(section.question_type) ?? 0; return available < section.count ? [`${questionTypeLabels[section.question_type] ?? section.question_type}缺 ${section.count - available} 道`] : []; });
  }, [activeTemplate, questions, autoChapter, approvedOnly]);
  const draftChapterBreakdown = useMemo(() => {
    const groups = new Map<string, { question_count: number; score: number }>();
    draftItems.forEach((item) => { const label = item.question.chapter || "未分类"; const current = groups.get(label) ?? { question_count: 0, score: 0 }; current.question_count += 1; current.score += Number(item.score || 0); groups.set(label, current); });
    return Array.from(groups, ([label, values]) => ({ label, ...values }));
  }, [draftItems]);

  async function openPaper(paperId: string) {
    const response = await fetch(`${apiBase}/api/v1/exam-papers/${paperId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const paper: Paper = await response.json();
    setSelected(paper); setTitle(paper.title); setDuration(paper.duration_minutes); setInstructions(paper.instructions); setDraftWarnings(paper.warnings);
    setDraftItems(paper.items.map((item) => ({ question: summaryFromSnapshot(item.question), score: item.score })));
    setIsDirty(false);
  }

  async function loadPapers(openFirst = false) {
    const response = await fetch(`${apiBase}/api/v1/exam-papers`);
    if (!response.ok) throw new Error(await errorText(response));
    const payload = await response.json(); setPapers(payload.items);
    if (openFirst && payload.items[0]) await openPaper(payload.items[0].exam_paper_id);
  }

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase}/api/v1/questions?verification_status=passed&page_size=100`).then(async (response) => { if (!response.ok) throw new Error(await errorText(response)); const payload = await response.json(); setQuestions(payload.items); }),
      fetch(`${apiBase}/api/v1/exam-papers/templates`).then(async (response) => { if (!response.ok) throw new Error(await errorText(response)); const payload = await response.json(); setTemplates(payload.items); }),
      loadPapers(true),
    ]).catch((error: Error) => setMessage(error.message));
  }, []);

  function newPaper() { setSelected(null); setTitle("高中数学阶段检测"); setDuration(90); setInstructions(defaultInstructions); setDraftItems([]); setDraftWarnings(["保存试卷后会固定题目和图片快照。"]); setActiveTemplateId(""); setAutoTarget(50); setAutoProfile("balanced"); setAutoTypeCounts({ single_choice: 4, open_response: 2 }); setQuery(""); setIsDirty(false); setMessage("已创建空白组卷草稿，请从左侧加入题目。"); }
  function addQuestion(question: Question) { setDraftItems((current) => [...current, { question, score: ["single_choice", "multiple_choice", "fill_blank"].includes(question.question_type) ? 5 : 12 }]); setIsDirty(true); }
  function moveItem(index: number, direction: -1 | 1) { const target = index + direction; if (target < 0 || target >= draftItems.length) return; setDraftItems((current) => { const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next; }); setIsDirty(true); }
  function exportUrl(edition: ExportEdition["id"], format: "docx" | "pdf") { return selected ? `${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=${format}&edition=${edition}` : "#"; }

  async function savePaper(event?: FormEvent) {
    event?.preventDefault();
    if (!draftItems.length) { setMessage("请至少加入一道独立验证通过的题目。"); return; }
    setBusy(true);
    try {
      const response = await fetch(selected ? `${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}` : `${apiBase}/api/v1/exam-papers`, { method: selected ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim(), duration_minutes: duration, instructions: instructions.trim(), items: draftItems.map((item) => ({ question_id: item.question.question_id, score: Number(item.score) })), teacher_id: "owner_teacher" }) });
      if (!response.ok) throw new Error(await errorText(response));
      const paper: Paper = await response.json(); setSelected(paper); setDraftItems(paper.items.map((item) => ({ question: summaryFromSnapshot(item.question), score: item.score }))); setDraftWarnings(paper.warnings); setIsDirty(false); await loadPapers();
      setMessage(selected ? `试卷已保存为 v${paper.version}，原有题目快照保持不变。` : "试卷草稿已创建，题目内容和图片快照已固定。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "试卷保存失败"); } finally { setBusy(false); }
  }

  async function composePaper() {
    const quotas = configuredQuestionTypes.map((questionType) => ({ question_type: questionType, count: autoTypeCounts[questionType] ?? 0 })).filter((item) => item.count > 0);
    if (!quotas.length) { setMessage("请至少设置一种题型的数量。"); return; }
    if (activeTemplate && templateSupplyIssues.length) { setMessage(`当前题库还不能生成完整模板：${templateSupplyIssues.join("；")}。可补充题库或修改为自定义结构。`); return; }
    setComposing(true);
    try {
      const endpoint = activeTemplate ? "compose-template" : "compose";
      const body = activeTemplate ? { template_id: activeTemplate.template_id, chapters: autoChapter ? [autoChapter] : [], review_policy: approvedOnly ? "approved_only" : "verified", seed: `${title}-${Date.now()}` } : { target_score: autoTarget, difficulty_profile: autoProfile, type_quotas: quotas, chapters: autoChapter ? [autoChapter] : [], review_policy: approvedOnly ? "approved_only" : "verified", seed: `${title}-${Date.now()}` };
      const response = await fetch(`${apiBase}/api/v1/exam-papers/${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(await errorText(response));
      const proposal: PaperProposal = await response.json();
      setSelected(null); setDraftItems(proposal.items.map((item) => ({ question: item.question, score: item.score }))); setDraftWarnings(proposal.warnings.length ? proposal.warnings : [`已按${autoProfile === "foundation" ? "基础巩固" : autoProfile === "challenge" ? "能力提升" : "均衡"}方案完成自动选题，平均难度 ${proposal.average_difficulty.toFixed(1)}。`]); setIsDirty(true);
      setMessage(`自动组卷草稿已生成：${proposal.items.length} 道题，共 ${scoreText(proposal.actual_score)} 分。请审核、调整后再保存。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "自动组卷失败"); } finally { setComposing(false); }
  }

  function applyTemplate(templateId: string) {
    setActiveTemplateId(templateId);
    const template = templates.find((item) => item.template_id === templateId);
    if (!template) { setMessage("已切换为自定义试卷结构。"); return; }
    setAutoTarget(template.target_score); setDuration(template.duration_minutes); setAutoProfile(template.difficulty_profile); setAutoTypeCounts(Object.fromEntries(template.sections.map((section) => [section.question_type, section.count]))); setIsDirty(true); setMessage(`已应用“${template.name}”。系统会先检查当前题库供给，再生成可编辑草稿。`);
  }

  return <div className="page-content lesson-page paper-page">
    <section className="page-title lesson-title"><div><p className="eyebrow">智能组卷 · 版本快照</p><h1>把选题、分值和导出连成一条线。</h1><p className="subtle">只调用独立验证通过的题目；保存后，题库修订不会改变历史试卷。</p></div><button className="primary-button" type="button" onClick={newPaper}>＋ 新建试卷</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}
    <div className="lesson-builder-layout">
      <aside className="lesson-control-panel paper-control">
        <form onSubmit={savePaper}>
          <div className="control-heading"><span>01</span><div><h2>试卷设置</h2><p>设置标题、时长并从题库加入题目</p></div></div>
          <label>试卷标题<input type="text" value={title} maxLength={200} onChange={(event) => { setTitle(event.target.value); setIsDirty(true); }} /></label>
          <div className="control-grid"><label>考试时长<input type="number" min={10} max={300} value={duration} onChange={(event) => { setDuration(Number(event.target.value)); setIsDirty(true); }} /><small>分钟</small></label><label>当前总分<input type="number" value={totalScore} readOnly /><small>分</small></label></div>
          <label>考生须知<textarea value={instructions} onChange={(event) => { setInstructions(event.target.value); setIsDirty(true); }} /></label>
          <section className="paper-auto-panel">
            <div className="control-heading"><span>AI</span><div><h2>自动组卷</h2><p>按结构生成可编辑草稿，不会直接保存</p></div></div>
            <label>组卷模板<select value={activeTemplateId} onChange={(event) => applyTemplate(event.target.value)}><option value="">自定义结构</option>{templates.map((template) => <option value={template.template_id} key={template.template_id}>{template.name}</option>)}</select></label>
            {activeTemplate && <div className="paper-template-note"><b>近年参考结构 · 核验于 {activeTemplate.reviewed_on}</b><p>{activeTemplate.description}</p><small>{activeTemplate.verification_note} <a href={activeTemplate.evidence_urls[0]} target="_blank" rel="noreferrer">查看公开依据</a></small>{templateSupplyIssues.length ? <strong>当前供给缺口：{templateSupplyIssues.join("；")}</strong> : <strong className="ready">当前题库可以生成完整模板</strong>}</div>}
            <div className="control-grid"><label>目标总分<input type="number" min={5} max={300} step={0.5} value={autoTarget} onChange={(event) => { setAutoTarget(Number(event.target.value)); setActiveTemplateId(""); }} /><small>分</small></label><label>难度方案<select value={autoProfile} onChange={(event) => { setAutoProfile(event.target.value); setActiveTemplateId(""); }}><option value="foundation">基础巩固</option><option value="balanced">均衡</option><option value="challenge">能力提升</option></select></label></div>
            <div className="paper-auto-type-grid">{configuredQuestionTypes.map((questionType) => <label key={questionType}>{questionTypeLabels[questionType] ?? questionType}<input type="number" min={0} max={30} value={autoTypeCounts[questionType] ?? 0} onChange={(event) => { setAutoTypeCounts((current) => ({ ...current, [questionType]: Number(event.target.value) })); setActiveTemplateId(""); }} /><small>道</small></label>)}</div>
            <label>限定章节<select value={autoChapter} onChange={(event) => setAutoChapter(event.target.value)}><option value="">全部已验证章节</option>{availableChapters.map((chapter) => <option value={chapter} key={chapter}>{chapter}</option>)}</select></label>
            <label className="paper-auto-check"><input type="checkbox" checked={approvedOnly} onChange={(event) => setApprovedOnly(event.target.checked)} /><span>仅使用教师审核通过的题目</span></label>
            <button className="paper-auto-button" disabled={composing} type="button" onClick={composePaper}>{composing ? "正在匹配题目与配分…" : activeTemplate && templateSupplyIssues.length ? "查看题库供给缺口" : "生成自动组卷草稿"}</button>
          </section>
          <label>从已验证题库选题<input type="text" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题干、章节或知识点" /></label>
          <div className="paper-candidates">{filteredQuestions.map((question) => <button type="button" key={question.question_id} onClick={() => addQuestion(question)}><span>＋</span><div><b>{questionTypeLabels[question.question_type] ?? "解答题"} · 难度 {question.difficulty}</b><p>{question.stem_plain}</p><small>{question.chapter} · {question.review_status === "approved" ? "教师已审核" : "待教师审核"}</small></div></button>)}{!filteredQuestions.length && <p>没有更多匹配题目。</p>}</div>
          <button className="lesson-generate-button" disabled={busy || !title.trim() || !draftItems.length || Boolean(selected && !isDirty)} type="submit">{busy ? "正在保存题目快照…" : selected ? isDirty ? "保存为新版本" : "当前版本已保存" : "创建并启用导出"}</button>
        </form>
        <section className="lesson-history"><header><strong>最近试卷</strong><span>{papers.length} 份</span></header>{papers.map((paper) => <button className={selected?.exam_paper_id === paper.exam_paper_id ? "active" : ""} type="button" key={paper.exam_paper_id} onClick={() => openPaper(paper.exam_paper_id).catch((error: Error) => setMessage(error.message))}><span>{paper.question_count}</span><div><b>{paper.title}</b><small>v{paper.version} · {scoreText(paper.total_score)} 分 · {paper.duration_minutes} 分钟</small></div></button>)}{!papers.length && <p>尚未保存试卷</p>}</section>
      </aside>
      <main className="lesson-editor paper-editor">
        {!draftItems.length ? <div className="lesson-empty"><span>卷</span><h2>从已验证题库开始组卷</h2><p>左侧搜索并加入题目；每道题都可设置分值和顺序，保存后即可导出学生卷、答案卷和双向细目表。</p></div> : <>
          <header className="lesson-document-heading"><div><p>{selected ? `试卷编号 ${selected.exam_paper_id} · 当前 v${selected.version}` : "尚未保存的组卷草稿"}</p><h2>{title}</h2></div><div className="document-actions"><span>{selected ? isDirty ? "有未保存修改" : `v${selected.version} 已保存 · 可导出` : "保存后可导出"}</span>{canExport && <><a href={exportUrl("student", "docx")} title="导出当前已保存版本">学生卷 Word</a><a href={exportUrl("student", "pdf")} title="导出当前已保存版本">学生卷 PDF</a></>}<button type="button" disabled={busy || Boolean(selected && !isDirty)} onClick={() => savePaper()}>{busy ? "保存中…" : selected ? isDirty ? "保存新版本" : "当前版本已保存" : "创建并启用导出"}</button></div></header>
          <div className="lesson-context-strip"><div><span>题目数量</span><strong>{draftItems.length} 道</strong></div><div><span>总分</span><strong>{scoreText(totalScore)} 分</strong></div><div><span>考试时长</span><strong>{duration} 分钟</strong></div><div><span>待教师审核</span><strong>{draftItems.filter((item) => item.question.review_status !== "approved").length} 道</strong></div></div>
          {draftWarnings.map((warning) => <div className="lesson-warning" key={warning}>○ {warning}</div>)}
          <section className="lesson-flow-card paper-items-card"><header><div><h3>试卷题目与分值</h3><p>题目顺序和分值可调整；修改后需保存为新版本。</p></div><strong className="valid">共 {scoreText(totalScore)} 分</strong></header><div className="paper-item-list">{draftItems.map((item, index) => <article key={item.question.question_id}><span className="phase-number">{String(index + 1).padStart(2, "0")}</span><div><header><div><b>{questionTypeLabels[item.question.question_type] ?? "解答题"}</b><span>难度 {item.question.difficulty} · {item.question.review_status === "approved" ? "教师已审核" : "待教师审核"}</span></div><label>分值<input type="number" min={0.5} max={50} step={0.5} value={item.score} onChange={(event) => { setDraftItems((current) => current.map((currentItem, itemIndex) => itemIndex === index ? { ...currentItem, score: Number(event.target.value) } : currentItem)); setIsDirty(true); }} /></label></header><p><MathText text={item.question.stem_plain} /></p><small>{item.question.chapter} · {item.question.source_document}</small><footer><button type="button" disabled={index === 0} onClick={() => moveItem(index, -1)}>上移</button><button type="button" disabled={index === draftItems.length - 1} onClick={() => moveItem(index, 1)}>下移</button><button type="button" className="danger" onClick={() => { setDraftItems((current) => current.filter((_, itemIndex) => itemIndex !== index)); setIsDirty(true); }}>移除</button></footer></div></article>)}</div></section>
          <div className="lesson-editor-two-column lower"><section className="lesson-editor-card"><header><h3>章节结构</h3></header>{draftChapterBreakdown.map((item) => <p className="paper-breakdown" key={item.label}><span>{item.label}</span><strong>{item.question_count} 题 · {scoreText(item.score)} 分</strong></p>)}</section><section className="lesson-editor-card paper-export-card"><header><div><h3>导出试卷</h3><p>{canExport ? `当前导出基于已保存的 v${selected?.version}` : selected ? "当前有修改，请先保存为新版本" : "请先创建试卷，随后即可下载"}</p></div><span className={canExport ? "export-ready" : "export-pending"}>{canExport ? "可导出" : "待保存"}</span></header><div className="paper-export-list">{exportEditions.map((edition) => <div className="paper-export-row" key={edition.id}><div><strong>{edition.name}</strong><small>{edition.description}</small></div><div>{canExport ? <><a href={exportUrl(edition.id, "docx")} title={`导出${edition.name} Word`}>Word</a><a href={exportUrl(edition.id, "pdf")} title={`导出${edition.name} PDF`}>PDF</a></> : <><span>Word</span><span>PDF</span></>}</div></div>)}</div></section></div>
        </>}
      </main>
    </div>
  </div>;
}
