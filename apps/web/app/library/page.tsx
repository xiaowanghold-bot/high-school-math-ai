"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { ResizableColumns } from "../components/resizable-columns";
import "./library.css";

type LibrarySummary = {
  library_item_id: string; title: string; original_filename: string; file_kind: "pdf" | "docx" | "image";
  mime_type: string; size_bytes: number; page_count: number | null; extraction_status: "extracted" | "needs_ocr" | "failed";
  text_review_status: "pending" | "confirmed"; extracted_char_count: number; corrected_char_count: number;
  rights_basis: "original" | "licensed" | "private_teaching_only"; version: number; updated_at: string;
};
type LibraryItem = LibrarySummary & {
  source_sha256: string; extracted_text: string; corrected_text: string; rights_statement: string;
  adaptation_allowed: boolean; warnings: string[]; review_note: string;
};
type LibraryStats = { total: number; pending_review: number; confirmed: number; needs_ocr: number; by_file_kind: Record<string, number> };
type CandidateOption = { key: string; text: string };
type QuestionCandidate = {
  candidate_id: string; library_item_id: string; source_version: number; position: number;
  question_type: "single_choice" | "multiple_choice" | "fill_blank" | "open_response";
  stem_plain: string; stem_latex: string | null; options: CandidateOption[]; answer_value: string | null;
  solution_method: string; solution_steps: string[]; final_answer: string | null; difficulty: number;
  status: "draft" | "discarded" | "imported"; warnings: string[]; imported_question_id: string | null;
};

const extractionLabels = { extracted: "已提取文字", needs_ocr: "待 OCR / 转录", failed: "提取失败" };
const rightsLabels = { original: "本人原创", licensed: "已获授权", private_teaching_only: "仅限私人教学" };
const fileKindLabels = { pdf: "PDF", docx: "Word", image: "图片" };
const questionTypeLabels = { single_choice: "单选题", multiple_choice: "多选题", fill_blank: "填空题", open_response: "解答题" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}
function formatBytes(value: number) { return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }

