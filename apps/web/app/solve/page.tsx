"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { MathText } from "../components/math-text";
import { ResizableColumns } from "../components/resizable-columns";
import { useToast } from "../components/toast-provider";
import { longTaskApiUrl } from "../components/api-url";
import "./solver.css";

type QuestionSample = { question_id: string; stem_plain: string; chapter: string | null; difficulty: number };
type SolutionResult = {
  question_text: string;
  solution_mode: "standard" | "alternative";
  explanation: { method: string; steps: string[]; final_answer: string };
  knowledge_points: string[];
  common_mistakes: string[];
  teaching_notes: string[];
  confidence_status: "program_verified" | "model_reviewed" | "teacher_review_required";
  verification_evidence: string[];
  model: string;
  mode: "verified_bank" | "live_ai";
  matched_question_id: string | null;
  match_score: number | null;
  alternative_available: boolean;
  warnings: string[];
};

const confidenceLabels = { program_verified: "已程序验证", model_reviewed: "模型复核", teacher_review_required: "仅供教师复核" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}

export default function SolvePage() {
  const [questionText, setQuestionText] = useState("");
  const [instruction, setInstruction] = useState("");
  const [samples, setSamples] = useState<QuestionSample[]>([]);
  const [result, setResult] = useState<SolutionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const { auto: setMessage } = useToast();

  useEffect(() => {
    fetch("/api/v1/questions?verification_status=passed&page_size=3")
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((payload) => setSamples(payload.items ?? []))
      .catch(() => setSamples([]));
  }, []);

  async function solve(solutionMode: "standard" | "alternative") {
    if (questionText.trim().length < 5) { setMessage("请先输入完整题目，至少 5 个字符。"); return; }
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(longTaskApiUrl("/api/v1/solutions/solve"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_text: questionText, solution_mode: solutionMode, teacher_instruction: instruction }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      setResult(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "解题失败，请稍后重试。");
    } finally { setBusy(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void solve("standard"); }

  return (
    <div className="page-content solver-workspace">
      <section className="page-title solver-title">
        <div><p className="eyebrow">解题助手 · 教师复核优先</p><h1>把答案、依据和风险放在一起看。</h1><p className="subtle">优先匹配独立验证题库；题库外答案会明确标记为待教师复核。</p></div>
        <div className="solver-safety-badge"><strong>三档可信度</strong><span>程序验证 · 模型复核 · 教师复核</span></div>
      </section>


      <ResizableColumns className="solver-layout" storageKey="solver-workspace" initialLeftPercent={36} leftMin={260} rightMin={420} collapse="compact" label="调整题目输入与解答结果宽度">
        <aside className="solver-input-panel">
          <form onSubmit={submit}>
            <header><span>01</span><div><strong>输入题目</strong><small>支持正文与 $...$ LaTeX 公式</small></div></header>
            <label className="solver-question-field"><span>题目正文</span><textarea value={questionText} onChange={(event) => setQuestionText(event.target.value)} placeholder="粘贴一道完整高中数学题目，包括必要条件和选项……" /><small>{questionText.length} / 30000</small></label>
            <label className="solver-instruction-field"><span>教师补充要求（可选）</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：使用函数单调性解答，并指出学生常见错误" /></label>
            <button className="solver-submit" disabled={busy || questionText.trim().length < 5} type="submit">{busy ? "正在核对条件与推导…" : "生成标准解法"}</button>
          </form>

          <section className="solver-samples">
            <header><strong>从已验证题目体验</strong><span>{samples.length} 道</span></header>
            {samples.map((sample, index) => <button type="button" key={sample.question_id} onClick={() => { setQuestionText(sample.stem_plain); setResult(null); setMessage(null); }}><b>{String(index + 1).padStart(2, "0")}</b><span><MathText text={sample.stem_plain} /><small>{sample.chapter || "高中数学"} · 难度 {sample.difficulty}</small></span></button>)}
            {!samples.length && <p>正在读取已验证题库……</p>}
          </section>
        </aside>

        <main className="solver-result-panel">
          {!result ? <div className="solver-empty"><span>解</span><h2>答案不是终点，证据才是。</h2><p>输入题目后，这里会显示解法步骤、最终答案、知识点、易错点和可信度依据。</p><ol><li>完整录入题目条件</li><li>查看每一步推导</li><li>根据可信度标记完成教师复核</li></ol></div> : <>
            <header className="solver-result-heading"><div><p>{result.solution_mode === "alternative" ? "第二种解法" : "标准解法"}</p><h2>{result.explanation.method}</h2></div><span className={`solver-confidence ${result.confidence_status}`}>{confidenceLabels[result.confidence_status]}</span></header>
            <section className="solver-question-preview"><span>当前题目</span><p><MathText text={result.question_text} /></p></section>
            {result.warnings.map((warning) => <p className="solver-warning" key={warning}>{warning}</p>)}
            <section className="solver-solution-card">
              <header><div><span>解题过程</span><strong>{result.explanation.steps.length} 个关键步骤</strong></div>{result.matched_question_id && <Link href="/search">查看题库原题 →</Link>}</header>
              <ol>{result.explanation.steps.map((step, index) => <li key={`${index}-${step}`}><b>{String(index + 1).padStart(2, "0")}</b><p><MathText text={step} /></p></li>)}</ol>
              <footer><span>最终答案</span><strong><MathText text={result.explanation.final_answer} /></strong></footer>
            </section>
            <div className="solver-insight-grid">
              <section><header><span>知</span><strong>知识点</strong></header>{result.knowledge_points.length ? result.knowledge_points.map((item) => <p key={item}>{item}</p>) : <p>待教师补充标签</p>}</section>
              <section><header><span>错</span><strong>常见错误</strong></header>{result.common_mistakes.map((item) => <p key={item}>{item}</p>)}</section>
              <section><header><span>证</span><strong>可信度依据</strong></header>{result.verification_evidence.map((item) => <p key={item}>{item}</p>)}</section>
              <section><header><span>讲</span><strong>教学提示</strong></header>{result.teaching_notes.map((item) => <p key={item}>{item}</p>)}</section>
            </div>
            <footer className="solver-result-actions"><div><span>来源：{result.mode === "verified_bank" ? "独立验证私有题库" : result.model}</span>{result.match_score && <small>题干匹配度 {Math.round(result.match_score * 100)}%</small>}</div><button type="button" disabled={busy || !result.alternative_available} onClick={() => void solve("alternative")}>{busy ? "生成中…" : result.alternative_available ? "换一种解法" : "暂无第二种已验证解法"}</button></footer>
          </>}
        </main>
      </ResizableColumns>
    </div>
  );
}
