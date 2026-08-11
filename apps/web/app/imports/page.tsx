"use client";

import { ChangeEvent, FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { ResizableColumns } from "../components/resizable-columns";
import "./imports.css";

type ImportStatus = "registered" | "analyzing" | "ready_for_segmentation" | "failed";
type CandidateStatus = "draft" | "confirmed" | "discarded";
type DraftStatus = "draft" | "confirmed" | "imported";
type FormulaStatus = "pending" | "needs_review" | "confirmed";
type QuestionType = "single_choice" | "multiple_choice" | "fill_blank" | "open_response" | "unknown";
type ImportPage = { page_id: string; page_number: number; width_points: number; height_points: number; extracted_text: string; character_count: number; question_marker_count: number; embedded_image_count: number; has_text_layer: boolean; warnings: string[] };
type ImportFile = { file_id: string; batch_id: string; original_filename: string; size_bytes: number; sha256: string; page_count: number; status: ImportStatus; analyzed_page_count: number; text_page_count: number; scan_page_count: number; extracted_character_count: number; question_marker_count: number; image_page_count: number; embedded_image_count: number; warnings: string[]; error_message: string; created_at: string; updated_at: string };
type ImportFileDetail = ImportFile & { pages: ImportPage[] };
type ImportBatch = { batch_id: string; title: string; rights_basis: string; rights_statement: string; owner_id: string; file_count: number; registered_count: number; ready_count: number; failed_count: number; page_count: number; question_marker_count: number; created_at: string; updated_at: string; files: ImportFile[] };
type ImportWorkspace = { stats: { batches: number; files: number; pages: number; ready_files: number; scan_pages: number; question_markers: number }; batches: ImportBatch[] };
type BoundaryCandidate = { candidate_id: string; file_id: string; position: number; start_page: number; end_page: number; stem_text: string; question_type: QuestionType; subquestion_count: number; status: CandidateStatus; note: string; editor_id: string; source_analysis_updated_at: string; created_at: string; updated_at: string };
type BoundaryList = { file_id: string; source_analysis_updated_at: string; total: number; draft_count: number; confirmed_count: number; discarded_count: number; items: BoundaryCandidate[] };
type StructuredOption = { key: string; text: string };
type MediaReference = { page_number: number; placement: "stem" | "solution"; note: string };
type MediaCrop = { crop_id: string; draft_id: string; file_id: string; page_number: number; placement: "stem" | "solution"; x_ratio: number; y_ratio: number; width_ratio: number; height_ratio: number; note: string; editor_id: string; pixel_width: number; pixel_height: number; imported_image_id: string | null; created_at: string };
type CropRect = { x_ratio: number; y_ratio: number; width_ratio: number; height_ratio: number };
type StructuredDraft = { draft_id: string; file_id: string; boundary_candidate_id: string; position: number; start_page: number; end_page: number; source_text: string; question_type: QuestionType; stem_plain: string; stem_latex: string | null; options: StructuredOption[]; answer_value: string | null; solution_method: string; solution_steps: string[]; final_answer: string | null; difficulty: number; formula_status: FormulaStatus; media_references: MediaReference[]; media_crops: MediaCrop[]; status: DraftStatus; warnings: string[]; note: string; editor_id: string; imported_question_id: string | null; created_at: string; updated_at: string };
type StructuredDraftList = { file_id: string; total: number; draft_count: number; confirmed_count: number; imported_count: number; items: StructuredDraft[] };

const statusLabels: Record<ImportStatus, string> = { registered: "待分析", analyzing: "分析中", ready_for_segmentation: "可进入拆题", failed: "分析失败" };
const candidateStatusLabels: Record<CandidateStatus, string> = { draft: "待校对", confirmed: "已确认", discarded: "已弃用" };
const draftStatusLabels: Record<DraftStatus, string> = { draft: "待校对", confirmed: "可入题库", imported: "已入题库" };
const formulaStatusLabels: Record<FormulaStatus, string> = { pending: "待检查", needs_review: "需校正", confirmed: "已核对" };
const questionTypeLabels: Record<QuestionType, string> = { single_choice: "单选题", multiple_choice: "多选题", fill_blank: "填空题", open_response: "解答题", unknown: "待判断" };
const rightsLabels: Record<string, string> = { question_content_user_declared_usable: "题目内容经本人声明可使用", licensed: "已获得明确授权", original: "本人原创", private_research_only: "仅限内部研究" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}
function formatBytes(value: number) { return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function emptyBoundaries(fileId = ""): BoundaryList { return { file_id: fileId, source_analysis_updated_at: "", total: 0, draft_count: 0, confirmed_count: 0, discarded_count: 0, items: [] }; }
function emptyDrafts(fileId = ""): StructuredDraftList { return { file_id: fileId, total: 0, draft_count: 0, confirmed_count: 0, imported_count: 0, items: [] }; }

export default function ImportsPage() {
  const [workspace, setWorkspace] = useState<ImportWorkspace | null>(null);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [selected, setSelected] = useState<ImportFileDetail | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [viewMode, setViewMode] = useState<"pages" | "boundaries" | "structured">("pages");
  const [boundaries, setBoundaries] = useState<BoundaryList>(emptyBoundaries());
  const [candidate, setCandidate] = useState<BoundaryCandidate | null>(null);
  const [drafts, setDrafts] = useState<StructuredDraftList>(emptyDrafts());
  const [draft, setDraft] = useState<StructuredDraft | null>(null);
  const [cropMode, setCropMode] = useState(false);
  const [cropRect, setCropRect] = useState<CropRect | null>(null);
  const [cropPlacement, setCropPlacement] = useState<"stem" | "solution">("stem");
  const [cropNote, setCropNote] = useState("题目配图");
  const cropStart = useRef<{ x: number; y: number } | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("三文件结构化试点");
  const [rightsBasis, setRightsBasis] = useState("question_content_user_declared_usable");
  const [rightsStatement, setRightsStatement] = useState("本人确认仅使用题目事实，不复用原 PDF 版式、封面、水印、讲义文字和原解析表述。");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedBatch = useMemo(() => workspace?.batches.find((batch) => batch.batch_id === selected?.batch_id) ?? null, [selected, workspace]);

  async function loadBoundaries(fileId: string, preferredCandidateId?: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}/boundary-candidates`);
    if (!response.ok) throw new Error(await errorText(response));
    const payload: BoundaryList = await response.json();
    setBoundaries(payload);
    const next = payload.items.find((item) => item.candidate_id === preferredCandidateId) ?? payload.items[0] ?? null;
    setCandidate(next);
    if (next) setPreviewPage(next.start_page);
  }

  async function loadDrafts(fileId: string, preferredDraftId?: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}/structured-drafts`);
    if (!response.ok) throw new Error(await errorText(response));
    const payload: StructuredDraftList = await response.json();
    setDrafts(payload);
    const next = payload.items.find((item) => item.draft_id === preferredDraftId) ?? payload.items[0] ?? null;
    setDraft(next);
    if (next) setPreviewPage(next.start_page);
  }

  async function openFile(fileId: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const detail: ImportFileDetail = await response.json();
    setSelectedFileId(fileId);
    setSelected(detail);
    setPreviewPage(1);
    await Promise.all([loadBoundaries(fileId), loadDrafts(fileId)]);
  }

  async function refresh(preferredFileId?: string) {
    const response = await fetch("/api/v1/imports");
    if (!response.ok) throw new Error(await errorText(response));
    const payload: ImportWorkspace = await response.json();
    setWorkspace(payload);
    const target = preferredFileId || selectedFileId || payload.batches[0]?.files[0]?.file_id;
    if (target) await openFile(target);
    else { setSelected(null); setSelectedFileId(""); setBoundaries(emptyBoundaries()); setDrafts(emptyDrafts()); }
  }

  useEffect(() => { refresh().catch((error: Error) => setMessage(error.message)); }, []);

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files ?? []);
    setFiles(chosen);
    if (chosen.length && title === "三文件结构化试点") setTitle(`${chosen[0].name.replace(/\.pdf$/i, "")}等 ${chosen.length} 份资料`);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!files.length) { setMessage("请至少选择一份 PDF。"); return; }
    if (!acknowledged) { setMessage("请先确认本批资料的来源与使用权声明。"); return; }
    setBusy(true); setMessage("");
    try {
      const body = new FormData();
      files.forEach((file) => body.append("files", file));
      body.append("title", title); body.append("rights_basis", rightsBasis); body.append("rights_statement", rightsStatement); body.append("rights_acknowledged", "true"); body.append("owner_id", "owner_teacher");
      const response = await fetch("/api/v1/imports/batches", { method: "POST", body });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      const firstId = result.batch.files[0]?.file_id;
      await refresh(firstId); setFiles([]); setAcknowledged(false); setUploadOpen(false); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "批次登记失败"); }
    finally { setBusy(false); }
  }

  async function analyzeFile() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/analyze`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); await refresh(selected.file_id); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "文件分析失败"); }
    finally { setBusy(false); }
  }

  async function analyzeBatch() {
    if (!selectedBatch) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/batches/${selectedBatch.batch_id}/analyze`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); await refresh(selected?.file_id); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "批次分析失败"); }
    finally { setBusy(false); }
  }

  async function proposeBoundaries() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/boundary-candidates/propose`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setBoundaries(result.candidates);
      const first = result.candidates.items[0] ?? null;
      setCandidate(first); if (first) setPreviewPage(first.start_page);
      setViewMode("boundaries"); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "生成边界候选失败"); }
    finally { setBusy(false); }
  }

  async function addManualBoundary() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const pageText = selected.pages.find((page) => page.page_number === previewPage)?.extracted_text.trim();
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/boundary-candidates`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_page: previewPage, end_page: previewPage, stem_text: pageText || "请在此输入题目正文", question_type: "unknown", subquestion_count: 0, note: "教师手工补充", editor_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const created: BoundaryCandidate = await response.json();
      await loadBoundaries(selected.file_id, created.candidate_id); setViewMode("boundaries"); setMessage("已新增手工边界，请继续校对题目正文。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "新增边界失败"); }
    finally { setBusy(false); }
  }

  async function saveCandidate(status?: CandidateStatus) {
    if (!selected || !candidate) return;
    setBusy(true); setMessage("");
    const nextStatus = status ?? candidate.status;
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/boundary-candidates/${candidate.candidate_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...candidate, status: nextStatus, editor_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const updated: BoundaryCandidate = await response.json();
      await loadBoundaries(selected.file_id, updated.candidate_id);
      setMessage(nextStatus === "confirmed" ? "该题边界已确认，仍保留在加工区，尚未进入正式题库。" : nextStatus === "discarded" ? "该候选已弃用，可随时重新编辑并恢复。" : "校对内容已保存。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存校对失败"); }
    finally { setBusy(false); }
  }

  async function proposeStructuredDrafts() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/propose`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setDrafts(result.drafts);
      const first: StructuredDraft | null = result.drafts.items[0] ?? null;
      setDraft(first); if (first) setPreviewPage(first.start_page);
      setViewMode("structured"); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "生成结构化草稿失败"); }
    finally { setBusy(false); }
  }

  async function saveDraft(status?: DraftStatus) {
    if (!selected || !draft) return;
    const nextStatus = status ?? draft.status;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_type: draft.question_type, stem_plain: draft.stem_plain, stem_latex: draft.stem_latex,
          options: draft.options, answer_value: draft.answer_value, solution_method: draft.solution_method,
          solution_steps: draft.solution_steps, final_answer: draft.final_answer, difficulty: draft.difficulty,
          formula_status: draft.formula_status, media_references: draft.media_references,
          note: draft.note, status: nextStatus, editor_id: "owner_teacher",
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const updated: StructuredDraft = await response.json();
      await loadDrafts(selected.file_id, updated.draft_id);
      setMessage(nextStatus === "confirmed" ? "结构与公式已确认，现在可以送入题库继续数学核验和教师审核。" : "结构化草稿已保存。 ");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存结构化草稿失败"); }
    finally { setBusy(false); }
  }

  async function importDraft() {
    if (!selected || !draft) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}/import`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      await loadDrafts(selected.file_id, result.draft.draft_id);
      setMessage(`已进入私人题库审核队列：${result.question_id}。仍需教材映射、独立验算和教师审核。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "提交题库审核失败"); }
    finally { setBusy(false); }
  }

  function cropPoint(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  }

  function beginCrop(event: ReactPointerEvent<HTMLDivElement>) {
    if (!cropMode || !draft || draft.status === "imported") return;
    const point = cropPoint(event);
    cropStart.current = point;
    setCropRect({ x_ratio: point.x, y_ratio: point.y, width_ratio: 0, height_ratio: 0 });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveCrop(event: ReactPointerEvent<HTMLDivElement>) {
    if (!cropMode || !cropStart.current) return;
    const point = cropPoint(event);
    const start = cropStart.current;
    setCropRect({
      x_ratio: Math.min(start.x, point.x), y_ratio: Math.min(start.y, point.y),
      width_ratio: Math.abs(point.x - start.x), height_ratio: Math.abs(point.y - start.y),
    });
  }

  function endCrop(event: ReactPointerEvent<HTMLDivElement>) {
    const start = cropStart.current;
    if (!start) return;
    const point = cropPoint(event);
    const finalRect = {
      x_ratio: Math.min(start.x, point.x), y_ratio: Math.min(start.y, point.y),
      width_ratio: Math.abs(point.x - start.x), height_ratio: Math.abs(point.y - start.y),
    };
    event.currentTarget.releasePointerCapture(event.pointerId);
    cropStart.current = null;
    if (finalRect.width_ratio < 0.01 || finalRect.height_ratio < 0.01) {
      setCropRect(null); setMessage("框选区域太小，请重新拖动选择图片范围。");
    } else setCropRect(finalRect);
  }

  async function saveCrop() {
    if (!selected || !draft || !cropRect) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}/media-crops`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_number: previewPage, placement: cropPlacement, ...cropRect, note: cropNote, editor_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const created: MediaCrop = await response.json();
      await loadDrafts(selected.file_id, draft.draft_id);
      setPreviewPage(created.page_number);
      setCropRect(null); setCropMode(false);
      setMessage(`已保存第 ${created.page_number} 页裁剪图（${created.pixel_width} × ${created.pixel_height} px）。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存裁剪图失败"); }
    finally { setBusy(false); }
  }

  async function deleteCrop(cropId: string) {
    if (!selected || !draft) return;
    const preservedPage = previewPage;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}/media-crops/${cropId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorText(response));
      await loadDrafts(selected.file_id, draft.draft_id);
      setPreviewPage(preservedPage);
      setMessage("裁剪图已从 PDF 加工区移除。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除裁剪图失败"); }
    finally { setBusy(false); }
  }

  function selectCandidate(item: BoundaryCandidate) { setCandidate(item); setPreviewPage(item.start_page); }
  function selectDraft(item: StructuredDraft) { setDraft(item); setPreviewPage(item.start_page); setCropMode(false); setCropRect(null); }

  return <div className="page-content import-workspace">
    <section className="page-title import-title"><div><p className="eyebrow">题库生产 · 来源可追溯</p><h1>批量 PDF 加工中心</h1><p className="subtle">先登记来源和权利，再逐页分析与校对题目边界；任何内容都不会自动进入正式题库。</p></div><button className="primary-button" type="button" onClick={() => setUploadOpen((value) => !value)}>{uploadOpen ? "收起登记" : "＋ 新建批次"}</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage("")}>关闭</button></div>}
    <section className="import-stats"><div><span>导入批次</span><strong>{workspace?.stats.batches ?? "—"}</strong><small>保留权利声明</small></div><div><span>PDF 文件</span><strong>{workspace?.stats.files ?? "—"}</strong><small>{workspace?.stats.pages ?? 0} 页</small></div><div className="ready"><span>已完成页分析</span><strong>{workspace?.stats.ready_files ?? "—"}</strong><small>可进入拆题准备</small></div><div className={workspace?.stats.scan_pages ? "attention" : ""}><span>待 OCR 页面</span><strong>{workspace?.stats.scan_pages ?? "—"}</strong><small>文字层不足</small></div><div><span>题号标记</span><strong>{workspace?.stats.question_markers ?? "—"}</strong><small>仅作边界候选</small></div></section>

    {uploadOpen && <form className="import-upload-panel" onSubmit={upload}>
      <header><span>01</span><div><h2>登记一批 PDF</h2><p>每批最多 12 份、单份不超过 100 MB；登记后由教师决定何时分析。</p></div></header>
      <label className="import-file-picker"><input type="file" accept="application/pdf,.pdf" multiple onChange={chooseFiles} /><strong>{files.length ? `已选择 ${files.length} 份 PDF` : "选择多份 PDF"}</strong><small>{files.length ? files.map((file) => file.name).join("、") : "建议首批选择函数与导数、概率统计、立体几何三种版式"}</small></label>
      <div className="import-upload-grid"><label><span>批次名称</span><input value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} /></label><label><span>使用权依据</span><select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value)}>{Object.entries(rightsLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
      <label><span>来源与使用边界</span><textarea value={rightsStatement} onChange={(event) => setRightsStatement(event.target.value)} /></label>
      <footer><label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我确认声明真实；登记、分析和拆题均不等于允许公开发布。</span></label><button type="submit" disabled={busy || !files.length || !acknowledged || rightsStatement.trim().length < 6}>{busy ? "正在登记…" : "登记批次"}</button></footer>
    </form>}

    <ResizableColumns className="import-layout" storageKey="pdf-import-queue" initialLeftPercent={32} leftMin={260} rightMin={480} collapse="compact" label="调整 PDF 处理队列与加工区宽度">
      <aside className="import-queue"><header><strong>处理队列</strong><span>{workspace?.stats.files ?? 0} 份</span></header>
        {!workspace?.batches.length && <div className="import-empty"><strong>暂无导入批次</strong><p>从上方选择 PDF，登记后再逐份分析。</p></div>}
        {workspace?.batches.map((batch) => <section key={batch.batch_id} className="import-batch-group"><header><div><strong>{batch.title}</strong><small>{batch.file_count} 份 · {batch.page_count} 页 · {rightsLabels[batch.rights_basis]}</small></div><em>{batch.ready_count}/{batch.file_count}</em></header>{batch.files.map((file) => <button type="button" className={selectedFileId === file.file_id ? "active" : ""} key={file.file_id} onClick={() => openFile(file.file_id).catch((error: Error) => setMessage(error.message))}><span className={`import-file-status ${file.status}`}>PDF</span><div><b>{file.original_filename}</b><small>{file.page_count} 页 · {formatBytes(file.size_bytes)}</small></div><em className={file.status}>{statusLabels[file.status]}</em></button>)}</section>)}
      </aside>

      <main className="import-inspector">{!selected ? <div className="import-inspector-empty"><span>PDF</span><h2>选择文件检查页面质量</h2><p>这里会显示原文件、文字层覆盖、题号标记和需要 OCR 的页面。</p></div> : <>
        <header className="import-inspector-heading"><div><p>{selectedBatch?.title}</p><h2>{selected.original_filename}</h2><small>SHA-256：{selected.sha256.slice(0, 18)}… · {formatBytes(selected.size_bytes)}</small></div><div><a href={`/api/v1/imports/files/${selected.file_id}/source`} target="_blank" rel="noreferrer">打开原 PDF</a><button type="button" disabled={busy} onClick={analyzeFile}>{busy ? "处理中…" : selected.status === "ready_for_segmentation" ? "重新分析" : "分析此文件"}</button><button className="primary" type="button" disabled={busy || !selectedBatch || selectedBatch.ready_count === selectedBatch.file_count} onClick={analyzeBatch}>分析本批全部</button></div></header>
        <section className="import-file-metrics"><div><span>状态</span><strong className={selected.status}>{statusLabels[selected.status]}</strong></div><div><span>总页数</span><strong>{selected.page_count}</strong></div><div><span>有文字层</span><strong>{selected.text_page_count}</strong></div><div><span>待 OCR</span><strong>{selected.scan_page_count}</strong></div><div><span>题号 / 图片</span><strong>{selected.question_marker_count} / {selected.embedded_image_count}</strong></div></section>
        {selected.error_message && <div className="notice warning">{selected.error_message}</div>}{selected.warnings.map((warning) => <p className="import-warning" key={warning}>{warning}</p>)}
        <nav className="import-stage-tabs"><button type="button" className={viewMode === "pages" ? "active" : ""} onClick={() => setViewMode("pages")}><span>01</span><div><strong>逐页分析</strong><small>文字层、题号与图片</small></div></button><button type="button" className={viewMode === "boundaries" ? "active" : ""} disabled={selected.status !== "ready_for_segmentation"} onClick={() => setViewMode("boundaries")}><span>02</span><div><strong>题目边界</strong><small>{boundaries.total ? `${boundaries.confirmed_count}/${boundaries.total} 已确认` : "生成候选后人工校对"}</small></div></button><button type="button" className={viewMode === "structured" ? "active" : ""} disabled={!boundaries.confirmed_count} onClick={() => setViewMode("structured")}><span>03</span><div><strong>内容结构化</strong><small>{drafts.total ? `${drafts.confirmed_count + drafts.imported_count}/${drafts.total} 已校对` : "题干、选项、公式与配图"}</small></div></button></nav>
        <ResizableColumns className={`import-preview-layout ${viewMode === "boundaries" ? "boundary-mode" : viewMode === "structured" ? "structured-mode" : ""}`} storageKey={`pdf-preview-${viewMode}`} initialLeftPercent={viewMode === "pages" ? 63 : 45} leftMin={viewMode === "pages" ? 340 : 320} rightMin={viewMode === "pages" ? 240 : 360} collapse="wide" label="调整 PDF 原文预览与分析校对区宽度">
          <section className="import-pdf-preview"><header><strong>{cropMode ? "拖动框选图片范围" : "原 PDF 预览"}</strong><div className="preview-page-controls"><button type="button" disabled={previewPage <= 1 || cropMode} onClick={() => setPreviewPage((page) => Math.max(1, page - 1))}>‹</button><span>第 {previewPage} / {selected.page_count} 页</span><button type="button" disabled={previewPage >= selected.page_count || cropMode} onClick={() => setPreviewPage((page) => Math.min(selected.page_count, page + 1))}>›</button></div></header><div className="import-preview-scroll"><div className={`import-preview-page ${cropMode ? "crop-active" : ""}`} onPointerDown={beginCrop} onPointerMove={moveCrop} onPointerUp={endCrop} onPointerCancel={() => { cropStart.current = null; setCropRect(null); }}><img draggable={false} key={`${selected.file_id}-${previewPage}`} alt={`${selected.original_filename} 第 ${previewPage} 页`} src={`/api/v1/imports/files/${selected.file_id}/pages/${previewPage}/preview?width=1200`} />{viewMode === "structured" && draft?.media_crops.filter((crop) => crop.page_number === previewPage).map((crop) => <span className="saved-crop-box" key={crop.crop_id} style={{ left: `${crop.x_ratio * 100}%`, top: `${crop.y_ratio * 100}%`, width: `${crop.width_ratio * 100}%`, height: `${crop.height_ratio * 100}%` }} title={crop.note || "已保存裁剪图"} />)}{cropRect && <span className="active-crop-box" style={{ left: `${cropRect.x_ratio * 100}%`, top: `${cropRect.y_ratio * 100}%`, width: `${cropRect.width_ratio * 100}%`, height: `${cropRect.height_ratio * 100}%` }} />}</div></div></section>
          {viewMode === "pages" ? <section className="import-page-analysis"><header><div><strong>逐页分析</strong><small>{selected.pages.length ? `${selected.pages.length} 页已分析` : "分析后生成页面指标"}</small></div><span>题号只是候选</span></header>
            {!selected.pages.length ? <div className="import-page-empty"><strong>尚未分析</strong><p>点击“分析此文件”，系统只提取页面文字和题号标记，不生成题库内容。</p></div> : <div className="import-page-list">{selected.pages.map((page) => <button type="button" className={previewPage === page.page_number ? "active" : ""} key={page.page_id} onClick={() => setPreviewPage(page.page_number)}><span>{String(page.page_number).padStart(3, "0")}</span><div><strong>{page.has_text_layer ? `${page.character_count} 字符` : "文字层不足"}</strong><small>{page.question_marker_count} 个题号 · {page.embedded_image_count} 张图 · {Math.round(page.width_points)} × {Math.round(page.height_points)} pt</small></div><em className={page.has_text_layer ? "text" : "ocr"}>{page.has_text_layer ? "文本" : "OCR"}</em></button>)}</div>}
          </section> : viewMode === "boundaries" ? <section className="boundary-review">
            <header className="boundary-toolbar"><div><strong>题目边界校对</strong><small>{boundaries.draft_count} 待校对 · {boundaries.confirmed_count} 已确认 · {boundaries.discarded_count} 已弃用</small></div><div><button type="button" disabled={busy} onClick={addManualBoundary}>＋ 手工补题</button><button className="primary" type="button" disabled={busy || boundaries.total > 0} onClick={proposeBoundaries}>{busy ? "生成中…" : "生成边界候选"}</button></div></header>
            {!boundaries.total ? <div className="boundary-empty"><span>02</span><strong>把题号标记转成可校对的题目</strong><p>系统会给出起止页、题型和小问数量建议。所有结果必须由教师确认，且不会直接进入题库。</p><button type="button" disabled={busy} onClick={proposeBoundaries}>生成边界候选</button></div> : <ResizableColumns className="boundary-body" storageKey="pdf-boundary-candidate-editor" initialLeftPercent={40} leftMin={190} rightMin={280} collapse="compact" label="调整题目候选列表与候选编辑器宽度"><div className="boundary-list">{boundaries.items.map((item) => <button type="button" className={`${candidate?.candidate_id === item.candidate_id ? "active" : ""} ${item.status}`} key={item.candidate_id} onClick={() => selectCandidate(item)}><span>{String(item.position).padStart(3, "0")}</span><div><strong>{item.stem_text.replace(/\s+/g, " ").slice(0, 54) || "未填写题目"}</strong><small>第 {item.start_page}{item.end_page === item.start_page ? "" : `—${item.end_page}`} 页 · {questionTypeLabels[item.question_type]} · {item.subquestion_count || 0} 小问</small></div><em>{candidateStatusLabels[item.status]}</em></button>)}</div>
              {candidate ? <form className="boundary-editor" onSubmit={(event) => { event.preventDefault(); saveCandidate(); }}><header><div><span>候选 {String(candidate.position).padStart(3, "0")}</span><strong>{candidateStatusLabels[candidate.status]}</strong></div><small>修改会保存为教师校对版本</small></header><div className="boundary-fields"><label><span>起始页</span><input type="number" min={1} max={selected.page_count} value={candidate.start_page} onChange={(event) => { const value = Number(event.target.value); setCandidate({ ...candidate, start_page: value }); if (value >= 1 && value <= selected.page_count) setPreviewPage(value); }} /></label><label><span>结束页</span><input type="number" min={1} max={selected.page_count} value={candidate.end_page} onChange={(event) => setCandidate({ ...candidate, end_page: Number(event.target.value) })} /></label><label><span>题型</span><select value={candidate.question_type} onChange={(event) => setCandidate({ ...candidate, question_type: event.target.value as QuestionType })}>{Object.entries(questionTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>小问数量</span><input type="number" min={0} max={20} value={candidate.subquestion_count} onChange={(event) => setCandidate({ ...candidate, subquestion_count: Number(event.target.value) })} /></label></div><label className="boundary-text"><span>原始连续内容（题目、解析等）</span><textarea value={candidate.stem_text} onChange={(event) => setCandidate({ ...candidate, stem_text: event.target.value })} /></label><label className="boundary-note"><span>校对备注</span><input value={candidate.note} placeholder="例如：跨页题，图形在下一页" onChange={(event) => setCandidate({ ...candidate, note: event.target.value })} /></label><footer><button className="discard" type="button" disabled={busy} onClick={() => saveCandidate("discarded")}>弃用候选</button><div><button type="submit" disabled={busy || !candidate.stem_text.trim()}>保存修改</button><button className="confirm" type="button" disabled={busy || !candidate.stem_text.trim()} onClick={() => saveCandidate("confirmed")}>确认边界</button></div></footer></form> : <div className="boundary-editor" />}
            </ResizableColumns>}
          </section> : <section className="structured-review">
            <header className="boundary-toolbar"><div><strong>结构化题目校对</strong><small>{drafts.draft_count} 待校对 · {drafts.confirmed_count} 可入题库 · {drafts.imported_count} 已导入</small></div><div><button className="primary" type="button" disabled={busy} onClick={proposeStructuredDrafts}>{busy ? "处理中…" : drafts.total ? "同步新增确认边界" : "生成结构化草稿"}</button></div></header>
            {!drafts.total ? <div className="boundary-empty"><span>03</span><strong>分离题干、选项与解析</strong><p>只读取已确认的题目边界。自动结果是初稿，必须逐题检查公式与图片归属。</p><button type="button" disabled={busy || !boundaries.confirmed_count} onClick={proposeStructuredDrafts}>生成结构化草稿</button></div> : <ResizableColumns className="structured-body" storageKey="pdf-structured-draft-editor" initialLeftPercent={34} leftMin={210} rightMin={360} collapse="compact" label="调整结构化草稿列表与编辑器宽度"><div className="structured-list">{drafts.items.map((item) => <button type="button" className={`${draft?.draft_id === item.draft_id ? "active" : ""} ${item.status}`} key={item.draft_id} onClick={() => selectDraft(item)}><span>{String(item.position).padStart(3, "0")}</span><div><strong>{item.stem_plain.replace(/\s+/g, " ").slice(0, 58) || "未填写题干"}</strong><small>{questionTypeLabels[item.question_type]} · 公式{formulaStatusLabels[item.formula_status]} · {item.media_crops.length} 张裁剪图</small></div><em>{draftStatusLabels[item.status]}</em></button>)}</div>
              {draft ? <form className="structured-editor" onSubmit={(event) => { event.preventDefault(); saveDraft(); }}><header><div><span>草稿 {String(draft.position).padStart(3, "0")}</span><strong>{draftStatusLabels[draft.status]}</strong></div><small>来源第 {draft.start_page}{draft.end_page === draft.start_page ? "" : `—${draft.end_page}`} 页</small></header>
                {!!draft.warnings.length && <div className="structured-warnings">{draft.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
                <div className="structured-fields"><label><span>题型</span><select disabled={draft.status === "imported"} value={draft.question_type} onChange={(event) => setDraft({ ...draft, question_type: event.target.value as QuestionType })}>{Object.entries(questionTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>难度</span><select disabled={draft.status === "imported"} value={draft.difficulty} onChange={(event) => setDraft({ ...draft, difficulty: Number(event.target.value) })}>{[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value} 级</option>)}</select></label><label><span>公式校对</span><select disabled={draft.status === "imported"} value={draft.formula_status} onChange={(event) => setDraft({ ...draft, formula_status: event.target.value as FormulaStatus })}>{Object.entries(formulaStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
                <label><span>题干正文</span><textarea disabled={draft.status === "imported"} value={draft.stem_plain} onChange={(event) => setDraft({ ...draft, stem_plain: event.target.value })} /></label><label><span>LaTeX 题干（可选）</span><textarea className="compact" disabled={draft.status === "imported"} value={draft.stem_latex ?? ""} placeholder="对照原页重建公式，例如：已知 $f(x)=x^2$" onChange={(event) => setDraft({ ...draft, stem_latex: event.target.value || null })} /></label>
                <section className="structured-options"><header><strong>选项</strong><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft({ ...draft, options: [...draft.options, { key: String.fromCharCode(65 + draft.options.length), text: "" }] })}>＋ 添加选项</button></header>{draft.options.map((option, index) => <div key={`${option.key}-${index}`}><input disabled={draft.status === "imported"} aria-label={`选项 ${index + 1} 编号`} value={option.key} onChange={(event) => setDraft({ ...draft, options: draft.options.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value.toUpperCase() } : item) })} /><textarea disabled={draft.status === "imported"} value={option.text} onChange={(event) => setDraft({ ...draft, options: draft.options.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item) })} /><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft({ ...draft, options: draft.options.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>)}</section>
                <div className="structured-fields"><label><span>参考答案</span><input disabled={draft.status === "imported"} value={draft.answer_value ?? ""} onChange={(event) => setDraft({ ...draft, answer_value: event.target.value || null })} /></label><label><span>解析方法</span><input disabled={draft.status === "imported"} value={draft.solution_method} onChange={(event) => setDraft({ ...draft, solution_method: event.target.value })} /></label><label><span>最终答案</span><input disabled={draft.status === "imported"} value={draft.final_answer ?? ""} onChange={(event) => setDraft({ ...draft, final_answer: event.target.value || null })} /></label></div><label><span>自有解析步骤（每行一步）</span><textarea className="compact" disabled={draft.status === "imported"} value={draft.solution_steps.join("\n")} placeholder="不要复制原解析；在后续数学核验时独立编写" onChange={(event) => setDraft({ ...draft, solution_steps: event.target.value.split("\n") })} /></label>
                <section className="structured-media crop-manager"><header><div><strong>PDF 配图裁剪</strong><small>{draft.media_crops.length}/8 张 · 只允许框选本题第 {draft.start_page}{draft.end_page === draft.start_page ? "" : `—${draft.end_page}`} 页</small></div><button type="button" disabled={draft.status === "imported" || draft.media_crops.length >= 8 || previewPage < draft.start_page || previewPage > draft.end_page} onClick={() => { setCropMode(true); setCropRect(null); }}>＋ 框选当前页</button></header>{cropMode && <div className="crop-actions"><select value={cropPlacement} onChange={(event) => setCropPlacement(event.target.value as "stem" | "solution")}><option value="stem">题干图</option><option value="solution">解析图</option></select><input value={cropNote} placeholder="图片说明，例如：圆与切线示意图" onChange={(event) => setCropNote(event.target.value)} /><button type="button" disabled={!cropRect || busy} onClick={saveCrop}>保存框选</button><button type="button" onClick={() => { setCropMode(false); setCropRect(null); }}>取消</button></div>}{draft.media_crops.length ? <div className="crop-gallery">{draft.media_crops.map((crop) => <article key={crop.crop_id}><button className="crop-preview" type="button" onClick={() => setPreviewPage(crop.page_number)}><img src={`/api/v1/imports/media-crops/${crop.crop_id}/file`} alt={crop.note || `第 ${crop.page_number} 页裁剪图`} /></button><div><strong>{crop.placement === "stem" ? "题干图" : "解析图"} · 第 {crop.page_number} 页</strong><small>{crop.pixel_width} × {crop.pixel_height} px · {crop.note || "未填写说明"}</small></div><button className="crop-delete" type="button" disabled={draft.status === "imported" || busy} onClick={() => deleteCrop(crop.crop_id)}>删除</button></article>)}</div> : <p>切换到题目所在页，点击“框选当前页”，再在左侧 PDF 上拖动选择图形、表格或坐标系。</p>}</section>
                <section className="structured-media"><header><strong>未裁剪图片备注</strong><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft({ ...draft, media_references: [...draft.media_references, { page_number: previewPage, placement: "stem", note: "待裁剪或替换" }] })}>＋ 添加来源页</button></header>{draft.media_references.length ? draft.media_references.map((media, index) => <div key={`${media.page_number}-${index}`}><input type="number" min={1} max={selected.page_count} disabled={draft.status === "imported"} value={media.page_number} onChange={(event) => setDraft({ ...draft, media_references: draft.media_references.map((item, itemIndex) => itemIndex === index ? { ...item, page_number: Number(event.target.value) } : item) })} /><select disabled={draft.status === "imported"} value={media.placement} onChange={(event) => setDraft({ ...draft, media_references: draft.media_references.map((item, itemIndex) => itemIndex === index ? { ...item, placement: event.target.value as "stem" | "solution" } : item) })}><option value="stem">题干图</option><option value="solution">解析图</option></select><input disabled={draft.status === "imported"} value={media.note} onChange={(event) => setDraft({ ...draft, media_references: draft.media_references.map((item, itemIndex) => itemIndex === index ? { ...item, note: event.target.value } : item) })} /><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft({ ...draft, media_references: draft.media_references.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>) : <p>仅在暂时无法裁剪、需要重绘或图片跨页时保留备注。</p>}</section>
                <label><span>校对备注</span><input disabled={draft.status === "imported"} value={draft.note} placeholder="例如：分式已重建，原页图形需重绘" onChange={(event) => setDraft({ ...draft, note: event.target.value })} /></label><footer>{draft.status === "imported" ? <a href={`/search?q=${encodeURIComponent(draft.imported_question_id ?? "")}`}>前往题库审核</a> : <><button type="submit" disabled={busy || !draft.stem_plain.trim()}>保存草稿</button><button className="confirm" type="button" disabled={busy || !draft.stem_plain.trim() || draft.formula_status !== "confirmed" || draft.question_type === "unknown"} onClick={() => saveDraft("confirmed")}>确认结构</button><button className="import" type="button" disabled={busy || draft.status !== "confirmed"} onClick={importDraft}>送入题库审核</button></>}</footer>
              </form> : <div className="structured-editor" />}
            </ResizableColumns>}
          </section>}
        </ResizableColumns>
        <footer className="import-next-stage"><div><span>{viewMode === "structured" ? "题库安全门" : "下一加工环节"}</span><strong>{viewMode === "pages" ? "题目边界与小问校对" : viewMode === "boundaries" ? "题干、选项、公式与配图校对" : "进入私人题库继续质量审核"}</strong><p>{viewMode === "pages" ? "在页坐标和文字层之上生成拆题候选，并继续保持教师确认门禁。" : viewMode === "boundaries" ? "只有教师确认过的边界才会生成结构化草稿，且不会自动入库。" : "已导入题仍是私人待审核草稿，还需教材映射、独立数学核验和教师确认。"}</p></div>{viewMode === "pages" ? <button type="button" disabled={selected.status !== "ready_for_segmentation"} onClick={() => { setViewMode("boundaries"); if (!boundaries.total) proposeBoundaries(); }}>{selected.status === "ready_for_segmentation" ? "进入边界校对" : "请先完成页面分析"}</button> : viewMode === "boundaries" ? <button type="button" disabled={!boundaries.confirmed_count || busy} onClick={() => { setViewMode("structured"); if (!drafts.total) proposeStructuredDrafts(); }}>进入内容结构化</button> : <em>{drafts.imported_count}/{drafts.total} 已入题库</em>}</footer>
      </>}</main>
    </ResizableColumns>
  </div>;
}