export default function LibraryPage() {
  const [items, setItems] = useState<LibrarySummary[]>([]);
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const [draftText, setDraftText] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [rightsBasis, setRightsBasis] = useState<LibrarySummary["rights_basis"]>("private_teaching_only");
  const [rightsStatement, setRightsStatement] = useState("本人确认该资料仅上传至私人空间，用于本人日常教学与备课。");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [candidates, setCandidates] = useState<QuestionCandidate[]>([]);
  const [ocrConsent, setOcrConsent] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) => !keyword || `${item.title} ${item.original_filename}`.toLowerCase().includes(keyword));
  }, [items, query]);

  async function openItem(itemId: string) {
    const [response, candidateResponse] = await Promise.all([
      fetch(`/api/v1/library/${itemId}`),
      fetch(`/api/v1/library/${itemId}/question-candidates`),
    ]);
    if (!response.ok) throw new Error(await errorText(response));
    const item: LibraryItem = await response.json();
    setSelected(item);
    setDraftText(item.corrected_text || item.extracted_text);
    setReviewNote(item.review_note);
    setOcrConsent(false);
    setCandidates(candidateResponse.ok ? (await candidateResponse.json()).items : []);
  }

  async function refresh(preferredId?: string) {
    const [listResponse, statsResponse] = await Promise.all([fetch("/api/v1/library"), fetch("/api/v1/library/stats")]);
    if (!listResponse.ok) throw new Error(await errorText(listResponse));
    if (!statsResponse.ok) throw new Error(await errorText(statsResponse));
    const list = await listResponse.json();
    setItems(list.items);
    setStats(await statsResponse.json());
    const nextId = preferredId || selected?.library_item_id || list.items[0]?.library_item_id;
    if (nextId) await openItem(nextId);
  }

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("create") === "upload") setUploadOpen(true);
    refresh().catch((error: Error) => setMessage(error.message));
    function receiveCreate(event: Event) {
      if ((event as CustomEvent).detail === "library") setUploadOpen(true);
    }
    window.addEventListener("math-ai:create", receiveCreate);
    return () => window.removeEventListener("math-ai:create", receiveCreate);
  }, []);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    if (next && !title.trim()) setTitle(next.name.replace(/\.[^.]+$/, ""));
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) { setMessage("请选择要上传的 PDF、DOCX 或图片。"); return; }
    if (!acknowledged) { setMessage("请先确认资料来源和使用权声明。"); return; }
    setBusy(true); setMessage(null);
    try {
      const body = new FormData();
      body.append("file", file); body.append("title", title); body.append("rights_basis", rightsBasis);
      body.append("rights_statement", rightsStatement); body.append("rights_acknowledged", String(acknowledged));
      const response = await fetch("/api/v1/library", { method: "POST", body });
      if (!response.ok) throw new Error(await errorText(response));
      const item: LibraryItem = await response.json();
      await refresh(item.library_item_id);
      setFile(null); setTitle(""); setAcknowledged(false); setUploadOpen(false);
      setMessage(item.extraction_status === "extracted" ? "资料已安全上传并提取文字，请进行人工校对。" : "资料已安全上传；当前需要 OCR 或人工转录。" );
    } catch (error) { setMessage(error instanceof Error ? error.message : "资料上传失败"); }
    finally { setBusy(false); }
  }

  async function saveReview(confirm: boolean) {
    if (!selected) return;
    if (confirm && !draftText.trim()) { setMessage("确认校对前必须填写可用文本。"); return; }
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/review`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrected_text: draftText, note: reviewNote, confirm }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const item: LibraryItem = await response.json();
      setSelected(item); setDraftText(item.corrected_text); await refresh(item.library_item_id);
      setMessage(confirm ? "文本校对已确认；资料仍保持私人状态。" : "校对草稿已保存为新版本。" );
    } catch (error) { setMessage(error instanceof Error ? error.message : "校对保存失败"); }
    finally { setBusy(false); }
  }

  async function runOcr() {
    if (!selected || !ocrConsent) { setMessage("请先勾选本次外部 OCR 授权。"); return; }
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/ocr`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ external_processing_consent: true }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      await refresh(result.item.library_item_id);
      setMessage("OCR 已生成待校对文本；请逐行核对公式、题号和选项后再确认。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "OCR 识别失败"); }
    finally { setBusy(false); }
  }

  async function proposeCandidates() {
    if (!selected) return;
    setCandidateBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/question-candidates`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); setCandidates(result.items);
      setMessage(`已生成 ${result.items.length} 道拆题候选，请逐题编辑后再导入。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "拆题失败"); }
    finally { setCandidateBusy(false); }
  }

  function editCandidate(candidateId: string, patch: Partial<QuestionCandidate>) {
    setCandidates((current) => current.map((item) => item.candidate_id === candidateId ? { ...item, ...patch } : item));
  }

  async function saveCandidate(candidate: QuestionCandidate) {
    if (!selected) return;
    setCandidateBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/question-candidates/${candidate.candidate_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(candidate),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const saved = await response.json(); editCandidate(candidate.candidate_id, saved);
      setMessage(`候选 ${candidate.position} 已保存。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "候选保存失败"); }
    finally { setCandidateBusy(false); }
  }

  async function discardCandidate(candidate: QuestionCandidate) {
    if (!selected) return;
    setCandidateBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/question-candidates/${candidate.candidate_id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorText(response));
      editCandidate(candidate.candidate_id, await response.json()); setMessage(`候选 ${candidate.position} 已移出本次导入。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "候选处理失败"); }
    finally { setCandidateBusy(false); }
  }

  async function importCandidate(candidate: QuestionCandidate) {
    if (!selected) return;
    setCandidateBusy(true); setMessage(null);
    try {
      const saveResponse = await fetch(`/api/v1/library/${selected.library_item_id}/question-candidates/${candidate.candidate_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(candidate),
      });
      if (!saveResponse.ok) throw new Error(await errorText(saveResponse));
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/question-candidates/${candidate.candidate_id}/import`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); editCandidate(candidate.candidate_id, result.candidate);
      setMessage(`已导入私人题库：${result.question_id}。仍需在题库审核台完成数学核验。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "导入题库失败"); }
    finally { setCandidateBusy(false); }
  }

  return <div className="page-content library-workspace">
    <section className="page-title library-title"><div><p className="eyebrow">个人资料库 · 默认私人</p><h1>先安全收进来，再逐份校对。</h1><p className="subtle">原文件、提取文本与教师修订分开保存；未经明确授权不会进入公共题库或模型训练。</p></div><button className="primary-button" type="button" onClick={() => setUploadOpen((current) => !current)}>{uploadOpen ? "收起上传" : "＋ 上传资料"}</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}

    <section className="library-stats"><div><span>私人资料</span><strong>{stats?.total ?? "—"}</strong><small>不会公开检索</small></div><div><span>待人工校对</span><strong>{stats?.pending_review ?? "—"}</strong><small>保留原始提取文本</small></div><div className="confirmed"><span>已确认文本</span><strong>{stats?.confirmed ?? "—"}</strong><small>可进入后续结构化</small></div><div className={stats?.needs_ocr ? "attention" : ""}><span>待 OCR / 转录</span><strong>{stats?.needs_ocr ?? "—"}</strong><small>图片或扫描件</small></div></section>

    {uploadOpen && <form className="library-upload-panel" onSubmit={upload}>
      <div className="library-upload-heading"><span>入</span><div><h2>上传私人资料</h2><p>支持 PDF、DOCX、PNG、JPEG、WebP，单文件不超过 50 MB</p></div></div>
      <label className="library-file-drop"><input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" onChange={selectFile} /><span>{file ? file.name : "点击选择文件"}</span><small>{file ? formatBytes(file.size) : "系统会校验真实格式，不只检查扩展名"}</small></label>
      <label><span>资料标题</span><input value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} placeholder="例如：函数性质专题讲义" /></label>
      <label><span>使用权依据</span><select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as LibrarySummary["rights_basis"])}><option value="private_teaching_only">仅限本人私人教学使用</option><option value="original">本人原创</option><option value="licensed">已获得明确授权</option></select></label>
      <label className="library-rights-statement"><span>来源与权利说明</span><textarea value={rightsStatement} onChange={(event) => setRightsStatement(event.target.value)} /></label>
      <label className="library-ack"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我确认上述声明真实；该资料默认保持私人，不自动用于公共展示或模型训练。</span></label>
      <button className="library-upload-submit" disabled={busy || !file || !acknowledged || rightsStatement.trim().length < 6} type="submit">{busy ? "正在校验并提取…" : "上传并提取文字"}</button>
    </form>}

    <ResizableColumns className="library-layout" storageKey="private-library" initialLeftPercent={29} leftMin={240} rightMin={440} collapse="compact" label="调整资料列表与资料校对区宽度">
      <aside className="library-list-panel">
        <header><div><strong>我的资料</strong><span>{filtered.length} 份</span></div><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或文件名" /></header>
        <div className="library-item-list">{filtered.map((item) => <button className={selected?.library_item_id === item.library_item_id ? "active" : ""} type="button" key={item.library_item_id} onClick={() => openItem(item.library_item_id).catch((error: Error) => setMessage(error.message))}><span className={`library-kind ${item.file_kind}`}>{fileKindLabels[item.file_kind]}</span><div><b>{item.title}</b><p>{item.original_filename}</p><small>{extractionLabels[item.extraction_status]} · {item.text_review_status === "confirmed" ? "教师已确认" : "待校对"} · v{item.version}</small></div></button>)}{!filtered.length && <div className="empty-state"><strong>暂无私人资料</strong><p>从上方上传第一份 PDF、Word 或图片。</p></div>}</div>
      </aside>

      <main className="library-review-panel">
        {!selected ? <div className="library-empty"><span>资</span><h2>上传资料后从这里开始校对</h2><p>系统保留原文件和自动提取结果；教师修订会生成新版本，不会覆盖原文。</p></div> : <>
          <header className="library-document-heading"><div><p>{fileKindLabels[selected.file_kind]} · {formatBytes(selected.size_bytes)}{selected.page_count ? ` · ${selected.page_count} 页` : ""}</p><h2>{selected.title}</h2><small>{selected.original_filename}</small></div><div><span className={`library-review-status ${selected.text_review_status}`}>{selected.text_review_status === "confirmed" ? "教师已确认" : "待人工校对"}</span><a href={`/api/v1/library/${selected.library_item_id}/file`}>下载原文件</a></div></header>
          <section className="library-privacy-strip"><div><span>可见范围</span><strong>仅本人</strong></div><div><span>模型训练</span><strong>禁止</strong></div><div><span>改编权限</span><strong>{selected.adaptation_allowed ? "已声明允许" : "未授权"}</strong></div><div><span>权利依据</span><strong>{rightsLabels[selected.rights_basis]}</strong></div></section>
          {selected.warnings.map((warning) => <p className="library-warning" key={warning}>{warning}</p>)}
          {selected.extraction_status === "needs_ocr" && <section className="library-ocr-panel"><div><strong>扫描件或图片需要 OCR</strong><p>仅在本次勾选后，原文件才会发送给当前配置的大模型服务。识别结果仍是私人待校对文本。</p></div><label><input type="checkbox" checked={ocrConsent} onChange={(event) => setOcrConsent(event.target.checked)} /><span>我同意本次发送该文件用于 OCR</span></label><button type="button" disabled={busy || !ocrConsent} onClick={runOcr}>{busy ? "识别中…" : "开始 OCR"}</button></section>}
          {selected.file_kind === "image" && <div className="library-image-preview"><img src={`/api/v1/library/${selected.library_item_id}/file`} alt={selected.title} /></div>}
          <div className="library-text-compare">
            <section><header><div><strong>自动提取原文</strong><small>{selected.extracted_char_count} 字符 · 不可覆盖</small></div><span>{extractionLabels[selected.extraction_status]}</span></header><pre>{selected.extracted_text || "尚无自动提取文字。请在右侧根据原文件进行人工转录。"}</pre></section>
            <section className="library-correction"><header><div><strong>教师校对文本</strong><small>{draftText.length} 字符 · 保存即生成新版本</small></div><span>v{selected.version}</span></header><textarea value={draftText} onChange={(event) => setDraftText(event.target.value)} placeholder="在此修正识别错误、补充公式或人工转录图片内容……" /></section>
          </div>
          <label className="library-review-note"><span>本次校对说明</span><input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="例如：核对第 1—5 页，修正函数公式与上下标" /></label>
          <footer className="library-review-actions"><div><span>确认后仍只进入私人资料库</span><small>后续拆题和进入题库需要再次审核</small></div><button type="button" disabled={busy} onClick={() => saveReview(false)}>保存校对草稿</button><button className="confirm" type="button" disabled={busy || !draftText.trim()} onClick={() => saveReview(true)}>{busy ? "保存中…" : "确认文本可用"}</button></footer>
          <section className="library-candidate-workspace">
            <header><div><p>下一步 · 结构化题目</p><h3>拆题候选</h3><small>先本地按题号拆分，再由教师逐题修订；导入后仍是私人待审核草稿。</small></div><button type="button" disabled={candidateBusy || selected.text_review_status !== "confirmed"} onClick={proposeCandidates}>{candidateBusy ? "处理中…" : candidates.length ? "重新读取候选" : "生成拆题候选"}</button></header>
            {selected.text_review_status !== "confirmed" ? <div className="library-candidate-empty"><strong>请先确认校对文本</strong><span>未确认的 OCR 或提取结果不会进入拆题流程。</span></div> : !candidates.length ? <div className="library-candidate-empty"><strong>尚未生成候选</strong><span>点击右上方按钮，系统只处理当前已确认的文本版本。</span></div> : <div className="library-candidate-list">{candidates.map((candidate) => <details key={candidate.candidate_id} open={candidate.position === 1 && candidate.status === "draft"} className={`library-candidate ${candidate.status}`}>
              <summary><span>{String(candidate.position).padStart(2, "0")}</span><div><strong>{candidate.stem_plain.slice(0, 58) || "未填写题干"}</strong><small>{questionTypeLabels[candidate.question_type]} · 难度 {candidate.difficulty} · {candidate.status === "imported" ? "已进入私人题库" : candidate.status === "discarded" ? "已丢弃" : "待审核"}</small></div><b>{candidate.status === "imported" ? "已导入" : candidate.status === "discarded" ? "已丢弃" : "编辑"}</b></summary>
              <div className="library-candidate-editor">
                {candidate.warnings.map((warning) => <p className="library-candidate-warning" key={warning}>{warning}</p>)}
                <div className="library-candidate-meta"><label><span>题型</span><select disabled={candidate.status !== "draft"} value={candidate.question_type} onChange={(event) => editCandidate(candidate.candidate_id, { question_type: event.target.value as QuestionCandidate["question_type"] })}>{Object.entries(questionTypeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label><span>难度</span><select disabled={candidate.status !== "draft"} value={candidate.difficulty} onChange={(event) => editCandidate(candidate.candidate_id, { difficulty: Number(event.target.value) })}>{[1,2,3,4,5].map((value) => <option key={value} value={value}>{value}</option>)}</select></label></div>
                <label><span>题干</span><textarea disabled={candidate.status !== "draft"} value={candidate.stem_plain} onChange={(event) => editCandidate(candidate.candidate_id, { stem_plain: event.target.value })} /></label>
                <label><span>选项（每行“字母. 内容”）</span><textarea className="compact" disabled={candidate.status !== "draft"} value={candidate.options.map((option) => `${option.key}. ${option.text}`).join("\n")} onChange={(event) => editCandidate(candidate.candidate_id, { options: event.target.value.split("\n").map((line) => line.match(/^\s*([A-Za-z0-9]+)[.、．]\s*(.*)$/)).filter((match): match is RegExpMatchArray => Boolean(match)).map((match) => ({ key: match[1].toUpperCase(), text: match[2] })) })} placeholder="A. 选项一" /></label>
                <div className="library-candidate-answer"><label><span>答案</span><input disabled={candidate.status !== "draft"} value={candidate.answer_value ?? ""} onChange={(event) => editCandidate(candidate.candidate_id, { answer_value: event.target.value })} /></label><label><span>最终答案</span><input disabled={candidate.status !== "draft"} value={candidate.final_answer ?? ""} onChange={(event) => editCandidate(candidate.candidate_id, { final_answer: event.target.value })} /></label></div>
                <label><span>解析步骤（每行一步）</span><textarea disabled={candidate.status !== "draft"} value={candidate.solution_steps.join("\n")} onChange={(event) => editCandidate(candidate.candidate_id, { solution_steps: event.target.value.split("\n").filter(Boolean) })} /></label>
                <footer>{candidate.status === "imported" ? <><span>题号：{candidate.imported_question_id}</span><a href="/search">前往题库审核台</a></> : candidate.status === "discarded" ? <span>此候选不会进入题库。</span> : <><button type="button" disabled={candidateBusy || !candidate.stem_plain.trim()} onClick={() => saveCandidate(candidate)}>保存修改</button><button className="discard" type="button" disabled={candidateBusy} onClick={() => discardCandidate(candidate)}>丢弃</button><button className="import" type="button" disabled={candidateBusy || !candidate.stem_plain.trim()} onClick={() => importCandidate(candidate)}>导入私人题库</button></>}</footer>
              </div>
            </details>)}</div>}
          </section>
        </>}
      </main>
    </ResizableColumns>
  </div>;
}
