"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
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

type QuestionImage = {
  image_id: string;
  question_id: string;
  placement: "stem" | "solution";
  original_filename: string;
  mime_type: string;
  width: number;
  height: number;
  alt_text: string;
  caption: string;
  sort_order: number;
  content_url: string;
  updated_at: string;
};

type RawOption = { key: string; plain_text?: string; latex?: string };

type QuestionDetail = Question & {
  raw: {
    stem?: { plain_text?: string; latex?: string };
    options?: RawOption[];
    solutions?: { method?: string; steps_latex?: string[]; final_answer?: string; review_status?: string }[];
    verification?: { status?: string; details?: string[]; computed_answer?: string | null; computed_canonical_value?: string };
    source?: { source_reference?: string | null };
    curation?: { disposition?: string; adaptation_candidate?: { change?: string; result?: string } | null };
  };
  reviews: { reviewer_id: string; decision: string; note: string; reviewed_at: string }[];
  images: QuestionImage[];
  revision_count: number;
};

type EditDraft = {
  stem_plain: string;
  stem_latex: string;
  options: { key: string; text: string }[];
  answer_value: string;
  solution_method: string;
  solution_steps: string;
  final_answer: string;
  note: string;
};

type Stats = {
  total: number;
  by_review_status: Record<string, number>;
  by_verification_status: Record<string, number>;
  by_chapter: Record<string, number>;
  publishable: number;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const imageAccept = "image/png,image/jpeg,image/webp";

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
  { label: "立体几何", chapter: "第八章 立体几何初步" },
  { label: "圆锥曲线", chapter: "第三章 圆锥曲线的方程" },
  { label: "概率", chapter: "第七章 随机变量及其分布" },
];

function draftFromDetail(detail: QuestionDetail): EditDraft {
  const solution = detail.raw.solutions?.[0];
  return {
    stem_plain: detail.raw.stem?.plain_text || detail.stem_plain,
    stem_latex: detail.raw.stem?.latex || "",
    options: (detail.raw.options || []).map((item) => ({
      key: item.key,
      text: item.latex || item.plain_text || "",
    })),
    answer_value: detail.answer_value || "",
    solution_method: solution?.method || "教师修订",
    solution_steps: (solution?.steps_latex || []).join("\n"),
    final_answer: solution?.final_answer || detail.answer_value || "",
    note: "教师在审核台修订题干、答案或解析",
  };
}

