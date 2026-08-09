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
  status: string;
  children: CurriculumNode[];
};

const apiBase = "";

export default function CurriculumPage() {
  const [root, setRoot] = useState<CurriculumNode | null>(null);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/api/v1/curriculum/tree`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((tree: CurriculumNode) => {
        setRoot(tree);
        const firstVolume = tree.node_type === "volume" ? tree : tree.children.find((item) => item.node_type === "volume");
        if (firstVolume) setSelectedVolumeId(firstVolume.node_id);
      })
      .catch(() => setError("课程接口暂时不可用，请先启动 FastAPI。"));
  }, []);

  const volumes = root ? (root.node_type === "volume" ? [root] : root.children.filter((item) => item.node_type === "volume")) : [];
  const selectedVolume = volumes.find((item) => item.node_id === selectedVolumeId) ?? volumes[0];
  const chapters = selectedVolume?.children ?? [];
  const knowledgePointCount = chapters.reduce((chapterTotal, chapter) => chapterTotal + chapter.children.reduce((sectionTotal, section) => sectionTotal + section.children.length, 0), 0);
  return (
    <div className="page-content">
      <section className="page-title"><div><p className="eyebrow">教材备课</p><h1>人教 A 版 · {selectedVolume?.name || "课程目录"}</h1><p className="subtle">按册次、章节、节和知识点进入备课工作区。</p></div><a className="primary-button" href="/lesson-plans">进入教案生成</a></section>
      {error && <div className="notice warning">{error}</div>}
      {!root && !error && <div className="notice">正在读取知识点树…</div>}
      {!!volumes.length && <>
        <nav className="curriculum-volume-tabs" aria-label="选择教材册次">{volumes.map((volume) => <button className={selectedVolume?.node_id === volume.node_id ? "active" : ""} type="button" key={volume.node_id} onClick={() => setSelectedVolumeId(volume.node_id)}><strong>{volume.name}</strong><span>{volume.children.length} 章</span></button>)}</nav>
        <div className="curriculum-review-banner"><strong>{selectedVolume?.status === "draft_for_teacher_review" ? "待教师终审" : "已有目录基础"}</strong><span>本册共 {chapters.length} 章、{chapters.reduce((sum, chapter) => sum + chapter.children.length, 0)} 节、{knowledgePointCount} 个知识点。新增四册在您确认前始终保持草稿状态。</span></div>
      </>}
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
