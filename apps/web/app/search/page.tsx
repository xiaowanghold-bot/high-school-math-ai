"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { MathText } from "../components/math-text";
import { ResizableColumns } from "../components/resizable-columns";
import { useToast } from "../components/toast-provider";
import { longTaskApiUrl } from "../components/api-url";
import { useAppRole } from "../components/role-provider";

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
  library_state: "active" | "removed";
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
  active: number;
  removed: number;
  by_review_status: Record<string, number>;
  by_verification_status: Record<string, number>;
  by_chapter: Record<string, number>;
  by_work_queue: Record<string, number>;
  by_module: Record<string, number>;
  publishable: number;
};

type SolutionResult = {
  explanation: { method: string; steps: string[]; final_answer: string };
};

type CurriculumSuggestion = {
  node_id: string;
  name: string;
  volume: string;
  chapter: string;
  section: string;
  confidence: number;
  reasons: string[];
};

type QuestionQuality = {
  question_id: string;
  current_curriculum: {
    volume: string | null;
    chapter: string | null;
    section: string | null;
    knowledge_point_ids: string[];
    knowledge_point_names: string[];
  };
  curriculum_suggestions: CurriculumSuggestion[];
  verification: {
    status: string;
    capability: "already_verified" | "rule_based" | "teacher_evidence_required";
    source_answer: string | null;
    computed_answer: string | null;
    method: string | null;
    details: string[];
  };
};

type CurriculumSearchItem = {
  node_id: string;
  code: string;
  name: string;
  node_type: string;
  volume: string;
  chapter: string | null;
  section: string | null;
  description: string;
  primary_competencies: string[];
  gaokao_priority: string;
  match_score: number;
};

const apiBase = "";
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

const workQueueShortcuts = [
  { label: "全部题目", key: "" },
  { label: "待教师审核", key: "teacher_review" },
  { label: "验证通过待确认", key: "verified_pending_teacher" },
  { label: "待公式校正", key: "formula_review" },
  { label: "待数学验算", key: "math_review" },
  { label: "来源矛盾", key: "source_conflict" },
  { label: "需要修改", key: "changes_requested" },
  { label: "当前可发布", key: "publishable" },
];

