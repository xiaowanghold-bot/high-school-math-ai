"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminGuard } from "../../components/admin-guard";

type RouteStatus = {
  feature: string;
  label: string;
  configured_mode: string;
  effective_provider: string;
  model: string;
  ready: boolean;
  note: string;
};

type RunStats = {
  total_runs: number;
  succeeded_runs: number;
  failed_runs: number;
  success_rate: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  average_latency_ms: number;
  estimated_cost_usd: number | null;
};

type FeatureStats = {
  feature: string;
  label: string;
  total_runs: number;
  succeeded_runs: number;
  failed_runs: number;
  average_latency_ms: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
};

type ModelRun = {
  run_id: string;
  feature_label: string;
  provider: string;
  model: string;
  prompt_version: string;
  status: "succeeded" | "failed";
  total_tokens: number;
  cached_input_tokens: number;
  latency_ms: number;
  estimated_cost_usd: number | null;
  error_category: string | null;
  error_message: string | null;
  created_at: string;
};

type Dashboard = {
  api_configured: boolean;
  model: string;
  reasoning_effort: string;
  timeout_seconds: number;
  pricing_configured: boolean;
  pricing_note: string;
  routes: RouteStatus[];
  stats: RunStats;
  feature_stats: FeatureStats[];
  recent_runs: ModelRun[];
};

const providerLabels: Record<string, string> = {
  openai: "外部模型",
  local_template: "本地教案模板",
  local_rule: "本地诊断规则",
  verified_answer: "题库已验证答案",
  unavailable: "尚不可用",
};

function number(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function duration(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} 秒` : `${ms} 毫秒`;
}

function ModelsDashboard() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/v1/admin/model-operations?limit=60", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setData(await response.json());
    } catch {
      setError("模型运行数据暂时无法读取，请确认 API 已启动。 ");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return <div className="page-content model-ops-page">
    <section className="page-title model-ops-title">
      <div><p className="eyebrow">平台管理 · 模型可观测性</p><h1>模型运行中心</h1><p className="subtle">集中查看能力路由、运行质量、耗时和 token 用量；运行记录不保存题目正文、提示词或 API Key。</p></div>
      <button className="review-secondary-button" type="button" onClick={() => void load()} disabled={loading}>{loading ? "刷新中…" : "刷新数据"}</button>
    </section>

    {error && <div className="notice warning">{error}</div>}
    {!data && loading && <div className="model-ops-loading">正在读取模型运行状态…</div>}
    {data && <>
      <section className={`model-ops-readiness ${data.api_configured ? "ready" : "local"}`}>
        <span>{data.api_configured ? "已" : "本"}</span>
        <div><strong>{data.api_configured ? "外部模型连接已配置" : "当前以本地能力为主"}</strong><p>{data.api_configured ? `默认模型 ${data.model} · 推理强度 ${data.reasoning_effort} · 超时 ${data.timeout_seconds} 秒` : "未检测到 API Key；教案与部分变式继续使用本地确定性能力，OCR 暂不可用。"}</p></div>
        <em>{data.api_configured ? "连接就绪" : "安全降级"}</em>
      </section>

      <section className="model-ops-metrics" aria-label="模型运行指标">
        <article><span>累计运行</span><strong>{number(data.stats.total_runs)}</strong><small>全部能力</small></article>
        <article><span>成功率</span><strong>{data.stats.total_runs ? `${data.stats.success_rate}%` : "—"}</strong><small>{data.stats.failed_runs} 次失败</small></article>
        <article><span>平均耗时</span><strong>{data.stats.total_runs ? duration(data.stats.average_latency_ms) : "—"}</strong><small>端到端记录</small></article>
        <article><span>Token 用量</span><strong>{number(data.stats.total_tokens)}</strong><small>缓存输入 {number(data.stats.cached_input_tokens)}</small></article>
        <article><span>估算成本</span><strong>{data.stats.estimated_cost_usd === null ? "—" : `$${data.stats.estimated_cost_usd.toFixed(4)}`}</strong><small>{data.pricing_note}</small></article>
      </section>

      <div className="model-ops-grid">
        <section className="model-ops-panel">
          <header><div><p>能力路由</p><h2>当前每项功能实际走哪条路径</h2></div><span>{data.routes.filter((route) => route.ready).length}/{data.routes.length} 可用</span></header>
          <div className="model-route-list">
            {data.routes.map((route) => <article key={route.feature}>
              <span className={route.ready ? "ready" : "blocked"}>{route.ready ? "✓" : "!"}</span>
              <div><strong>{route.label}</strong><small>{route.note}</small></div>
              <p><b>{providerLabels[route.effective_provider] ?? route.effective_provider}</b><small>{route.model}</small></p>
            </article>)}
          </div>
        </section>

        <section className="model-ops-panel">
          <header><div><p>能力分布</p><h2>按功能查看运行质量</h2></div><span>全量历史</span></header>
          <div className="model-feature-list">
            {data.feature_stats.map((feature) => <article key={feature.feature}>
              <div><strong>{feature.label}</strong><small>{feature.total_runs ? `${feature.succeeded_runs} 成功 · ${feature.failed_runs} 失败` : "尚无运行记录"}</small></div>
              <p><b>{number(feature.total_runs)}</b><small>{feature.total_runs ? `${duration(feature.average_latency_ms)} · ${number(feature.total_tokens)} token` : "等待首次调用"}</small></p>
            </article>)}
          </div>
        </section>
      </div>

      <section className="model-ops-panel model-run-panel">
        <header><div><p>审计记录</p><h2>最近运行</h2></div><span>最近 {data.recent_runs.length} 条</span></header>
        {data.recent_runs.length === 0 ? <div className="model-run-empty"><strong>还没有运行记录</strong><p>生成一份教案、创建一道变式或调用解题助手后，这里会自动出现记录。</p></div> :
          <div className="model-run-table-wrap"><table className="model-run-table"><thead><tr><th>状态</th><th>功能</th><th>适配器 / 模型</th><th>Token</th><th>耗时</th><th>时间</th></tr></thead><tbody>
            {data.recent_runs.map((run) => <tr key={run.run_id}>
              <td><span className={`run-status ${run.status}`}>{run.status === "succeeded" ? "成功" : "失败"}</span></td>
              <td><strong>{run.feature_label}</strong><small>{run.prompt_version}</small>{run.error_message && <em title={run.error_message}>{run.error_category}：{run.error_message}</em>}</td>
              <td><strong>{providerLabels[run.provider] ?? run.provider}</strong><small>{run.model}</small></td>
              <td><strong>{number(run.total_tokens)}</strong><small>{run.cached_input_tokens ? `缓存 ${number(run.cached_input_tokens)}` : "—"}</small></td>
              <td>{duration(run.latency_ms)}</td>
              <td>{new Date(run.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
            </tr>)}
          </tbody></table></div>}
      </section>
    </>}
  </div>;
}

export default function ModelsPage() {
  return <AdminGuard><ModelsDashboard /></AdminGuard>;
}
