"use client";

import Link from "next/link";
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

export default function CurriculumPage() {
  const [root, setRoot] = useState<CurriculumNode | null>(null);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [highlightedChapterId, setHighlightedChapterId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/curriculum/tree")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((tree: CurriculumNode) => {
        setRoot(tree);
        const volumes = tree.node_type === "volume"
          ? [tree]
          : tree.children.filter((item) => item.node_type === "volume");
        const params = new URLSearchParams(window.location.search);
        const requestedVolumeId = params.get("volume");
        const requestedChapterId = params.get("chapter") ?? "";
        const requestedVolume = volumes.find((item) => item.node_id === requestedVolumeId);
        const nextVolume = requestedVolume ?? volumes[0];
        if (nextVolume) setSelectedVolumeId(nextVolume.node_id);
        if (requestedChapterId) setHighlightedChapterId(requestedChapterId);
      })
      .catch(() => setError("课程接口暂时不可用，请先启动 FastAPI。"));
  }, []);

  const volumes = root
    ? root.node_type === "volume"
      ? [root]
      : root.children.filter((item) => item.node_type === "volume")
    : [];
  const selectedVolume = volumes.find((item) => item.node_id === selectedVolumeId) ?? volumes[0];
  const chapters = selectedVolume?.children ?? [];
  const sectionCount = chapters.reduce((total, chapter) => total + chapter.children.length, 0);
  const knowledgePointCount = chapters.reduce(
    (chapterTotal, chapter) => chapterTotal + chapter.children.reduce(
      (sectionTotal, section) => sectionTotal + section.children.length,
      0,
    ),
    0,
  );

  useEffect(() => {
    if (!highlightedChapterId || !chapters.some((chapter) => chapter.node_id === highlightedChapterId)) return;
    document.getElementById(`curriculum-${highlightedChapterId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [chapters, highlightedChapterId]);

  return <div className="page-content">
    <section className="page-title">
      <div><p className="eyebrow">教材备课</p><h1>人教 A 版 · {selectedVolume?.name || "课程目录"}</h1><p className="subtle">按册次、章、节和知识点进入备课工作区。</p></div>
      <div className="curriculum-page-actions">
        <span className="review-secondary-button" aria-label="只读封存教材基线">官方基线 · 只读封存</span>
        <Link className="primary-button" href="/lesson-plans">进入教案工作区</Link>
      </div>
    </section>
    {error && <div className="notice warning">{error}</div>}
    {!root && !error && <div className="notice">正在读取知识点树…</div>}
    {!!volumes.length && <>
      <nav className="curriculum-volume-tabs" aria-label="选择教材册次">
        {volumes.map((volume) => <button className={selectedVolume?.node_id === volume.node_id ? "active" : ""} type="button" key={volume.node_id} onClick={() => { setSelectedVolumeId(volume.node_id); setHighlightedChapterId(""); }}><strong>{volume.name}</strong><span>{volume.children.length} 章</span></button>)}
      </nav>
      <div className="curriculum-review-banner">
        <strong>官方标准基线 · 只读</strong>
        <span>本册共 {chapters.length} 章、{sectionCount} 节、{knowledgePointCount} 个知识点。目录按教育部课程标准与人教 A 版教材范围封存，用于题目标注和教案生成，不再设置人工教材审核。</span>
      </div>
    </>}
    <div className="curriculum-grid">
      {chapters.map((chapter) => <article id={`curriculum-${chapter.node_id}`} className={`curriculum-card curriculum-prep-card ${highlightedChapterId === chapter.node_id ? "highlighted" : ""}`} key={chapter.node_id}>
        <header><span>{chapter.code.padStart(2, "0")}</span><div><h2>{chapter.name}</h2><p>{chapter.children.length} 节 · {chapter.children.reduce((total, section) => total + section.children.length, 0)} 个知识点</p></div>{chapter.children[0] && <Link className="curriculum-chapter-start" href={`/lesson-plans?curriculum=${encodeURIComponent(chapter.children[0].node_id)}`}>从本章开始 →</Link>}</header>
        <div className="curriculum-section-list">{chapter.children.map((section) => <details className="curriculum-section" key={section.node_id}>
          <summary><div><b>{section.code}</b><span>{section.name}</span></div><span>{section.children.length} 个知识点 <b aria-hidden="true">⌄</b></span></summary>
          <div className="curriculum-section-content">
            <Link className="curriculum-whole-section" href={`/lesson-plans?curriculum=${encodeURIComponent(section.node_id)}`}><span>按整节备课</span><b>直接带入教案生成 →</b></Link>
            <div className="curriculum-knowledge-list">
              {section.children.map((knowledgePoint) => <Link href={`/lesson-plans?curriculum=${encodeURIComponent(knowledgePoint.node_id)}`} key={knowledgePoint.node_id}><span>{knowledgePoint.name}</span><b>用此知识点备课 →</b></Link>)}
            </div>
          </div>
        </details>)}</div>
      </article>)}
    </div>
  </div>;
}