const moduleShortcuts = [
  { label: "全部模块", key: "" },
  { label: "集合与逻辑", key: "sets_logic" },
  { label: "函数与导数", key: "functions_derivatives" },
  { label: "三角函数", key: "trigonometry" },
  { label: "数列", key: "sequences" },
  { label: "平面向量", key: "vectors" },
  { label: "立体几何", key: "solid_geometry" },
  { label: "解析几何", key: "analytic_geometry" },
  { label: "计数原理", key: "counting" },
  { label: "统计与概率", key: "statistics_probability" },
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
  const { isAdmin, actorId } = useAppRole();
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Question[]>([]);
  const [total, setTotal] = useState(0);
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [chapter, setChapter] = useState("");
  const [verification, setVerification] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [module, setModule] = useState("");
  const [workQueue, setWorkQueue] = useState("");
  const [knowledgePointId, setKnowledgePointId] = useState("");
  const [listVersion, setListVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<QuestionDetail | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [detailMode, setDetailMode] = useState<"preview" | "edit">("preview");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const { auto: setMessage } = useToast();
  const [variantInstruction, setVariantInstruction] = useState("");
  const [variantDraftMode, setVariantDraftMode] = useState(false);
  const [quality, setQuality] = useState<QuestionQuality | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [verificationConclusion, setVerificationConclusion] = useState<"passed" | "inconsistent" | "inconclusive">("passed");
  const [computedAnswer, setComputedAnswer] = useState("");
  const [verificationSteps, setVerificationSteps] = useState("");
  const [independentlyChecked, setIndependentlyChecked] = useState(false);
  const [manualCatalogOpen, setManualCatalogOpen] = useState(false);
  const [curriculumQuery, setCurriculumQuery] = useState("");
  const [curriculumResults, setCurriculumResults] = useState<CurriculumSearchItem[]>([]);
  const [curriculumTotal, setCurriculumTotal] = useState(0);
  const [catalogSearching, setCatalogSearching] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);

  const searchUrl = useMemo(() => {
    const params = new URLSearchParams({ page_size: "50" });
    if (query) params.set("query", query);
    if (chapter) params.set("chapter", chapter);
    if (verification) params.set("verification_status", verification);
    if (reviewStatus) params.set("review_status", reviewStatus);
    if (module) params.set("module", module);
    if (workQueue) params.set("work_queue", workQueue);
    if (knowledgePointId) params.set("knowledge_point_id", knowledgePointId);
    params.set("usage_scope", isAdmin ? "admin" : "teacher");
    params.set("usage_owner_id", actorId);
    params.set("library_state", showRemoved ? "removed" : "active");
    return `${apiBase}/api/v1/questions?${params.toString()}`;
  }, [query, chapter, verification, reviewStatus, module, workQueue, knowledgePointId, showRemoved, isAdmin, actorId]);

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

  async function refreshQuality(questionId = selectedId) {
    if (!questionId) return;
    setQualityLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${questionId}/quality`);
      if (!response.ok) throw new Error(await errorText(response));
      const updated: QuestionQuality = await response.json();
      setQuality(updated);
      setComputedAnswer(updated.verification.computed_answer || "");
      setVerificationSteps(updated.verification.details.join("\n"));
      setIndependentlyChecked(false);
    } finally {
      setQualityLoading(false);
    }
  }

  useEffect(() => {
    loadStats().catch(() => setMessage("题库统计接口暂时不可用。"));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialQuery = params.get("q")?.trim() || "";
    const initialVerification = params.get("verification") || "";
    const initialReview = params.get("review") || "";
    const initialModule = params.get("module") || "";
    const initialQueue = params.get("queue") || "";
    const initialKnowledgePoint = params.get("knowledge_point") || "";
    if (initialQuery) { setQueryInput(initialQuery); setQuery(initialQuery); }
    if (initialVerification) setVerification(initialVerification);
    if (initialReview) setReviewStatus(initialReview);
    if (initialModule) setModule(initialModule);
    if (initialQueue) setWorkQueue(initialQueue);
    if (initialKnowledgePoint) setKnowledgePointId(initialKnowledgePoint);
    function receiveGlobalSearch(event: Event) {
      const keyword = String((event as CustomEvent).detail || "").trim();
      setQueryInput(keyword);
      setQuery(keyword);
    }
    window.addEventListener("math-ai:global-search", receiveGlobalSearch);
    return () => window.removeEventListener("math-ai:global-search", receiveGlobalSearch);
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
        const visibleItems: Question[] = payload.items;
        setItems(visibleItems);
        setTotal(payload.total);
        setSelectedId((current) => current && visibleItems.some((item: Question) => item.question_id === current) ? current : visibleItems[0]?.question_id ?? null);
      })
      .catch(() => active && setMessage("题库接口暂时不可用，请确认后端已启动。"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [searchUrl, listVersion, isAdmin]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setEditDraft(null);
      setQuality(null);
      return;
    }
    setDetailMode("preview");
    setVariantDraftMode(false);
    setDetail(null);
    setEditDraft(null);
    setQuality(null);
    setManualCatalogOpen(false);
    setCurriculumQuery("");
    setCurriculumResults([]);
    setCurriculumTotal(0);
    Promise.all([refreshDetail(selectedId), refreshQuality(selectedId)]).catch(() => setMessage("无法读取题目详情或质量工作区。"));
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
      await Promise.all([loadStats(), refreshQuality(selectedId)]);
      setListVersion((value) => value + 1);
      setMessage(result.verification_reset ? "修订已保存为新版本；数学内容发生变化，旧验证已自动失效。" : "修订已保存为新版本；题干、选项和答案未变化，验证状态保持不变。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "题目修订保存失败");
    } finally {
      setWorking(false);
    }
  }

  async function calculateVariantAnswer() {
    if (!editDraft?.stem_plain.trim()) return;
    setWorking(true);
    try {
      const optionText = editDraft.options.length
        ? `\n${editDraft.options.map((item) => `${item.key}. ${item.text}`).join("\n")}`
        : "";
      const response = await fetch(longTaskApiUrl("/api/v1/solutions/solve"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_text: `${editDraft.stem_plain}${optionText}`,
          solution_mode: "standard",
          teacher_instruction: "这是教师正在编写的变式题。请独立计算答案并给出可审核步骤；不要改写题干。",
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const result: SolutionResult = await response.json();
      setEditDraft({
        ...editDraft,
        answer_value: result.explanation.final_answer,
        final_answer: result.explanation.final_answer,
        solution_method: result.explanation.method,
        solution_steps: result.explanation.steps.join("\n"),
      });
      setMessage("DeepSeek 已独立计算并回填答案与解析草稿；请教师复核后再保存。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "DeepSeek 计算答案失败");
    } finally { setWorking(false); }
  }

  async function saveAsTeacherVariant() {
    if (!selectedId || !detail || !editDraft?.stem_plain.trim()) return;
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/teacher-variants`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_type: detail.question_type,
          ...editDraft,
          stem_latex: editDraft.stem_latex || null,
          solution_steps: editDraft.solution_steps.split("\n").map((item) => item.trim()).filter(Boolean),
          difficulty: detail.difficulty,
          teacher_id: actorId,
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const saved: QuestionDetail = await response.json();
      setItems((current) => [saved, ...current]);
      setSelectedId(saved.question_id);
      setVariantDraftMode(false);
      setMessage("变式已另存为你的私有题目；不会修改管理员维护的原题，正式共享前仍需管理员审核。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存私有变式失败");
    } finally { setWorking(false); }
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
    await Promise.all([refreshDetail(), refreshQuality(), loadStats()]);
    setListVersion((value) => value + 1);
    setMessage(decision === "approved" ? "审核已保存；发布门禁仍会独立检查。" : "审核结论已保存。" );
  }

  async function applyCurriculum(nodeId: string) {
    if (!selectedId) return;
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/quality/curriculum`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: nodeId, teacher_id: "owner_teacher" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setQuality(result.workspace);
      setManualCatalogOpen(false);
      await Promise.all([refreshDetail(selectedId), loadStats()]);
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "教材知识点应用失败");
    } finally {
      setWorking(false);
    }
  }

  async function searchCurriculum(searchValue = curriculumQuery) {
    setCatalogSearching(true);
    try {
      const params = new URLSearchParams({
        query: searchValue.trim(),
        node_type: "knowledge_point",
        limit: "30",
      });
      const response = await fetch(`${apiBase}/api/v1/curriculum/search?${params.toString()}`);
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setCurriculumResults(result.items);
      setCurriculumTotal(result.total);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "教材目录搜索失败");
    } finally {
      setCatalogSearching(false);
    }
  }

  function toggleManualCatalog() {
    const nextOpen = !manualCatalogOpen;
    setManualCatalogOpen(nextOpen);
    if (nextOpen && !curriculumResults.length) searchCurriculum("");
  }

  async function recordVerification() {
    if (!selectedId) return;
    const evidenceSteps = verificationSteps.split("\n").map((item) => item.trim()).filter(Boolean);
    setWorking(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/quality/verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conclusion: verificationConclusion,
          computed_answer: computedAnswer.trim(),
          evidence_steps: evidenceSteps,
          note: "教师在题目质量工作台提交独立核验记录",
          independently_checked: independentlyChecked,
          verifier_id: "owner_teacher",
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const result = await response.json();
      setQuality(result.workspace);
      setIndependentlyChecked(false);
      await Promise.all([refreshDetail(selectedId), loadStats()]);
      setListVersion((value) => value + 1);
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "独立核验记录保存失败");
    } finally {
      setWorking(false);
    }
  }

  async function checkPublish() {
    if (!selectedId) return;
    const response = await fetch(`${apiBase}/api/v1/questions/${selectedId}/publish`, { method: "POST" });
    const decision = await response.json();
    if (decision.allowed) {
      await Promise.all([refreshDetail(selectedId), loadStats()]);
      setListVersion((value) => value + 1);
    }
    setMessage(decision.allowed ? "全部门禁通过，题目已发布。" : `暂不可发布：${decision.blockers.map((item: string) => blockerLabels[item] ?? item).join("、")}`);
  }

  function startTeacherVariant() {
    if (!detail) return;
    const draft = draftFromDetail(detail);
    setEditDraft({
      ...draft,
      answer_value: "",
      solution_method: "教师自拟变式",
      solution_steps: "",
      final_answer: "",
      note: "基于母题创建的教师私人变式",
    });
    setVariantDraftMode(true);
    setDetailMode("edit");
    setMessage("已复制母题作为私人变式起点。请先自行修改题干或选项，再选择 AI 润色或计算答案。 ");
  }

  async function polishTeacherVariant() {
    if (!editDraft?.stem_plain.trim()) return;
    setWorking(true);
    try {
      const response = await fetch(longTaskApiUrl(`${apiBase}/api/v1/questions/teacher-variants/polish`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stem_plain: editDraft.stem_plain,
          stem_latex: editDraft.stem_latex || null,
          options: editDraft.options,
          instruction: variantInstruction.trim(),
          teacher_id: actorId,
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const polished: { stem_plain: string; stem_latex: string | null; options: EditDraft["options"]; warnings: string[] } = await response.json();
      setEditDraft({ ...editDraft, stem_plain: polished.stem_plain, stem_latex: polished.stem_latex || "", options: polished.options });
      setMessage(`DeepSeek 只润色了当前教师原稿，没有另行出题。${polished.warnings.join(" ")}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "题目润色失败");
    } finally {
      setWorking(false);
    }
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

  async function changeQuestionLibraryState(action: "remove" | "restore") {
    if (!selectedId) return;
    if (action === "remove" && !window.confirm("题目将移入回收站，不再参与搜索、组卷、教案和推荐；正文、图片、来源及审核历史均保留。继续吗？")) return;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/questions/library-state`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_ids: [selectedId], action, reason: action === "remove" ? "用户从题库审核移入回收站" : "用户从题库回收站恢复" }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      setSelectedId(null); setListVersion((value) => value + 1); await loadStats();
      setMessage(action === "remove" ? "题目已移入回收站，可随时恢复。" : "题目已恢复到正常题库。" );
    } catch (error) { setMessage(error instanceof Error ? error.message : "题目状态修改失败"); }
    finally { setWorking(false); }
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
        <div><p className="eyebrow">{isAdmin ? "智能搜题 · 题库管理台" : "智能搜题 · 教师使用台"}</p><h1>{isAdmin ? "先把每一道题变得可信。" : "从成型题库选题，并制作自己的变式。"}</h1><p className="subtle">{isAdmin ? "管理员修订题干、答案、解析和来源，并负责正式入库。" : "这里只展示已验证题目；修改会另存为私人变式，不会改变正式母题。"}</p></div>
        {isAdmin && <button className="primary-button" type="button" onClick={showImportStatus}>导入记录</button>}
      </section>


      {isAdmin && <section className="quality-strip" aria-label="题库质量概览">
        <div><span>试点题目</span><strong>{stats?.total ?? "—"}</strong><small>本地私有题库</small></div>
        <div><span>待教师审核</span><strong>{pending}</strong><small>逐题确认</small></div>
        <div className="metric-passed"><span>独立验证通过</span><strong>{verifiedCount}</strong><small>含计算证据</small></div>
        <div><span>待公式校正</span><strong>{formulaIssues}</strong><small>禁止直接展示</small></div>
        <div className={sourceIssues ? "metric-alert" : ""}><span>来源矛盾</span><strong>{sourceIssues}</strong><small>需重点复核</small></div>
        <div><span>当前可发布</span><strong>{stats?.publishable ?? 0}</strong><small>全部门禁通过</small></div>
      </section>}

      <form className="question-filters" onSubmit={submitSearch}>
        <label className="search-field"><span>⌕</span><input aria-label="搜索题目" value={queryInput} onChange={(event) => { setQueryInput(event.target.value); setKnowledgePointId(""); }} placeholder="搜索题干、章节或来源，例如：集合、椭圆、概率" /></label>
        <select value={chapter} onChange={(event) => { setChapter(event.target.value); setModule(""); }} aria-label="按章节筛选"><option value="">全部章节</option>{Object.keys(stats?.by_chapter ?? {}).map((item) => <option key={item} value={item}>{item}</option>)}</select>
        {isAdmin && <select value={verification} onChange={(event) => { setVerification(event.target.value); setWorkQueue(""); }} aria-label="按验证状态筛选"><option value="">全部质量状态</option><option value="passed">验证通过</option><option value="needs_formula_review">待公式校正</option><option value="needs_math_review">待数学验算</option><option value="source_inconsistency_detected">来源存在矛盾</option></select>}
        {isAdmin && <select value={reviewStatus} onChange={(event) => { setReviewStatus(event.target.value); setWorkQueue(""); }} aria-label="按教师审核状态筛选"><option value="">全部审核状态</option><option value="pending">待教师审核</option><option value="approved">教师已通过</option><option value="changes_requested">需要修改</option><option value="rejected">已拒绝</option></select>}
        <button className="primary-button" type="submit">检索</button>
      </form>

      {isAdmin && <section className="review-shortcuts-panel" aria-label="题库审核快速入口">
        <nav className="module-shortcuts work-queue-shortcuts" aria-label="按审核队列快速筛选"><span>审核队列</span>{workQueueShortcuts.map((item) => {
          const active = item.key ? workQueue === item.key : !workQueue && !reviewStatus && !verification;
          const count = item.key ? stats?.by_work_queue?.[item.key] ?? 0 : stats?.total ?? 0;
          return <button className={active ? "active" : ""} key={item.label} type="button" onClick={() => { setWorkQueue(item.key); setReviewStatus(""); setVerification(""); }}>{item.label}<small>{count}</small></button>;
        })}</nav>
        <nav className="module-shortcuts" aria-label="按数学模块快速筛选"><span>知识模块</span>{moduleShortcuts.map((item) => {
          const active = item.key ? module === item.key : !module && !chapter;
          const count = item.key ? stats?.by_module?.[item.key] ?? 0 : stats?.total ?? 0;
          return <button className={active ? "active" : ""} key={item.label} type="button" onClick={() => { setModule(item.key); setChapter(""); }}>{item.label}<small>{count}</small></button>;
        })}</nav>
      </section>}

      <ResizableColumns className="question-layout" storageKey="question-search" initialLeftPercent={42} leftMin={320} rightMin={420} collapse="wide" label="调整题目列表与题目详情宽度">
        <section className="question-results" aria-label="题目列表">
          <div className="results-heading"><strong>{loading ? "正在检索…" : `${total} 道题`}</strong>{isAdmin && <button type="button" onClick={() => { setShowRemoved((current) => !current); setSelectedId(null); }}>{showRemoved ? "返回正常题库" : `题目回收站 ${stats?.removed ?? 0}`}</button>}</div>
          <div className="result-list">
            {items.map((item, index) => <button className={selectedId === item.question_id ? "question-row selected" : "question-row"} type="button" key={item.question_id} onClick={() => setSelectedId(item.question_id)}><span className="question-index">{String(index + 1).padStart(2, "0")}</span><span className="question-main"><span className="question-tags"><em>{item.question_type === "single_choice" ? "单选题" : "解答题"}</em><i className={`quality-tag ${item.verification_status}`}>{verificationLabels[item.verification_status] ?? item.verification_status}</i></span><b>{item.stem_plain}</b><small>{item.chapter} · 难度 {item.difficulty}/5</small></span><span className="review-mark">{reviewLabels[item.review_status] ?? item.review_status}</span></button>)}
            {!loading && items.length === 0 && <div className="empty-state"><strong>没有匹配题目</strong><p>换一个关键词或清空筛选条件。</p></div>}
          </div>
        </section>

        <aside className="question-detail" aria-label="题目审核详情">
          {!detail && <div className="empty-state"><strong>请选择一道题</strong><p>右侧将显示来源、答案与审核动作。</p></div>}
          {detail && editDraft && <>
            <header className="detail-heading"><div><p>{detail.volume}{detail.section ? ` · ${detail.section}` : ""}</p><h2>{detail.chapter}</h2></div><div className="detail-heading-tools">{detail.question_id.startsWith("q_variant_") && <span>当前教师私有</span>}<span>难度 {detail.difficulty}</span><span>修订 {detail.revision_count}</span>{isAdmin && <button type="button" onClick={() => changeQuestionLibraryState(detail.library_state === "removed" ? "restore" : "remove")}>{detail.library_state === "removed" ? "恢复题目" : "移入回收站"}</button>}</div></header>
            <div className="detail-mode-tabs"><button className={detailMode === "preview" ? "active" : ""} type="button" onClick={() => setDetailMode("preview")}>内容预览</button><button className={detailMode === "edit" ? "active" : ""} type="button" onClick={() => setDetailMode("edit")}>编辑与配图</button></div>

            {detailMode === "preview" ? <>
              {detail.verification_status === "passed" ? <div className="verification-passed"><strong>独立验证通过</strong><p>答案已由规则模块独立计算；教师修订数学内容后，本结论会自动失效。</p></div> : <div className="formula-warning"><strong>{verificationLabels[detail.verification_status]}</strong><p>{detail.raw.verification?.details?.[0] || "该题需要重新校正或独立验算后才能审核发布。"}</p></div>}
              <div className="stem-card"><p><MathText text={detail.raw.stem?.latex || detail.stem_plain} /></p></div>
              {renderImages("stem")}
              {!!detail.raw.options?.length && <ol className="option-list">{detail.raw.options.map((option) => <li key={option.key}><b>{option.key}</b><span><MathText text={option.latex || option.plain_text || "选项内容需重建"} /></span></li>)}</ol>}
              <div className="answer-line"><span>{detail.verification_status === "passed" ? "独立验证答案" : "当前答案"}</span><strong>{detail.raw.verification?.computed_answer || detail.answer_value || "待独立求解"}</strong></div>
              {!!detail.raw.solutions?.[0]?.steps_latex?.length && <div className="solution-card"><header><span>自有解析草稿</span><strong>{detail.raw.solutions[0].method}</strong></header><ol>{detail.raw.solutions[0].steps_latex?.map((step, index) => <li key={index}><MathText text={step} /></li>)}</ol><small>需由教师确认后才可作为正式解析</small></div>}
              {renderImages("solution")}
              {isAdmin && <details className="question-quality-workspace" open={detail.verification_status !== "passed" || !detail.knowledge_point_ids.length}>
                <summary><span><strong>教材映射与数学核验</strong><small>建议只供参考，应用与通过均由教师确认</small></span><i>{qualityLoading ? "读取中" : detail.verification_status === "passed" ? "已核验" : "待处理"}</i></summary>
                {quality && <div className="quality-workspace-grid">
                  <section className="curriculum-quality-panel">
                    <header><div><strong>教材知识点</strong><span>人教 A 版</span></div><small>当前：{quality.current_curriculum.section || quality.current_curriculum.chapter || "尚未映射"}</small></header>
                    {!!quality.current_curriculum.knowledge_point_ids.length && <p className="mapping-current">已关联：{quality.current_curriculum.knowledge_point_names.join("、")}</p>}
                    <div className="curriculum-suggestions">
                      {quality.curriculum_suggestions.map((suggestion) => <article className="curriculum-suggestion" key={suggestion.node_id}>
                        <div><strong>{suggestion.name}</strong><span>{Math.round(suggestion.confidence * 100)}% 匹配</span></div>
                        <p>{suggestion.chapter} · {suggestion.section}</p>
                        <small>{suggestion.reasons.join("；")}</small>
                        <button type="button" disabled={working || quality.current_curriculum.knowledge_point_ids.includes(suggestion.node_id)} onClick={() => applyCurriculum(suggestion.node_id)}>{quality.current_curriculum.knowledge_point_ids.includes(suggestion.node_id) ? "当前知识点" : "应用此知识点"}</button>
                      </article>)}
                      {!quality.curriculum_suggestions.length && <div className="quality-empty"><strong>暂未找到可靠建议</strong><span>可以使用下面的完整目录搜索进行人工映射。</span></div>}
                    </div>
                    <button className="manual-catalog-toggle" type="button" onClick={toggleManualCatalog}>{manualCatalogOpen ? "收起目录搜索" : "从教材目录选择"}</button>
                    {manualCatalogOpen && <div className="manual-catalog-panel">
                      <form onSubmit={(event) => { event.preventDefault(); searchCurriculum(); }}>
                        <input aria-label="搜索教材知识点" value={curriculumQuery} onChange={(event) => setCurriculumQuery(event.target.value)} placeholder="输入知识点、章节、题型或编号" />
                        <button type="submit" disabled={catalogSearching}>{catalogSearching ? "搜索中…" : "搜索"}</button>
                      </form>
                      <p>找到 {curriculumTotal} 个知识点{curriculumTotal > curriculumResults.length ? `，显示前 ${curriculumResults.length} 个` : ""}</p>
                      <div className="manual-catalog-results">
                        {curriculumResults.map((item) => <article key={item.node_id}>
                          <div><strong>{item.name}</strong><span>{item.code}</span></div>
                          <p>{item.volume} · {item.chapter} · {item.section}</p>
                          <small>{item.description || item.primary_competencies.join("、")}</small>
                          <button type="button" disabled={working || quality.current_curriculum.knowledge_point_ids.includes(item.node_id)} onClick={() => applyCurriculum(item.node_id)}>{quality.current_curriculum.knowledge_point_ids.includes(item.node_id) ? "当前知识点" : "选择"}</button>
                        </article>)}
                        {!catalogSearching && !curriculumResults.length && <div className="quality-empty"><strong>没有匹配知识点</strong><span>尝试缩短关键词，例如将“函数的单调递增”改为“单调性”。</span></div>}
                      </div>
                    </div>}
                  </section>

                  <section className="verification-quality-panel">
                    <header><div><strong>独立数学核验</strong><span>{quality.verification.capability === "teacher_evidence_required" ? "教师证据" : quality.verification.capability === "rule_based" ? "规则可验" : "已有证据"}</span></div><small>{verificationLabels[quality.verification.status] ?? quality.verification.status}</small></header>
                    {quality.verification.status === "passed" ? <div className="verification-evidence">
                      <strong>独立答案：{quality.verification.computed_answer || "已验证"}</strong>
                      <p>{quality.verification.details.join("；") || "验证证据已保存；数学内容再次修订后会自动失效。"}</p>
                    </div> : <div className="verification-evidence-form">
                      <label><span>核验结论</span><select value={verificationConclusion} onChange={(event) => setVerificationConclusion(event.target.value as "passed" | "inconsistent" | "inconclusive")}><option value="passed">答案与独立结果一致</option><option value="inconsistent">发现当前答案不一致</option><option value="inconclusive">证据不足，继续复核</option></select></label>
                      <label><span>独立求得的答案</span><input value={computedAnswer} onChange={(event) => setComputedAnswer(event.target.value)} placeholder="不要照抄当前答案，填写独立计算结果" /></label>
                      <label><span>推导证据（每行一步）</span><textarea value={verificationSteps} onChange={(event) => setVerificationSteps(event.target.value)} placeholder={"写出关键推导，例如：\n1. 由定义域得 x > 0\n2. 求导并判断单调区间"} /></label>
                      <label className="independent-check"><input type="checkbox" checked={independentlyChecked} onChange={(event) => setIndependentlyChecked(event.target.checked)} /><span>我确认以上答案与推导是独立验算所得，而非直接复制来源解析。</span></label>
                      <p className="verification-rule">只有独立答案与当前答案一致时才能通过；不一致会自动标记为“来源矛盾”。</p>
                      <button type="button" disabled={working || !verificationSteps.trim() || !independentlyChecked} onClick={recordVerification}>{working ? "保存中…" : "保存核验记录"}</button>
                    </div>}
                  </section>
                </div>}
                {!quality && !qualityLoading && <p className="quality-load-error">质量工作区暂不可用，请确认接口已启动后重试。</p>}
              </details>}
              <div className="question-editor-form">
                <div className="editor-safety-note"><strong>教师先写，AI 后润色</strong><span>系统只复制母题作为编辑起点，不会替教师直接生成新题。教师修改后的内容归当前教师私有。</span></div>
                <div className="question-editor-actions"><span>{detail.verification_status === "passed" ? "进入编辑器后，请先修改题干、条件、数值或选项，再使用 AI 润色和答案计算。" : "该题尚未验证，暂不能作为变式母题。"}</span><button className="primary" type="button" disabled={working || detail.verification_status !== "passed"} onClick={startTeacherVariant}>开始编写私人变式</button></div>
              </div>
            </> : <div className="question-editor-form">
              <div className="editor-safety-note"><strong>{variantDraftMode ? "正在编写私人变式" : isAdmin ? "修改即生成新版本" : "编辑自己的变式"}</strong><span>{variantDraftMode ? "教师是这份变式的所有者；AI 只润色或计算，保存后不会覆盖正式母题。" : isAdmin ? "题干、选项、答案或题干图变化会自动退回数学验算；来源原文不会被覆盖。" : "这里的修改不会覆盖正式母题；可让 DeepSeek 计算答案后另存为私人变式。"}</span></div>
              <label><span>题干正文</span><textarea className="large" value={editDraft.stem_plain} onChange={(event) => setEditDraft({ ...editDraft, stem_plain: event.target.value })} /></label>
              <label><span>LaTeX 题干（可选）</span><textarea value={editDraft.stem_latex} onChange={(event) => setEditDraft({ ...editDraft, stem_latex: event.target.value })} placeholder="可直接输入含 $...$ 的数学公式；留空则显示题干正文" /></label>
              <label><span>AI 润色要求（可选）</span><input value={variantInstruction} onChange={(event) => setVariantInstruction(event.target.value)} placeholder="例如：只规范语言和 LaTeX，不改变题目条件" /></label>
              {isAdmin && renderImages("stem", true)}
              <section className="option-editor"><header><strong>选项</strong><button type="button" onClick={() => setEditDraft({ ...editDraft, options: [...editDraft.options, { key: String.fromCharCode(65 + editDraft.options.length), text: "" }] })}>＋ 添加选项</button></header>{editDraft.options.map((option, index) => <div key={`${option.key}-${index}`}><input className="option-key-input" aria-label={`选项 ${index + 1} 编号`} value={option.key} onChange={(event) => setEditDraft({ ...editDraft, options: editDraft.options.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item) })} /><textarea value={option.text} onChange={(event) => setEditDraft({ ...editDraft, options: editDraft.options.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item) })} /><button type="button" aria-label={`删除选项 ${option.key}`} onClick={() => setEditDraft({ ...editDraft, options: editDraft.options.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>)}</section>
              <div className="question-editor-two"><label><span>参考答案</span><input value={editDraft.answer_value} onChange={(event) => setEditDraft({ ...editDraft, answer_value: event.target.value })} /></label><label><span>解析方法</span><input value={editDraft.solution_method} onChange={(event) => setEditDraft({ ...editDraft, solution_method: event.target.value })} /></label></div>
              <label><span>解析步骤（每行一步）</span><textarea className="large" value={editDraft.solution_steps} onChange={(event) => setEditDraft({ ...editDraft, solution_steps: event.target.value })} /></label>
              <label><span>最终答案</span><input value={editDraft.final_answer} onChange={(event) => setEditDraft({ ...editDraft, final_answer: event.target.value })} /></label>
              {isAdmin && renderImages("solution", true)}
              <label><span>修订说明</span><input value={editDraft.note} onChange={(event) => setEditDraft({ ...editDraft, note: event.target.value })} /></label>
              <div className="question-editor-actions"><button type="button" onClick={() => { setEditDraft(draftFromDetail(detail)); setVariantDraftMode(false); setDetailMode("preview"); }}>放弃未保存修改</button><button type="button" disabled={working || editDraft.stem_plain.trim().length < 5} onClick={polishTeacherVariant}>{working ? "处理中…" : "用 DeepSeek 润色原稿"}</button><button type="button" disabled={working || !editDraft.stem_plain.trim()} onClick={calculateVariantAnswer}>{working ? "计算中…" : "用 DeepSeek 计算答案"}</button><button className="primary" type="button" disabled={working || !editDraft.stem_plain.trim()} onClick={variantDraftMode || (!isAdmin && !detail.question_id.startsWith("q_variant_")) ? saveAsTeacherVariant : saveRevision}>{working ? "保存中…" : variantDraftMode ? "存入我的私人题库" : isAdmin ? "保存为新修订" : detail.question_id.startsWith("q_variant_") ? "保存我的变式" : "存入我的私人题库"}</button></div>
            </div>}

            {isAdmin && <><dl className="source-meta"><div><dt>来源文件</dt><dd>{detail.source_document}</dd></div><div><dt>定位页</dt><dd>{detail.source_page_start ?? "—"}{detail.source_page_end && detail.source_page_end !== detail.source_page_start ? `–${detail.source_page_end}` : ""}</dd></div><div><dt>审核状态</dt><dd>{reviewLabels[detail.review_status] ?? detail.review_status}</dd></div></dl><div className="gate-list"><h3>发布门禁</h3>{detail.publication_blockers.map((item) => <span key={item}>○ {blockerLabels[item] ?? item}</span>)}</div><div className="review-actions"><button type="button" className="approve" disabled={detail.verification_status !== "passed"} onClick={() => review("approved")}>教师通过</button><button type="button" onClick={() => review("changes_requested")}>需要修改</button><button type="button" className="reject" onClick={() => review("rejected")}>拒绝入库</button></div><button className="publish-check" type="button" onClick={checkPublish}>检查是否可以发布</button></>}
          </>}
        </aside>
      </ResizableColumns>
    </div>
  );
}
