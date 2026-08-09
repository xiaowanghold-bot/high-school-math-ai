import Link from "next/link";

const chapters = [
  ["01", "集合与常用逻辑用语", "16 个知识点", "正在整理"],
  ["02", "一元二次函数、方程和不等式", "12 个知识点", "待开始"],
  ["03", "函数的概念与性质", "16 个知识点", "待开始"],
  ["04", "指数函数与对数函数", "20 个知识点", "待开始"],
  ["05", "三角函数", "26 个知识点", "待开始"],
];

export default function DashboardPage() {
  return (
    <div className="page-content">
      <section className="welcome-row">
        <div>
          <p className="eyebrow">2026 秋季 · 人教 A 版</p>
          <h1>上午好，开始准备下一节数学课。</h1>
          <p className="subtle">从教材章节进入，或者直接告诉 AI 这节课要解决什么问题。</p>
        </div>
        <div className="date-card"><span>阶段 1/6</span><strong>教案生成 MVP</strong><small>课程树与题库已联动</small></div>
      </section>

      <section className="quick-grid" aria-label="快捷操作">
        <Link href="/lesson-plans/new" className="quick-card accent-blue"><span>备</span><div><h2>生成一份教案</h2><p>按章节、课型和学情生成可编辑初稿</p></div><b>→</b></Link>
        <Link href="/search" className="quick-card accent-teal"><span>题</span><div><h2>搜索与挑选题目</h2><p>自然语言、知识点和公式混合检索</p></div><b>→</b></Link>
        <div className="quick-card accent-amber is-upcoming" aria-disabled="true"><span>卷</span><div><h2>智能组卷</h2><p>题库审核稳定后开放，当前阶段先完成备课与搜题</p></div><b>后续</b></div>
      </section>

      <section className="section-block">
        <div className="section-heading"><div><p className="eyebrow">教学进度</p><h2>必修第一册</h2></div><Link href="/curriculum">查看完整知识点树 →</Link></div>
        <div className="chapter-list">
          {chapters.map(([number, name, count, status], index) => (
            <article className={index === 0 ? "chapter active" : "chapter"} key={number}>
              <span className="chapter-number">{number}</span>
              <div><h3>{name}</h3><p>{count}</p></div>
              <span className="status-pill">{status}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="two-column">
        <div className="panel"><div className="section-heading compact"><h2>最近工作</h2><span className="panel-meta">暂无记录</span></div><div className="empty-state"><strong>还没有教案</strong><p>从上方入口生成第一份可编辑教案。</p><Link className="empty-action" href="/lesson-plans/new">新建教案</Link></div></div>
        <div className="panel"><div className="section-heading compact"><h2>题库质量</h2><span className="verified-dot">质量门禁运行中</span></div><dl className="metric-list"><div><dt>试点题目</dt><dd>35</dd></div><div><dt>独立验证通过</dt><dd>22</dd></div><div><dt>发现来源矛盾</dt><dd>4</dd></div></dl></div>
      </section>
    </div>
  );
}
