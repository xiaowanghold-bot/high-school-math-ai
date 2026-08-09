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

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const questionTypeLabels: Record<string, string> = { single_choice: "单选题", multiple_choice: "多选题", fill_blank: "填空题", open_response: "解答题", composite: "综合题" };
const defaultInstructions = "答题前请填写姓名和班级；所有解答须写出必要过程。";

function scoreText(value: number) { return Number.isInteger(value) ? String(value) : value.toFixed(1); }
async function errorText(response: Response) { try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; } catch { return `请求失败（HTTP ${response.status}）`; } }
function summaryFromSnapshot(question: PaperQuestionSnapshot): Question { return { question_id: question.question_id, review_status: question.review_status, question_type: question.question_type, stem_plain: question.stem_plain, answer_value: question.answer_value, chapter: question.chapter, section: question.section, difficulty: question.difficulty, verification_status: question.verification_status, source_document: question.source_document }; }

export default function PapersPage() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [papers, setPapers] = useState<PaperSummary[]>([]);
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
  const [autoTypeCounts, setAutoTypeCounts] = useState<Record<string, number>>({ single_choice: 4, composite: 2 });
  const [approvedOnly, setApprovedOnly] = useState(true);

  const totalScore = useMemo(() => draftItems.reduce((sum, item) => sum + Number(item.score || 0), 0), [draftItems]);
  const filteredQuestions = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return questions.filter((question) => !draftItems.some((item) => item.question.question_id === question.question_id)).filter((question) => !keyword || `${question.stem_plain} ${question.chapter} ${question.section}`.toLowerCase().includes(keyword)).slice(0, 30);
  }, [questions, draftItems, query]);
  const availableChapters = useMemo(() => Array.from(new Set(questions.map((question) => question.chapter).filter((chapter): chapter is string => Boolean(chapter)))).sort(), [questions]);
  const availableQuestionTypes = useMemo(() => Array.from(new Set(questions.map((question) => question.question_type))).sort((left, right) => ["single_choice", "multiple_choice", "fill_blank", "open_response", "composite"].indexOf(left) - ["single_choice", "multiple_choice", "fill_blank", "open_response", "composite"].indexOf(right)), [questions]);
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
      loadPapers(true),
    ]).catch((error: Error) => setMessage(error.message));
  }, []);

  function newPaper() { setSelected(null); setTitle("高中数学阶段检测"); setDuration(90); setInstructions(defaultInstructions); setDraftItems([]); setDraftWarnings(["保存试卷后会固定题目和图片快照。"]); setQuery(""); setMessage("已创建空白组卷草稿，请从左侧加入题目。"); }
  function addQuestion(question: Question) { setDraftItems((current) => [...current, { question, score: ["single_choice", "multiple_choice", "fill_blank"].includes(question.question_type) ? 5 : 12 }]); }
  function moveItem(index: number, direction: -1 | 1) { const target = index + direction; if (target < 0 || target >= draftItems.length) return; setDraftItems((current) => { const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next; }); }

  async function savePaper(event?: FormEvent) {
    event?.preventDefault();
    if (!draftItems.length) { setMessage("请至少加入一道独立验证通过的题目。"); return; }
    setBusy(true);
    try {
      const response = await fetch(selected ? `${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}` : `${apiBase}/api/v1/exam-papers`, { method: selected ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim(), duration_minutes: duration, instructions: instructions.trim(), items: draftItems.map((item) => ({ question_id: item.question.question_id, score: Number(item.score) })), teacher_id: "owner_teacher" }) });
      if (!response.ok) throw new Error(await errorText(response));
      const paper: Paper = await response.json(); setSelected(paper); setDraftItems(paper.items.map((item) => ({ question: summaryFromSnapshot(item.question), score: item.score }))); setDraftWarnings(paper.warnings); await loadPapers();
      setMessage(selected ? `试卷已保存为 v${paper.version}，原有题目快照保持不变。` : "试卷草稿已创建，题目内容和图片快照已固定。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "试卷保存失败"); } finally { setBusy(false); }
  }

  async function composePaper() {
    const quotas = availableQuestionTypes.map((questionType) => ({ question_type: questionType, count: autoTypeCounts[questionType] ?? 0 })).filter((item) => item.count > 0);
    if (!quotas.length) { setMessage("请至少设置一种题型的数量。"); return; }
    setComposing(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/exam-papers/compose`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_score: autoTarget, difficulty_profile: autoProfile, type_quotas: quotas, chapters: autoChapter ? [autoChapter] : [], review_policy: approvedOnly ? "approved_only" : "verified", seed: `${title}-${Date.now()}` }) });
      if (!response.ok) throw new Error(await errorText(response));
      const proposal: PaperProposal = await response.json();
      setSelected(null); setDraftItems(proposal.items.map((item) => ({ question: item.question, score: item.score }))); setDraftWarnings(proposal.warnings.length ? proposal.warnings : [`已按${autoProfile === "foundation" ? "基础巩固" : autoProfile === "challenge" ? "能力提升" : "均衡"}方案完成自动选题，平均难度 ${proposal.average_difficulty.toFixed(1)}。`]);
      setMessage(`自动组卷草稿已生成：${proposal.items.length} 道题，共 ${scoreText(proposal.actual_score)} 分。请审核、调整后再保存。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "自动组卷失败"); } finally { setComposing(false); }
  }

  return <div className="page-content lesson-page paper-page">
    <section className="page-title lesson-title"><div><p className="eyebrow">智能组卷 · 版本快照</p><h1>把选题、分值和导出连成一条线。</h1><p className="subtle">只调用独立验证通过的题目；保存后，题库修订不会改变历史试卷。</p></div><button className="primary-button" type="button" onClick={newPaper}>＋ 新建试卷</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}
    <div className="lesson-builder-layout">
      <aside className="lesson-control-panel paper-control">
        <form onSubmit={savePaper}>
          <div className="control-heading"><span>01</span><div><h2>试卷设置</h2><p>设置标题、时长并从题库加入题目</p></div></div>
          <label>试卷标题<input type="text" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
          <div className="control-grid"><label>考试时长<input type="number" min={10} max={300} value={duration} onChange={(event) => setDuration(Number(event.target.value))} /><small>分钟</small></label><label>当前总分<input type="number" value={totalScore} readOnly /><small>分</small></label></div>
          <label>考生须知<textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} /></label>
          <section className="paper-auto-panel">
            <div className="control-heading"><span>AI</span><div><h2>自动组卷</h2><p>按结构生成可编辑草稿，不会直接保存</p></div></div>
            <div className="control-grid"><label>目标总分<input type="number" min={5} max={300} step={0.5} value={autoTarget} onChange={(event) => setAutoTarget(Number(event.target.value))} /><small>分</small></label><label>难度方案<select value={autoProfile} onChange={(event) => setAutoProfile(event.target.value)}><option value="foundation">基础巩固</option><option value="balanced">均衡</option><option value="challenge">能力提升</option></select></label></div>
            <div className="paper-auto-type-grid">{availableQuestionTypes.map((questionType) => <label key={questionType}>{questionTypeLabels[questionType] ?? questionType}<input type="number" min={0} max={30} value={autoTypeCounts[questionType] ?? 0} onChange={(event) => setAutoTypeCounts((current) => ({ ...current, [questionType]: Number(event.target.value) }))} /><small>道</small></label>)}</div>
            <label>限定章节<select value={autoChapter} onChange={(event) => setAutoChapter(event.target.value)}><option value="">全部已验证章节</option>{availableChapters.map((chapter) => <option value={chapter} key={chapter}>{chapter}</option>)}</select></label>
            <label className="paper-auto-check"><input type="checkbox" checked={approvedOnly} onChange={(event) => setApprovedOnly(event.target.checked)} /><span>仅使用教师审核通过的题目</span></label>
            <button className="paper-auto-button" disabled={composing} type="button" onClick={composePaper}>{composing ? "正在匹配题目与配分…" : "生成自动组卷草稿"}</button>
          </section>
          <label>从已验证题库选题<input type="text" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题干、章节或知识点" /></label>
          <div className="paper-candidates">{filteredQuestions.map((question) => <button type="button" key={question.question_id} onClick={() => addQuestion(question)}><span>＋</span><div><b>{questionTypeLabels[question.question_type] ?? "解答题"} · 难度 {question.difficulty}</b><p>{question.stem_plain}</p><small>{question.chapter} · {question.review_status === "approved" ? "教师已审核" : "待教师审核"}</small></div></button>)}{!filteredQuestions.length && <p>没有更多匹配题目。</p>}</div>
          <button className="lesson-generate-button" disabled={busy || !title.trim() || !draftItems.length} type="submit">{busy ? "正在保存题目快照…" : selected ? "保存为新版本" : "创建试卷草稿"}</button>
        </form>
        <section className="lesson-history"><header><strong>最近试卷</strong><span>{papers.length} 份</span></header>{papers.map((paper) => <button className={selected?.exam_paper_id === paper.exam_paper_id ? "active" : ""} type="button" key={paper.exam_paper_id} onClick={() => openPaper(paper.exam_paper_id).catch((error: Error) => setMessage(error.message))}><span>{paper.question_count}</span><div><b>{paper.title}</b><small>v{paper.version} · {scoreText(paper.total_score)} 分 · {paper.duration_minutes} 分钟</small></div></button>)}{!papers.length && <p>尚未保存试卷</p>}</section>
      </aside>
      <main className="lesson-editor paper-editor">
        {!draftItems.length ? <div className="lesson-empty"><span>卷</span><h2>从已验证题库开始组卷</h2><p>左侧搜索并加入题目；每道题都可设置分值和顺序，保存后即可导出学生卷、答案卷和双向细目表。</p></div> : <>
          <header className="lesson-document-heading"><div><p>{selected ? `试卷编号 ${selected.exam_paper_id} · 当前 v${selected.version}` : "尚未保存的组卷草稿"}</p><h2>{title}</h2></div><div className="document-actions"><span>{draftItems.length} 题 · {scoreText(totalScore)} 分</span>{selected && <><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=docx&edition=student`}>学生卷 Word</a><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=docx&edition=answer`}>答案卷 Word</a><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=docx&edition=blueprint`}>细目表 Word</a></>}<button type="button" disabled={busy} onClick={() => savePaper()}>{busy ? "保存中…" : selected ? "保存新版本" : "创建试卷"}</button></div></header>
          <div className="lesson-context-strip"><div><span>题目数量</span><strong>{draftItems.length} 道</strong></div><div><span>总分</span><strong>{scoreText(totalScore)} 分</strong></div><div><span>考试时长</span><strong>{duration} 分钟</strong></div><div><span>待教师审核</span><strong>{draftItems.filter((item) => item.question.review_status !== "approved").length} 道</strong></div></div>
          {draftWarnings.map((warning) => <div className="lesson-warning" key={warning}>○ {warning}</div>)}
          <section className="lesson-flow-card paper-items-card"><header><div><h3>试卷题目与分值</h3><p>题目顺序和分值可调整；修改后需保存为新版本。</p></div><strong className="valid">共 {scoreText(totalScore)} 分</strong></header><div className="paper-item-list">{draftItems.map((item, index) => <article key={item.question.question_id}><span className="phase-number">{String(index + 1).padStart(2, "0")}</span><div><header><div><b>{questionTypeLabels[item.question.question_type] ?? "解答题"}</b><span>难度 {item.question.difficulty} · {item.question.review_status === "approved" ? "教师已审核" : "待教师审核"}</span></div><label>分值<input type="number" min={0.5} max={50} step={0.5} value={item.score} onChange={(event) => setDraftItems((current) => current.map((currentItem, itemIndex) => itemIndex === index ? { ...currentItem, score: Number(event.target.value) } : currentItem))} /></label></header><p><MathText text={item.question.stem_plain} /></p><small>{item.question.chapter} · {item.question.source_document}</small><footer><button type="button" disabled={index === 0} onClick={() => moveItem(index, -1)}>上移</button><button type="button" disabled={index === draftItems.length - 1} onClick={() => moveItem(index, 1)}>下移</button><button type="button" className="danger" onClick={() => setDraftItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}>移除</button></footer></div></article>)}</div></section>
          <div className="lesson-editor-two-column lower"><section className="lesson-editor-card"><header><h3>章节结构</h3></header>{draftChapterBreakdown.map((item) => <p className="paper-breakdown" key={item.label}><span>{item.label}</span><strong>{item.question_count} 题 · {scoreText(item.score)} 分</strong></p>)}</section><section className="lesson-editor-card"><header><h3>导出版本</h3></header><p className="paper-breakdown"><span>学生卷</span><strong>隐藏答案与解析</strong></p><p className="paper-breakdown"><span>答案卷</span><strong>包含答案与步骤</strong></p><p className="paper-breakdown"><span>双向细目表</span><strong>章节、知识点、难度、分值</strong></p>{selected && <div className="paper-pdf-links"><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=pdf&edition=student`}>学生卷 PDF</a><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=pdf&edition=answer`}>答案卷 PDF</a><a href={`${apiBase}/api/v1/exam-papers/${selected.exam_paper_id}/export?format=pdf&edition=blueprint`}>细目表 PDF</a></div>}</section></div>
        </>}
      </main>
    </div>
  </div>;
}
