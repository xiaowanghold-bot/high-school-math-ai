"use client";

import { useEffect, useState } from "react";

type CurriculumNode = {
  node_id: string;
  parent_id: string | null;
  node_type: string;
  code: string;
  name: string;
  primary_competencies: string[];
  gaokao_priority: string;
  children: CurriculumNode[];
};

const apiBase = "";

export default function CurriculumPage() {
  const [root, setRoot] = useState<CurriculumNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/api/v1/curriculum/tree`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(setRoot)
      .catch(() => setError("课程接口暂时不可用，请先启动 FastAPI。"));
  }, []);

  const chapters = root?.children ?? [];
  return (
    <div className="page-content">
      <section className="page-title"><div><p className="eyebrow">教材备课</p><h1>人教 A 版 · 必修第一册</h1><p className="subtle">按章节、节和知识点进入备课工作区。</p></div><button className="primary-button" type="button">从当前进度备课</button></section>
      {error && <div className="notice warning">{error}</div>}
      {!root && !error && <div className="notice">正在读取知识点树…</div>}
      <div className="curriculum-grid">
        {chapters.map((chapter) => (
          <article className="curriculum-card" key={chapter.node_id}>
            <header><span>{chapter.code.padStart(2, "0")}</span><div><h2>{chapter.name}</h2><p>{chapter.children.length} 节</p></div></header>
            <ul>{chapter.children.map((section) => <li key={section.node_id}><div><b>{section.code}</b><span>{section.name}</span></div><small>{section.children.length} 个知识点</small></li>)}</ul>
          </article>
        ))}
      </div>
    </div>
  );
}