async function errorText(response: Response) {
  try {
    const payload = await response.json();
    return payload.detail || `请求失败（HTTP ${response.status}）`;
  } catch {
    return `请求失败（HTTP ${response.status}）`;
  }
}

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
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [detailMode, setDetailMode] = useState<"preview" | "edit">("preview");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const searchUrl = useMemo(() => {
    const params = new URLSearchParams({ page_size: "50" });
    if (query) params.set("query", query);
    if (chapter) params.set("chapter", chapter);
    if (verification) params.set("verification_status", verification);
    return `${apiBase}/api/v1/questions?${params.toString()}`;
  }, [query, chapter, verification]);

  const loadStats = () => fetch(`${apiBase}/api/v1/question-bank/stats`).then((response) => response.json()).then(setStats);

  async function refreshDetail(questionId = selectedId) {
    if (!questionId) return;
    const response = await fetch(`${apiBase}/api/v1/questions/${questionId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const updated: QuestionDetail = await response.json();
    setDetail(updated);
    setEditDraft(draftFromDetail(updated));
    setItems((current) => current.map((item) => item.question_id === questionId ? { ...item, ...updated } : item));
  }

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
        setSelectedId((current) => current && payload.items.some((item: Question) => item.question_id === current) ? current : payload.items[0]?.question_id ?? null);
      })
      .catch(() => active && setMessage("题库接口暂时不可用，请确认后端已启动。"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [searchUrl]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setEditDraft(null);
      return;
    }
    setDetailMode("preview");
    refreshDetail(selectedId).catch(() => setMessage("无法读取题目详情。"));
  }, [selectedId]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(queryInput.trim());
  }

  async function saveRevision() {
    if (!selectedId || !editDraft) return;
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...editDraft,
          stem_latex: editDraft.stem_latex || null,
          answer_value: editDraft.answer_value || null,
          solution_steps: editDraft.solution_steps.split("\n").map((item) => item.trim()).filter(Boolean),
          final_answer: editDraft.final_answer || null,
          editor_id: "owner_teacher",
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setDetail(result.question);
      setEditDraft(draftFromDetail(result.question));
      setItems((current) => current.map((item) => item.question_id === selectedId ? { ...item, ...result.question } : item));
      setDetailMode("preview");
      await loadStats();
      setMessage(result.verification_reset ? "修订已保存为新版本；数学内容发生变化，旧验证已自动失效。" : "修订已保存为新版本；题干、选项和答案未变化，验证状态保持不变。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "题目修订保存失败");
    } finally {
      setWorking(false);
    }
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
      setMessage(await errorText(response));
      return;
    }
    await Promise.all([refreshDetail(), loadStats()]);
    setMessage(decision === "approved" ? "审核已保存；发布门禁仍会独立检查。" : "审核结论已保存。" );
  }

  async function checkPublish() {
    if (!selectedId) return;
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/publish`, { method: "POST" });
    const decision = await response.json();
    setMessage(decision.allowed ? "全部门禁通过，题目已发布。" : `暂不可发布：${decision.blockers.map((item: string) => blockerLabels[item] ?? item).join("、")}`);
  }

  async function showImportStatus() {
    const batches = await fetch(`${apiBase}/api/v1/question-bank/import-batches`).then((response) => response.json());
    const latest = batches[0];
    setMessage(latest ? `最近导入：${latest.batch_id}，共 ${latest.declared_count} 题；当前状态为私有、不可直接发布。` : "还没有题目导入记录。");
  }

  async function uploadImage(event: ChangeEvent<HTMLInputElement>, placement: "stem" | "solution") {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !selectedId) return;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("placement", placement);
    formData.append("alt_text", placement === "stem" ? "题干配图，请补充图形说明" : "解析辅助图，请补充图形说明");
    formData.append("caption", file.name.replace(/\.[^.]+$/, ""));
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/images`, { method: "POST", body: formData });
      if (!response.ok) throw new Error(await errorText(response));
      await Promise.all([refreshDetail(), loadStats()]);
      setMessage(placement === "stem" ? "题干配图已加入固定图片槽；旧数学验证已自动失效。" : "解析配图已加入固定图片槽。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "图片上传失败");
    } finally {
      setWorking(false);
    }
  }

  async function replaceImage(event: ChangeEvent<HTMLInputElement>, image: QuestionImage) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !selectedId) return;
    const formData = new FormData();
    formData.append("file", file);
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/images/${image.image_id}/file`, { method: "PUT", body: formData });
      if (!response.ok) throw new Error(await errorText(response));
      await Promise.all([refreshDetail(), loadStats()]);
      setMessage("图片文件已替换，位置、说明和排序保持不变。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "图片替换失败");
    } finally {
      setWorking(false);
    }
  }

  async function updateImage(image: QuestionImage, patch: Partial<Pick<QuestionImage, "alt_text" | "caption" | "placement">>) {
    if (!selectedId) return;
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/images/${image.image_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!response.ok) {
      setMessage(await errorText(response));
      return;
    }
    await Promise.all([refreshDetail(), loadStats()]);
    setMessage("图片说明已保存。" );
  }

  async function deleteImage(image: QuestionImage) {
    if (!selectedId || !window.confirm(`确定删除“${image.caption || image.original_filename}”吗？`)) return;
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/images/${image.image_id}`, { method: "DELETE" });
    if (!response.ok) {
      setMessage(await errorText(response));
      return;
    }
    await Promise.all([refreshDetail(), loadStats()]);
    setMessage("图片已删除。" );
  }

  async function moveImage(image: QuestionImage, direction: -1 | 1) {
    if (!detail || !selectedId) return;
    const samePlacement = detail.images.filter((item) => item.placement === image.placement);
    const currentIndex = samePlacement.findIndex((item) => item.image_id === image.image_id);
    const target = samePlacement[currentIndex + direction];
    if (!target) return;
    const ordered = [...detail.images];
    const from = ordered.findIndex((item) => item.image_id === image.image_id);
    const to = ordered.findIndex((item) => item.image_id === target.image_id);
    [ordered[from], ordered[to]] = [ordered[to], ordered[from]];
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/images/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_ids: ordered.map((item) => item.image_id) }),
    });
    if (!response.ok) {
      setMessage(await errorText(response));
      return;
    }
    await refreshDetail();
  }

  const pending = stats?.by_review_status.pending ?? 0;
  const formulaIssues = stats?.by_verification_status.needs_formula_review ?? 0;
  const sourceIssues = stats?.by_verification_status.source_inconsistency_detected ?? 0;
  const verifiedCount = stats?.by_verification_status.passed ?? 0;

  function renderImages(placement: "stem" | "solution", editable = false) {
    if (!detail) return null;
    const images = detail.images.filter((item) => item.placement === placement);
    if (!editable && !images.length) return null;
    return (
      <section className={`question-media-section ${editable ? "media-editor" : ""}`}>
        <header>
          <div><strong>{placement === "stem" ? "题干配图" : "解析配图"}</strong><span>全题 {detail.images.length} / 8</span></div>
          {editable && <label className="media-upload-button">＋ 插入图片<input type="file" accept={imageAccept} disabled={working} onChange={(event) => uploadImage(event, placement)} /></label>}
        </header>
        {editable && !images.length && <div className="media-empty"><span>图</span><p>图片会固定在内容区，不进入题目列表。支持 PNG、JPEG、WebP。</p></div>}
        <div className="question-media-grid">
          {images.map((image, index) => (
            <article className="question-media-card" key={image.image_id}>
              <div className="media-frame"><img src={`${apiBase}${image.content_url}?v=${encodeURIComponent(image.updated_at)}`} alt={image.alt_text || image.caption || "题目配图"} /></div>
              {editable ? <div className="media-fields">
                <label><span>图片说明</span><input value={image.caption} onChange={(event) => setDetail((current) => current ? { ...current, images: current.images.map((item) => item.image_id === image.image_id ? { ...item, caption: event.target.value } : item) } : current)} onBlur={(event) => updateImage(image, { caption: event.target.value })} /></label>
                <label><span>无障碍描述</span><textarea value={image.alt_text} onChange={(event) => setDetail((current) => current ? { ...current, images: current.images.map((item) => item.image_id === image.image_id ? { ...item, alt_text: event.target.value } : item) } : current)} onBlur={(event) => updateImage(image, { alt_text: event.target.value })} /></label>
                <div className="media-card-actions">
                  <button type="button" disabled={index === 0} onClick={() => moveImage(image, -1)}>← 前移</button>
                  <button type="button" disabled={index === images.length - 1} onClick={() => moveImage(image, 1)}>后移 →</button>
                  <button type="button" onClick={() => updateImage(image, { placement: placement === "stem" ? "solution" : "stem" })}>{placement === "stem" ? "移到解析" : "移到题干"}</button>
                  <label>替换<input type="file" accept={imageAccept} onChange={(event) => replaceImage(event, image)} /></label>
                  <button type="button" className="danger" onClick={() => deleteImage(image)}>删除</button>
                </div>
              </div> : <div className="media-caption"><strong>{image.caption || `图 ${index + 1}`}</strong><span>{image.width} × {image.height}</span></div>}
            </article>
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="page-content question-workspace">
      <section className="page-title question-title">
        <div><p className="eyebrow">智能搜题 · 教师审核台</p><h1>先把每一道题变得可信。</h1><p className="subtle">教师可直接修订题干、答案和解析；题干图与解析图在固定图片槽内受控展示。</p></div>
        <button className="primary-button" type="button" onClick={showImportStatus}>导入记录</button>
      </section>

      {message && <div className="notice info-notice" role="status" aria-live="polite"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}

      <section className="quality-strip" aria-label="题库质量概览">
        <div><span>试点题目</span><strong>{stats?.total ?? "—"}</strong><small>本地私有题库</small></div>
        <div><span>待教师审核</span><strong>{pending}</strong><small>逐题确认</small></div>
        <div className="metric-passed"><span>独立验证通过</span><strong>{verifiedCount}</strong><small>含计算证据</small></div>
        <div><span>待公式校正</span><strong>{formulaIssues}</strong><small>禁止直接展示</small></div>
        <div className={sourceIssues ? "metric-alert" : ""}><span>来源矛盾</span><strong>{sourceIssues}</strong><small>需重点复核</small></div>
        <div><span>当前可发布</span><strong>{stats?.publishable ?? 0}</strong><small>全部门禁通过</small></div>
      </section>

      <form className="question-filters" onSubmit={submitSearch}>
        <label className="filter-field search-filter"><span className="filter-label">关键词</span><span className="search-field"><span aria-hidden="true">⌕</span><input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder="例如：集合、椭圆、概率" /></span></label>
        <label className="filter-field"><span className="filter-label">教材章节</span><select value={chapter} onChange={(event) => setChapter(event.target.value)}><option value="">全部章节</option>{Object.keys(stats?.by_chapter ?? {}).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="filter-field"><span className="filter-label">质量状态</span><select value={verification} onChange={(event) => setVerification(event.target.value)}><option value="">全部质量状态</option><option value="passed">验证通过</option><option value="needs_formula_review">待公式校正</option><option value="needs_math_review">待数学验算</option><option value="source_inconsistency_detected">来源存在矛盾</option></select></label>
        <button className="primary-button" type="submit">检索</button>
      </form>

      <nav className="module-shortcuts" aria-label="按数学模块快速筛选"><span>快速进入</span>{moduleShortcuts.map((item) => <button className={chapter === item.chapter ? "active" : ""} key={item.label} type="button" onClick={() => setChapter(item.chapter)}>{item.label}{item.chapter && stats?.by_chapter[item.chapter] !== undefined ? <small>{stats.by_chapter[item.chapter]}</small> : null}</button>)}</nav>

      <div className="question-layout">
        <section className="question-results" aria-label="题目列表">
          <div className="results-heading" aria-live="polite"><strong>{loading ? "正在检索…" : `${total} 道题`}</strong><span>图片固定在详情区</span></div>
          <div className="result-list">
            {items.map((item, index) => <button className={selectedId === item.question_id ? "question-row selected" : "question-row"} type="button" key={item.question_id} onClick={() => setSelectedId(item.question_id)}><span className="question-index">{String(index + 1).padStart(2, "0")}</span><span className="question-main"><span className="question-tags"><em>{item.question_type === "single_choice" ? "单选题" : "解答题"}</em><i className={`quality-tag ${item.verification_status}`}>{verificationLabels[item.verification_status] ?? item.verification_status}</i></span><b>{item.stem_plain}</b><small>{item.chapter} · 难度 {item.difficulty}/5</small></span><span className="review-mark">{reviewLabels[item.review_status] ?? item.review_status}</span></button>)}
            {!loading && items.length === 0 && <div className="empty-state"><strong>没有匹配题目</strong><p>换一个关键词或清空筛选条件。</p></div>}
          </div>
        </section>

        <aside className="question-detail" aria-label="题目审核详情">
          {!detail && <div className="empty-state"><strong>请选择一道题</strong><p>右侧将显示来源、答案与审核动作。</p></div>}
          {detail && editDraft && <>
            <header className="detail-heading"><div><p>{detail.volume}{detail.section ? ` · ${detail.section}` : ""}</p><h2>{detail.chapter}</h2></div><div className="detail-heading-tools"><span>难度 {detail.difficulty}</span><span>修订 {detail.revision_count}</span></div></header>
            <div className="detail-mode-tabs"><button className={detailMode === "preview" ? "active" : ""} type="button" onClick={() => setDetailMode("preview")}>内容预览</button><button className={detailMode === "edit" ? "active" : ""} type="button" onClick={() => setDetailMode("edit")}>编辑与配图</button></div>

            {detailMode === "preview" ? <>
              {detail.verification_status === "passed" ? <div className="verification-passed"><strong>独立验证通过</strong><p>答案已由规则模块独立计算；教师修订数学内容后，本结论会自动失效。</p></div> : <div className="formula-warning"><strong>{verificationLabels[detail.verification_status]}</strong><p>{detail.raw.verification?.details?.[0] || "该题需要重新校正或独立验算后才能审核发布。"}</p></div>}
              <div className="stem-card"><p><MathText text={detail.raw.stem?.latex || detail.stem_plain} /></p></div>
              {renderImages("stem")}
              {!!detail.raw.options?.length && <ol className="option-list">{detail.raw.options.map((option) => <li key={option.key}><b>{option.key}</b><span><MathText text={option.latex || option.plain_text || "选项内容需重建"} /></span></li>)}</ol>}
              <div className="answer-line"><span>{detail.verification_status === "passed" ? "独立验证答案" : "当前答案"}</span><strong>{detail.raw.verification?.computed_answer || detail.answer_value || "待独立求解"}</strong></div>
              {!!detail.raw.solutions?.[0]?.steps_latex?.length && <div className="solution-card"><header><span>自有解析草稿</span><strong>{detail.raw.solutions[0].method}</strong></header><ol>{detail.raw.solutions[0].steps_latex?.map((step, index) => <li key={index}><MathText text={step} /></li>)}</ol><small>需由教师确认后才可作为正式解析</small></div>}
              {renderImages("solution")}
            </> : <div className="question-editor-form">
              <div className="editor-safety-note"><strong>修改即生成新版本</strong><span>题干、选项、答案或题干图变化会自动退回数学验算；来源原文不会被覆盖。</span></div>
              <label><span>题干正文</span><textarea className="large" value={editDraft.stem_plain} onChange={(event) => setEditDraft({ ...editDraft, stem_plain: event.target.value })} /></label>
              <label><span>LaTeX 题干（可选）</span><textarea value={editDraft.stem_latex} onChange={(event) => setEditDraft({ ...editDraft, stem_latex: event.target.value })} placeholder="可直接输入含 $...$ 的数学公式；留空则显示题干正文" /></label>
              {renderImages("stem", true)}
              <section className="option-editor"><header><strong>选项</strong><button type="button" onClick={() => setEditDraft({ ...editDraft, options: [...editDraft.options, { key: String.fromCharCode(65 + editDraft.options.length), text: "" }] })}>＋ 添加选项</button></header>{editDraft.options.map((option, index) => <div key={`${option.key}-${index}`}><input className="option-key-input" aria-label={`选项 ${index + 1} 编号`} value={option.key} onChange={(event) => setEditDraft({ ...editDraft, options: editDraft.options.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item) })} /><textarea value={option.text} onChange={(event) => setEditDraft({ ...editDraft, options: editDraft.options.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item) })} /><button type="button" aria-label={`删除选项 ${option.key}`} onClick={() => setEditDraft({ ...editDraft, options: editDraft.options.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>)}</section>
              <div className="question-editor-two"><label><span>参考答案</span><input value={editDraft.answer_value} onChange={(event) => setEditDraft({ ...editDraft, answer_value: event.target.value })} /></label><label><span>解析方法</span><input value={editDraft.solution_method} onChange={(event) => setEditDraft({ ...editDraft, solution_method: event.target.value })} /></label></div>
              <label><span>解析步骤（每行一步）</span><textarea className="large" value={editDraft.solution_steps} onChange={(event) => setEditDraft({ ...editDraft, solution_steps: event.target.value })} /></label>
              <label><span>最终答案</span><input value={editDraft.final_answer} onChange={(event) => setEditDraft({ ...editDraft, final_answer: event.target.value })} /></label>
              {renderImages("solution", true)}
              <label><span>修订说明</span><input value={editDraft.note} onChange={(event) => setEditDraft({ ...editDraft, note: event.target.value })} /></label>
              <div className="question-editor-actions"><button type="button" onClick={() => { setEditDraft(draftFromDetail(detail)); setDetailMode("preview"); }}>放弃未保存修改</button><button className="primary" type="button" disabled={working || !editDraft.stem_plain.trim()} onClick={saveRevision}>{working ? "保存中…" : "保存为新修订"}</button></div>
            </div>}

            <dl className="source-meta"><div><dt>来源文件</dt><dd>{detail.source_document}</dd></div><div><dt>定位页</dt><dd>{detail.source_page_start ?? "—"}{detail.source_page_end && detail.source_page_end !== detail.source_page_start ? `–${detail.source_page_end}` : ""}</dd></div><div><dt>审核状态</dt><dd>{reviewLabels[detail.review_status] ?? detail.review_status}</dd></div></dl>
            <div className="gate-list"><h3>发布门禁</h3>{detail.publication_blockers.map((item) => <span key={item}>○ {blockerLabels[item] ?? item}</span>)}</div>
            <div className="review-actions"><button type="button" className="approve" disabled={detail.verification_status !== "passed"} onClick={() => review("approved")}>教师通过</button><button type="button" onClick={() => review("changes_requested")}>需要修改</button><button type="button" className="reject" onClick={() => review("rejected")}>拒绝入库</button></div>
            <button className="publish-check" type="button" onClick={checkPublish}>检查是否可以发布</button>
          </>}
        </aside>
      </div>
    </div>
  );
}
