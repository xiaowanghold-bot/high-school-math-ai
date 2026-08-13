"use client";

import { ChangeEvent, FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { AdminGuard } from "../components/admin-guard";
import { MathText } from "../components/math-text";
import { ResizableColumns } from "../components/resizable-columns";
import { useToast } from "../components/toast-provider";
import "./imports.css";

type ImportStatus = "registered" | "queued" | "analyzing" | "paused" | "ready_for_segmentation" | "failed";
type CandidateStatus = "draft" | "confirmed" | "discarded";
type DraftStatus = "draft" | "confirmed" | "imported";
type FormulaStatus = "pending" | "needs_review" | "confirmed";
type QuestionType = "single_choice" | "multiple_choice" | "fill_blank" | "open_response" | "unknown";
type ImportPage = { page_id: string; page_number: number; width_points: number; height_points: number; extracted_text: string; character_count: number; question_marker_count: number; embedded_image_count: number; has_text_layer: boolean; warnings: string[] };
type ImportFile = { file_id: string; batch_id: string; original_filename: string; size_bytes: number; sha256: string; page_count: number; status: ImportStatus; analysis_attempts: number; analyzed_page_count: number; progress_percent: number; resume_page: number | null; text_page_count: number; scan_page_count: number; extracted_character_count: number; question_marker_count: number; estimated_question_count: number; image_page_count: number; embedded_image_count: number; warnings: string[]; error_message: string; created_at: string; updated_at: string };
type ImportFileDetail = ImportFile & { pages: ImportPage[] };
type ImportBatch = { batch_id: string; title: string; rights_basis: string; rights_statement: string; owner_id: string; file_count: number; registered_count: number; queued_count: number; analyzing_count: number; paused_count: number; ready_count: number; failed_count: number; page_count: number; analyzed_page_count: number; progress_percent: number; question_marker_count: number; estimated_question_count: number; created_at: string; updated_at: string; files: ImportFile[] };
type ImportWorkspace = { stats: { batches: number; files: number; pages: number; analyzed_pages: number; ready_files: number; queued_files: number; failed_files: number; scan_pages: number; question_markers: number; estimated_questions: number }; batches: ImportBatch[] };
type SourceRole = "question_only" | "solution_reference" | "combined" | "unknown";
type SourcePairStatus = "proposed" | "confirmed" | "rejected";
type SourcePair = { pair_id: string; question_file: ImportFile; solution_file: ImportFile; confidence: number; status: SourcePairStatus; strategy: string; signals: string[]; note: string; reviewer_id: string | null; created_at: string; updated_at: string };
type SourcePairing = { file_id: string; inferred_role: SourceRole; coverage_status: "self_contained" | "paired" | "candidates" | "unpaired"; role_signals: string[]; candidates: SourcePair[] };
type SourceItemMatch = { item_match_id: string; pair_id: string; question_candidate: BoundaryCandidate; solution_candidate: BoundaryCandidate; confidence: number; status: SourcePairStatus; stale: boolean; strategy: string; signals: string[]; note: string; reviewer_id: string | null; created_at: string; updated_at: string };
type SourceItemMatches = { pair_id: string; question_file_id: string; solution_file_id: string; total_question_count: number; matched_count: number; proposed_count: number; confirmed_count: number; rejected_count: number; stale_count: number; unmatched_question_count: number; items: SourceItemMatch[] };
type BoundaryCandidate = { candidate_id: string; file_id: string; position: number; start_page: number; end_page: number; stem_text: string; question_type: QuestionType; subquestion_count: number; status: CandidateStatus; note: string; editor_id: string; source_analysis_updated_at: string; created_at: string; updated_at: string };
type BoundaryList = { file_id: string; source_analysis_updated_at: string; total: number; draft_count: number; confirmed_count: number; discarded_count: number; items: BoundaryCandidate[] };
type StructuredOption = { key: string; text: string };
type FormulaIssue = { code: string; severity: "blocking" | "warning"; field: string; message: string; excerpt: string };
type FormulaCheck = { status: "passed" | "blocked"; content_signature: string; issues: FormulaIssue[]; checked_at: string; checked_by: string; teacher_confirmed: boolean };
type MediaReference = { page_number: number; placement: "stem" | "solution"; note: string };
type MediaCrop = { crop_id: string; draft_id: string; file_id: string; page_number: number; placement: "stem" | "solution"; x_ratio: number; y_ratio: number; width_ratio: number; height_ratio: number; note: string; editor_id: string; pixel_width: number; pixel_height: number; imported_image_id: string | null; created_at: string };
type CropRect = { x_ratio: number; y_ratio: number; width_ratio: number; height_ratio: number };
type StructuredDraft = { draft_id: string; file_id: string; boundary_candidate_id: string; position: number; start_page: number; end_page: number; source_text: string; question_type: QuestionType; stem_plain: string; stem_latex: string | null; options: StructuredOption[]; answer_value: string | null; solution_method: string; solution_steps: string[]; final_answer: string | null; difficulty: number; formula_status: FormulaStatus; formula_check: FormulaCheck | null; media_references: MediaReference[]; media_crops: MediaCrop[]; status: DraftStatus; warnings: string[]; note: string; editor_id: string; imported_question_id: string | null; created_at: string; updated_at: string };
type StructuredDraftList = { file_id: string; total: number; draft_count: number; confirmed_count: number; imported_count: number; items: StructuredDraft[] };
type StructuredDraftRepairResult = { drafts: StructuredDraftList; repaired_count: number; skipped_teacher_edits: number; skipped_imported: number; review_required_count: number; unresolved_glyph_count: number; math_ocr_count: number; math_ocr_failed_count: number; message: string };

const statusLabels: Record<ImportStatus, string> = { registered: "待分析", queued: "队列中", analyzing: "分析中", paused: "已暂停", ready_for_segmentation: "可进入拆题", failed: "分析失败" };
const candidateStatusLabels: Record<CandidateStatus, string> = { draft: "待校对", confirmed: "已确认", discarded: "已弃用" };
const draftStatusLabels: Record<DraftStatus, string> = { draft: "待校对", confirmed: "可入题库", imported: "已入题库" };
const formulaStatusLabels: Record<FormulaStatus, string> = { pending: "待检查", needs_review: "需校正", confirmed: "已核对" };
const formulaFieldLabels: Record<string, string> = { stem_plain: "题干正文", stem_latex: "LaTeX 题干", options: "选项", answer_value: "参考答案", solution_method: "解析方法", solution_steps: "解析步骤", final_answer: "最终答案" };
const questionTypeLabels: Record<QuestionType, string> = { single_choice: "单选题", multiple_choice: "多选题", fill_blank: "填空题", open_response: "解答题", unknown: "待判断" };
const rightsLabels: Record<string, string> = { question_content_user_declared_usable: "题目内容经本人声明可使用", licensed: "已获得明确授权", original: "本人原创", private_research_only: "仅限内部研究" };
const sourceRoleLabels: Record<SourceRole, string> = { question_only: "仅题目资料", solution_reference: "答案参考资料", combined: "题解同文件", unknown: "待识别" };
const sourceCoverageLabels: Record<SourcePairing["coverage_status"], string> = { self_contained: "无需额外配对", paired: "已确认配对", candidates: "发现配对候选", unpaired: "尚未配对" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}
function formatBytes(value: number) { return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function emptyBoundaries(fileId = ""): BoundaryList { return { file_id: fileId, source_analysis_updated_at: "", total: 0, draft_count: 0, confirmed_count: 0, discarded_count: 0, items: [] }; }
function emptyDrafts(fileId = ""): StructuredDraftList { return { file_id: fileId, total: 0, draft_count: 0, confirmed_count: 0, imported_count: 0, items: [] }; }
function invalidateFormulaCheck(next: StructuredDraft): StructuredDraft {
  return { ...next, formula_status: "needs_review", formula_check: null, status: next.status === "confirmed" ? "draft" : next.status };
}
function draftUpdatePayload(target: StructuredDraft, status: DraftStatus = target.status) {
  return {
    question_type: target.question_type, stem_plain: target.stem_plain, stem_latex: target.stem_latex,
    options: target.options, answer_value: target.answer_value, solution_method: target.solution_method,
    solution_steps: target.solution_steps, final_answer: target.final_answer, difficulty: target.difficulty,
    formula_status: target.formula_status, media_references: target.media_references,
    note: target.note, status, editor_id: "owner_teacher",
  };
}

function ImportsPageContent() {
  const [workspace, setWorkspace] = useState<ImportWorkspace | null>(null);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [selected, setSelected] = useState<ImportFileDetail | null>(null);
  const [sourcePairing, setSourcePairing] = useState<SourcePairing | null>(null);
  const [sourceItemMatches, setSourceItemMatches] = useState<SourceItemMatches | null>(null);
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
  const queueStopRequested = useRef(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("三文件结构化试点");
  const [rightsBasis, setRightsBasis] = useState("question_content_user_declared_usable");
  const [rightsStatement, setRightsStatement] = useState("本人确认仅使用题目事实，不复用原 PDF 版式、封面、水印、讲义文字和原解析表述。");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [queueRunning, setQueueRunning] = useState(false);
  const { auto: setMessage } = useToast();

  const selectedBatch = useMemo(() => workspace?.batches.find((batch) => batch.batch_id === selected?.batch_id) ?? null, [selected, workspace]);
  const visibleSourcePairs = useMemo(() => sourcePairing?.candidates.filter((item) => item.status !== "rejected") ?? [], [sourcePairing]);

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

  async function loadSourcePairing(fileId: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}/source-pairing`);
    if (!response.ok) throw new Error(await errorText(response));
    const payload: SourcePairing = await response.json();
    setSourcePairing(payload);
    const confirmed = payload.candidates.find((item) => item.status === "confirmed");
    if (confirmed) await loadSourceItemMatches(confirmed.pair_id);
    else setSourceItemMatches(null);
  }

  async function loadSourceItemMatches(pairId: string) {
    const response = await fetch(`/api/v1/imports/source-pairs/${pairId}/item-matches`);
    if (!response.ok) throw new Error(await errorText(response));
    setSourceItemMatches(await response.json());
  }

  async function openFile(fileId: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const detail: ImportFileDetail = await response.json();
    setSelectedFileId(fileId);
    setSelected(detail);
    setPreviewPage(1);
    await Promise.all([loadBoundaries(fileId), loadDrafts(fileId), loadSourcePairing(fileId)]);
  }

  async function refresh(preferredFileId?: string) {
    const response = await fetch("/api/v1/imports");
    if (!response.ok) throw new Error(await errorText(response));
    const payload: ImportWorkspace = await response.json();
    setWorkspace(payload);
    const target = preferredFileId || selectedFileId || payload.batches[0]?.files[0]?.file_id;
    if (target) await openFile(target);
    else { setSelected(null); setSelectedFileId(""); setSourcePairing(null); setSourceItemMatches(null); setBoundaries(emptyBoundaries()); setDrafts(emptyDrafts()); }
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

  async function proposeSourcePairs() {
    if (!selected) return;
    setBusy(true);
    try {
      const response = await fetch("/api/v1/imports/source-pairs/propose", { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      await loadSourcePairing(selected.file_id);
      setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "来源配对扫描失败"); }
    finally { setBusy(false); }
  }

  async function reviewSourcePair(pairId: string, status: "confirmed" | "rejected") {
    if (!selected) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/imports/source-pairs/${pairId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, reviewer_id: "owner_teacher", note: status === "confirmed" ? "教师确认文件题目结构一致" : "教师排除错误配对" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      await loadSourcePairing(selected.file_id);
      setMessage(status === "confirmed" ? "已确认原题与解析来源配对。" : "已排除该配对候选。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "来源配对审核失败"); }
    finally { setBusy(false); }
  }

  async function proposeSourceItemMatches(pairId: string) {
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/imports/source-pairs/${pairId}/item-matches/propose`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setSourceItemMatches(result.matches);
      setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "逐题关联生成失败"); }
    finally { setBusy(false); }
  }

  async function reviewSourceItemMatch(pairId: string, itemMatchId: string, status: "confirmed" | "rejected") {
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/imports/source-pairs/${pairId}/item-matches/${itemMatchId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, reviewer_id: "owner_teacher", note: status === "confirmed" ? "教师确认题干与题目顺序一致" : "教师排除错误逐题匹配" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      await loadSourceItemMatches(pairId);
      setMessage(status === "confirmed" ? "已确认当前逐题匹配。" : "已排除当前逐题匹配。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "逐题匹配审核失败"); }
    finally { setBusy(false); }
  }

  async function confirmHighConfidenceSourceItems(pairId: string) {
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/imports/source-pairs/${pairId}/item-matches/confirm-high-confidence`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); setSourceItemMatches(result.matches); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "批量确认失败"); }
    finally { setBusy(false); }
  }

  async function analyzeFile() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const force = selected.status === "ready_for_segmentation" ? "?force=true" : "";
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/analyze${force}`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json(); await refresh(selected.file_id); setMessage(result.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "文件分析失败"); }
    finally { setBusy(false); }
  }

  async function processBatchQueue() {
    if (!selectedBatch) return;
    const batchId = selectedBatch.batch_id;
    const preferredFileId = selected?.file_id;
    queueStopRequested.current = false;
    setQueueRunning(true); setMessage("");
    try {
      const queuedResponse = await fetch(`/api/v1/imports/batches/${batchId}/queue`, { method: "POST" });
      if (!queuedResponse.ok) throw new Error(await errorText(queuedResponse));
      let lastMessage = (await queuedResponse.json()).message as string;
      while (!queueStopRequested.current) {
        const response = await fetch(`/api/v1/imports/batches/${batchId}/process-next?page_budget=12`, { method: "POST" });
        if (!response.ok) throw new Error(await errorText(response));
        const step = await response.json();
        lastMessage = step.message;
        await refresh(preferredFileId);
        setMessage(`${step.message} 批次总进度 ${step.batch.analyzed_page_count}/${step.batch.page_count} 页。`);
        if (step.remaining_count === 0) break;
      }
      if (queueStopRequested.current) {
        await fetch(`/api/v1/imports/batches/${batchId}/pause`, { method: "POST" });
        await refresh(preferredFileId);
        setMessage("批次已暂停；已完成的页面检查点均已保存，下次将从断点继续。");
      } else {
        setMessage(lastMessage || "批次队列处理完成。");
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : "批次队列处理失败"); }
    finally { setQueueRunning(false); }
  }

  async function pauseBatchQueue() {
    if (!selectedBatch) return;
    queueStopRequested.current = true;
    try {
      const response = await fetch(`/api/v1/imports/batches/${selectedBatch.batch_id}/pause`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      setMessage("正在完成当前页组，随后暂停队列…");
    } catch (error) { setMessage(error instanceof Error ? error.message : "暂停队列失败"); }
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
      const repairResponse = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/auto-repair?math_ocr=true`, { method: "POST" });
      if (!repairResponse.ok) throw new Error(await errorText(repairResponse));
      const repaired: StructuredDraftRepairResult = await repairResponse.json();
      setDrafts(repaired.drafts);
      const first: StructuredDraft | null = repaired.drafts.items[0] ?? null;
      setDraft(first); if (first) setPreviewPage(first.start_page);
      setViewMode("structured");
      const ocrFailed = repaired.math_ocr_failed_count ? `；${repaired.math_ocr_failed_count} 道未匹配到 OCR 候选` : "";
      setMessage(`${result.message}数学公式已自动识别 ${repaired.math_ocr_count} 道${ocrFailed}。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "生成结构化草稿失败"); }
    finally { setBusy(false); }
  }

  async function autoRepairStructuredDrafts() {
    if (!selected || !drafts.total) return;
    const preferredDraftId = draft?.draft_id;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/auto-repair?math_ocr=true`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const result: StructuredDraftRepairResult = await response.json();
      setDrafts(result.drafts);
      const next = result.drafts.items.find((item) => item.draft_id === preferredDraftId) ?? result.drafts.items[0] ?? null;
      setDraft(next); if (next) setPreviewPage(next.start_page);
      const preserved = result.skipped_teacher_edits ? `；已保护 ${result.skipped_teacher_edits} 道教师修改稿` : "";
      const unresolved = result.unresolved_glyph_count ? `；仍有 ${result.unresolved_glyph_count} 个异常字形待核` : "；未残留乱码字符";
      const ocrFailed = result.math_ocr_failed_count ? `；${result.math_ocr_failed_count} 道未匹配到 OCR 候选` : "";
      setMessage(`${result.message}${preserved}${unresolved}${ocrFailed}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "自动修复题目失败"); }
    finally { setBusy(false); }
  }

  async function saveDraft(status?: DraftStatus) {
    if (!selected || !draft) return;
    const nextStatus = status ?? draft.status;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draftUpdatePayload(draft, nextStatus)),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const updated: StructuredDraft = await response.json();
      await loadDrafts(selected.file_id, updated.draft_id);
      setMessage(nextStatus === "confirmed" ? "结构与公式已确认，现在可以送入题库继续数学核验和教师审核。" : "结构化草稿已保存。 ");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存结构化草稿失败"); }
    finally { setBusy(false); }
  }

  async function reviewFormula(confirm: boolean) {
    if (!selected || !draft) return;
    setBusy(true); setMessage("");
    try {
      const savedResponse = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draftUpdatePayload(draft)),
      });
      if (!savedResponse.ok) throw new Error(await errorText(savedResponse));
      const response = await fetch(`/api/v1/imports/files/${selected.file_id}/structured-drafts/${draft.draft_id}/formula-review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm, reviewer_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const reviewed: StructuredDraft = await response.json();
      await loadDrafts(selected.file_id, reviewed.draft_id);
      const blockingCount = reviewed.formula_check?.issues.filter((issue) => issue.severity === "blocking").length ?? 0;
      const warningCount = reviewed.formula_check?.issues.filter((issue) => issue.severity === "warning").length ?? 0;
      if (blockingCount) setMessage(`公式检查发现 ${blockingCount} 个必须修正的问题，请按定位修改后重新检查。`);
      else if (confirm) setMessage(warningCount ? `公式已由教师确认；另有 ${warningCount} 条提示供复核。` : "当前版本公式已由教师确认。后续修改公式相关内容会自动使确认失效。");
      else setMessage(warningCount ? `自动检查通过，另有 ${warningCount} 条提示。请对照左侧原 PDF 后再确认公式。` : "自动检查通过。请对照左侧原 PDF 后点击“教师确认公式”。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "公式检查失败"); }
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
    <section className="import-stats"><div><span>导入批次</span><strong>{workspace?.stats.batches ?? "—"}</strong><small>保留权利声明</small></div><div><span>PDF 文件</span><strong>{workspace?.stats.files ?? "—"}</strong><small>{workspace?.stats.pages ?? 0} 页</small></div><div className="ready"><span>页面处理进度</span><strong>{workspace ? `${workspace.stats.analyzed_pages}/${workspace.stats.pages}` : "—"}</strong><small>{workspace?.stats.ready_files ?? 0} 份可进入拆题</small></div><div><span>候选题量估计</span><strong>{workspace?.stats.estimated_questions ?? "—"}</strong><small>来自题量审计表</small></div><div className={workspace?.stats.scan_pages ? "attention" : ""}><span>待 OCR 页面</span><strong>{workspace?.stats.scan_pages ?? "—"}</strong><small>{workspace?.stats.failed_files ?? 0} 份失败待重试</small></div></section>

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
        {workspace?.batches.map((batch) => <section key={batch.batch_id} className="import-batch-group"><header><div><strong>{batch.title}</strong><small>{batch.file_count} 份 · {batch.page_count} 页 · 估计 {batch.estimated_question_count || "待统计"} 题</small></div><em>{batch.progress_percent}%</em></header><div className="import-batch-progress"><span style={{ width: `${batch.progress_percent}%` }} /></div><div className="import-batch-state"><span>{batch.analyzed_page_count}/{batch.page_count} 页</span><span>{batch.queued_count + batch.analyzing_count ? `${batch.queued_count + batch.analyzing_count} 份排队` : batch.paused_count ? `${batch.paused_count} 份暂停` : batch.failed_count ? `${batch.failed_count} 份失败` : `${batch.ready_count}/${batch.file_count} 完成`}</span></div>{batch.files.map((file) => <button type="button" className={selectedFileId === file.file_id ? "active" : ""} key={file.file_id} onClick={() => openFile(file.file_id).catch((error: Error) => setMessage(error.message))}><span className={`import-file-status ${file.status}`}>PDF</span><div><b>{file.original_filename}</b><small>{file.analyzed_page_count}/{file.page_count} 页 · 估计 {file.estimated_question_count || "—"} 题 · {formatBytes(file.size_bytes)}</small><span className="import-file-progress"><i style={{ width: `${file.progress_percent}%` }} /></span></div><em className={file.status}>{statusLabels[file.status]}</em></button>)}</section>)}
      </aside>

      <main className="import-inspector">{!selected ? <div className="import-inspector-empty"><span>PDF</span><h2>选择文件检查页面质量</h2><p>这里会显示原文件、文字层覆盖、题号标记和需要 OCR 的页面。</p></div> : <>
        <header className="import-inspector-heading"><div><p>{selectedBatch?.title}</p><h2>{selected.original_filename}</h2><small>SHA-256：{selected.sha256.slice(0, 18)}… · {formatBytes(selected.size_bytes)}</small></div><div><a href={`/api/v1/imports/files/${selected.file_id}/source`} target="_blank" rel="noreferrer">打开原 PDF</a><button type="button" disabled={busy || queueRunning} onClick={analyzeFile}>{busy ? "处理中…" : selected.status === "ready_for_segmentation" ? "重新分析" : selected.analyzed_page_count ? `从第 ${selected.resume_page} 页继续` : "分析此文件"}</button>{queueRunning ? <button className="pause" type="button" onClick={pauseBatchQueue}>暂停队列</button> : <button className="primary" type="button" disabled={busy || !selectedBatch || selectedBatch.ready_count === selectedBatch.file_count} onClick={processBatchQueue}>{selectedBatch && (selectedBatch.paused_count || selectedBatch.failed_count || selectedBatch.analyzed_page_count) ? "继续本批队列" : "启动本批队列"}</button>}</div></header>
        <section className="import-file-metrics"><div><span>状态</span><strong className={selected.status}>{statusLabels[selected.status]}</strong></div><div><span>页面进度</span><strong>{selected.analyzed_page_count}/{selected.page_count}</strong></div><div><span>处理完成度</span><strong>{selected.progress_percent}%</strong></div><div><span>待 OCR</span><strong>{selected.scan_page_count}</strong></div><div><span>估计题量 / 题号</span><strong>{selected.estimated_question_count || "—"} / {selected.question_marker_count}</strong></div></section>
        {selected.error_message && <div className="notice warning">{selected.error_message}</div>}{selected.warnings.map((warning) => <p className="import-warning" key={warning}>{warning}</p>)}
        {sourcePairing && <section className={`source-pair-panel ${sourcePairing.coverage_status}`}>
          <header><div><span>原题与解析自动配对</span><strong>{sourceCoverageLabels[sourcePairing.coverage_status]}</strong><em>{sourceRoleLabels[sourcePairing.inferred_role]}</em></div><button type="button" disabled={busy} onClick={proposeSourcePairs}>{busy ? "扫描中…" : "扫描全部文件"}</button></header>
          <div className="source-pair-body"><div className="source-pair-explanation"><strong>{sourcePairing.coverage_status === "self_contained" ? "当前文件已同时包含题目和解析" : sourcePairing.coverage_status === "paired" ? "文件关系已经教师确认" : sourcePairing.coverage_status === "candidates" ? `发现 ${visibleSourcePairs.length} 个可审核候选` : "暂未找到标题和题量足够接近的文件"}</strong><p>{sourcePairing.coverage_status === "self_contained" ? "系统将直接从本文件提取题干与答案种子，不会重复计入另一套题库。" : "系统不会依靠固定页码差；确认后仍只把答案作为核验种子，原解析不会直接发布。"}</p><small>{sourcePairing.role_signals.join(" · ")}</small></div>
            {!!visibleSourcePairs.length && <div className="source-pair-candidates">{visibleSourcePairs.map((pair) => { const counterpart = pair.question_file.file_id === selected.file_id ? pair.solution_file : pair.question_file; return <article key={pair.pair_id} className={pair.status}><div><span>{pair.question_file.file_id === selected.file_id ? "推荐解析来源" : "对应原题来源"}</span><strong title={counterpart.original_filename}>{counterpart.original_filename}</strong><small>{pair.signals.join(" · ")}</small></div><em>{Math.round(pair.confidence * 100)}%</em>{pair.status === "proposed" ? <div className="source-pair-actions"><button type="button" disabled={busy} onClick={() => reviewSourcePair(pair.pair_id, "rejected")}>排除</button><button className="confirm" type="button" disabled={busy} onClick={() => reviewSourcePair(pair.pair_id, "confirmed")}>确认配对</button></div> : <b>教师已确认</b>}</article>; })}</div>}
          </div>
          {sourcePairing.coverage_status === "paired" && (() => { const pair = sourcePairing.candidates.find((item) => item.status === "confirmed"); if (!pair) return null; const activeItems = sourceItemMatches?.items.filter((item) => item.status !== "rejected") ?? []; return <section className="source-item-panel"><header><div><strong>逐题关联</strong><small>{sourceItemMatches ? `${sourceItemMatches.confirmed_count} 已确认 · ${sourceItemMatches.proposed_count} 待审核 · ${sourceItemMatches.unmatched_question_count} 未匹配${sourceItemMatches.stale_count ? ` · ${sourceItemMatches.stale_count} 已过期` : ""}` : "匹配原题边界与解析边界"}</small></div><div>{!!sourceItemMatches?.proposed_count && <button type="button" disabled={busy} onClick={() => confirmHighConfidenceSourceItems(pair.pair_id)}>确认 ≥92%</button>}<button className="primary" type="button" disabled={busy} onClick={() => proposeSourceItemMatches(pair.pair_id)}>{sourceItemMatches?.items.length ? "重新匹配" : "生成逐题匹配"}</button></div></header>{sourceItemMatches && <div className="source-item-progress"><span style={{ width: `${sourceItemMatches.total_question_count ? sourceItemMatches.matched_count / sourceItemMatches.total_question_count * 100 : 0}%` }} /></div>}{activeItems.length ? <div className="source-item-list">{activeItems.slice(0, 12).map((item) => <article key={item.item_match_id} className={`${item.status} ${item.stale ? "stale" : ""}`}><div className="source-item-number"><span>{String(item.question_candidate.position).padStart(3, "0")}</span><i>→</i><span>{String(item.solution_candidate.position).padStart(3, "0")}</span></div><div className="source-item-text"><strong>{item.question_candidate.stem_text.replace(/\s+/g, " ").slice(0, 70)}</strong><small>{item.signals.join(" · ")}</small></div><em>{item.stale ? "已过期" : `${Math.round(item.confidence * 100)}%`}</em>{item.status === "proposed" && !item.stale ? <div className="source-item-actions"><button type="button" disabled={busy} onClick={() => reviewSourceItemMatch(pair.pair_id, item.item_match_id, "rejected")}>排除</button><button className="confirm" type="button" disabled={busy} onClick={() => reviewSourceItemMatch(pair.pair_id, item.item_match_id, "confirmed")}>确认</button></div> : <b>{item.status === "confirmed" && !item.stale ? "已确认" : "需重匹配"}</b>}</article>)}</div> : <div className="source-item-empty"><span>题</span><div><strong>尚未生成逐题匹配</strong><p>先分别确认两份文件的题目边界，再按题干核心文本和相对顺序建立关联。</p></div></div>}</section>; })()}
        </section>}
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
            <header className="boundary-toolbar"><div><strong>结构化题目校对</strong><small>{drafts.draft_count} 待校对 · {drafts.confirmed_count} 可入题库 · {drafts.imported_count} 已导入</small></div><div>{drafts.total > 0 && <button type="button" disabled={busy} onClick={autoRepairStructuredDrafts}>自动修复全部题目</button>}<button className="primary" type="button" disabled={busy} onClick={proposeStructuredDrafts}>{busy ? "处理中…" : drafts.total ? "同步新增确认边界" : "生成结构化草稿"}</button></div></header>
            {drafts.total > 0 && <p className="structured-auto-note">正文会自动清理，只有数学表达式需要公式格式；低置信度内容保留“需校正”状态，教师只需对照左侧原页抽查，无需逐题重输 LaTeX。</p>}
            {!drafts.total ? <div className="boundary-empty"><span>03</span><strong>分离题干、选项与解析</strong><p>只读取已确认的题目边界。自动结果是初稿，必须逐题检查公式与图片归属。</p><button type="button" disabled={busy || !boundaries.confirmed_count} onClick={proposeStructuredDrafts}>生成结构化草稿</button></div> : <ResizableColumns className="structured-body" storageKey="pdf-structured-draft-editor" initialLeftPercent={34} leftMin={210} rightMin={360} collapse="compact" label="调整结构化草稿列表与编辑器宽度"><div className="structured-list">{drafts.items.map((item) => <button type="button" className={`${draft?.draft_id === item.draft_id ? "active" : ""} ${item.status}`} key={item.draft_id} onClick={() => selectDraft(item)}><span>{String(item.position).padStart(3, "0")}</span><div><strong>{item.stem_plain.replace(/\s+/g, " ").slice(0, 58) || "未填写题干"}</strong><small>{questionTypeLabels[item.question_type]} · 公式{formulaStatusLabels[item.formula_status]} · {item.media_crops.length} 张裁剪图</small></div><em>{draftStatusLabels[item.status]}</em></button>)}</div>
              {draft ? <form className="structured-editor" onSubmit={(event) => { event.preventDefault(); saveDraft(); }}><header><div><span>草稿 {String(draft.position).padStart(3, "0")}</span><strong>{draftStatusLabels[draft.status]}</strong></div><small>来源第 {draft.start_page}{draft.end_page === draft.start_page ? "" : `—${draft.end_page}`} 页</small></header>
                {!!draft.warnings.length && <div className="structured-warnings">{draft.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
                {draft.stem_latex?.trim() && <section className="structured-ocr-preview"><span>数学 OCR 自动可读预览</span><p><MathText text={draft.stem_latex} /></p><small>公式已自动生成，无需手工重输 LaTeX；“需校正”表示仍要对照左侧原页抽查数学准确性。</small></section>}
                <div className="structured-fields"><label><span>题型</span><select disabled={draft.status === "imported"} value={draft.question_type} onChange={(event) => setDraft({ ...draft, question_type: event.target.value as QuestionType })}>{Object.entries(questionTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>难度</span><select disabled={draft.status === "imported"} value={draft.difficulty} onChange={(event) => setDraft({ ...draft, difficulty: Number(event.target.value) })}>{[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value} 级</option>)}</select></label><div className="formula-summary"><span>公式校对</span><strong className={draft.formula_status}>{formulaStatusLabels[draft.formula_status]}</strong><small>{draft.formula_check?.teacher_confirmed ? "已绑定当前内容版本" : "不能手动跳过检查"}</small></div></div>
                <label><span>{draft.stem_latex?.trim() ? "PDF 文字层（保留用于检索与对照）" : "可读题干（文字＋公式）"}</span><textarea disabled={draft.status === "imported"} value={draft.stem_plain} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, stem_plain: event.target.value }))} /></label><label><span>LaTeX 题干（系统自动生成，可修改）</span><textarea className="compact" disabled={draft.status === "imported"} value={draft.stem_latex ?? ""} placeholder="系统已自动整理常见公式；复杂分式或矩阵可在此覆盖，例如：已知 $f(x)=x^2$" onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, stem_latex: event.target.value || null }))} /></label>
                <section className={`formula-review-panel ${draft.formula_check?.status ?? "unchecked"}`}>
                  <header><div><strong>公式校对助手</strong><small>自动查找乱码、分隔符和 LaTeX 结构问题；最终仍需教师对照原 PDF。</small></div><div><button type="button" disabled={busy || draft.status === "imported" || !draft.stem_plain.trim()} onClick={() => reviewFormula(false)}>检查当前版本</button><button className="formula-confirm" type="button" disabled={busy || draft.status === "imported" || !draft.stem_plain.trim()} onClick={() => reviewFormula(true)}>教师确认公式</button></div></header>
                  <div className="formula-preview"><span>渲染预览</span><p><MathText text={draft.stem_latex?.trim() || draft.stem_plain} /></p>{draft.options.length > 0 && <div>{draft.options.map((option, index) => <p key={`${option.key}-preview-${index}`}><b>{option.key || String.fromCharCode(65 + index)}.</b> <MathText text={option.text || "（空选项）"} /></p>)}</div>}</div>
                  {draft.formula_check ? <div className="formula-result"><div><strong>{draft.formula_check.status === "blocked" ? "检查未通过" : draft.formula_check.teacher_confirmed ? "教师已确认当前版本" : "自动检查通过，等待教师确认"}</strong><small>{new Date(draft.formula_check.checked_at).toLocaleString("zh-CN")} · {draft.formula_check.checked_by}</small></div>{draft.formula_check.issues.length > 0 ? <ul>{draft.formula_check.issues.map((issue, index) => <li className={issue.severity} key={`${issue.code}-${issue.field}-${index}`}><div><strong>{issue.severity === "blocking" ? "必须修正" : "复核提示"} · {formulaFieldLabels[issue.field] ?? issue.field}</strong><span>{issue.message}</span></div>{issue.excerpt && <code>{issue.excerpt}</code>}</li>)}</ul> : <p>未发现乱码、分隔符或 LaTeX 结构异常。</p>}</div> : <p className="formula-empty">编辑完成后先检查；检查通过并对照原页无误，再由教师确认当前内容版本。</p>}
                </section>
                <section className="structured-options"><header><strong>选项</strong><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft(invalidateFormulaCheck({ ...draft, options: [...draft.options, { key: String.fromCharCode(65 + draft.options.length), text: "" }] }))}>＋ 添加选项</button></header>{draft.options.map((option, index) => <div key={`${option.key}-${index}`}><input disabled={draft.status === "imported"} aria-label={`选项 ${index + 1} 编号`} value={option.key} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, options: draft.options.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value.toUpperCase() } : item) }))} /><textarea disabled={draft.status === "imported"} value={option.text} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, options: draft.options.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item) }))} /><button type="button" disabled={draft.status === "imported"} onClick={() => setDraft(invalidateFormulaCheck({ ...draft, options: draft.options.filter((_, itemIndex) => itemIndex !== index) }))}>×</button></div>)}</section>
                <div className="structured-fields"><label><span>参考答案</span><input disabled={draft.status === "imported"} value={draft.answer_value ?? ""} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, answer_value: event.target.value || null }))} /></label><label><span>解析方法</span><input disabled={draft.status === "imported"} value={draft.solution_method} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, solution_method: event.target.value }))} /></label><label><span>最终答案</span><input disabled={draft.status === "imported"} value={draft.final_answer ?? ""} onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, final_answer: event.target.value || null }))} /></label></div><label><span>自有解析步骤（每行一步）</span><textarea className="compact" disabled={draft.status === "imported"} value={draft.solution_steps.join("\n")} placeholder="不要复制原解析；在后续数学核验时独立编写" onChange={(event) => setDraft(invalidateFormulaCheck({ ...draft, solution_steps: event.target.value.split("\n") }))} /></label>
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

export default function ImportsPage() {
  return <AdminGuard><ImportsPageContent /></AdminGuard>;
}
