"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import "./imports.css";

type ImportStatus = "registered" | "analyzing" | "ready_for_segmentation" | "failed";
type ImportPage = { page_id: string; page_number: number; width_points: number; height_points: number; extracted_text: string; character_count: number; question_marker_count: number; embedded_image_count: number; has_text_layer: boolean; warnings: string[] };
type ImportFile = { file_id: string; batch_id: string; original_filename: string; size_bytes: number; sha256: string; page_count: number; status: ImportStatus; analyzed_page_count: number; text_page_count: number; scan_page_count: number; extracted_character_count: number; question_marker_count: number; image_page_count: number; embedded_image_count: number; warnings: string[]; error_message: string; created_at: string; updated_at: string };
type ImportFileDetail = ImportFile & { pages: ImportPage[] };
type ImportBatch = { batch_id: string; title: string; rights_basis: string; rights_statement: string; owner_id: string; file_count: number; registered_count: number; ready_count: number; failed_count: number; page_count: number; question_marker_count: number; created_at: string; updated_at: string; files: ImportFile[] };
type ImportWorkspace = { stats: { batches: number; files: number; pages: number; ready_files: number; scan_pages: number; question_markers: number }; batches: ImportBatch[] };

const statusLabels: Record<ImportStatus, string> = { registered: "待分析", analyzing: "分析中", ready_for_segmentation: "可进入拆题", failed: "分析失败" };
const rightsLabels: Record<string, string> = { question_content_user_declared_usable: "题目内容经本人声明可使用", licensed: "已获得明确授权", original: "本人原创", private_research_only: "仅限内部研究" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}
function formatBytes(value: number) { return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }

export default function ImportsPage() {
  const [workspace, setWorkspace] = useState<ImportWorkspace | null>(null);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [selected, setSelected] = useState<ImportFileDetail | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("三文件结构化试点");
  const [rightsBasis, setRightsBasis] = useState("question_content_user_declared_usable");
  const [rightsStatement, setRightsStatement] = useState("本人确认仅使用题目事实，不复用原 PDF 版式、封面、水印、讲义文字和原解析表述。");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedBatch = useMemo(() => workspace?.batches.find((batch) => batch.batch_id === selected?.batch_id) ?? null, [selected, workspace]);

  async function openFile(fileId: string) {
    const response = await fetch(`/api/v1/imports/files/${fileId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const detail: ImportFileDetail = await response.json();
    setSelectedFileId(fileId); setSelected(detail); setPreviewPage(1);
  }

  async function refresh(preferredFileId?: string) {
    const response = await fetch("/api/v1/imports");
    if (!response.ok) throw new Error(await errorText(response));
    const payload: ImportWorkspace = await response.json();
    setWorkspace(payload);
    const target = preferredFileId || selectedFileId || payload.batches[0]?.files[0]?.file_id;
    if (target) await openFile(target); else { setSelected(null); setSelectedFileId(""); }
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

  return <div className="page-content import-workspace">
    <section className="page-title import-title"><div><p className="eyebrow">题库生产 · 来源可追溯</p><h1>批量 PDF 加工中心</h1><p className="subtle">先登记来源和权利，再逐页分析；任何文件都不会自动进入正式题库。</p></div><button className="primary-button" type="button" onClick={() => setUploadOpen((value) => !value)}>{uploadOpen ? "收起登记" : "＋ 新建批次"}</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage("")}>关闭</button></div>}
    <section className="import-stats"><div><span>导入批次</span><strong>{workspace?.stats.batches ?? "—"}</strong><small>保留权利声明</small></div><div><span>PDF 文件</span><strong>{workspace?.stats.files ?? "—"}</strong><small>{workspace?.stats.pages ?? 0} 页</small></div><div className="ready"><span>已完成页分析</span><strong>{workspace?.stats.ready_files ?? "—"}</strong><small>可进入拆题准备</small></div><div className={workspace?.stats.scan_pages ? "attention" : ""}><span>待 OCR 页面</span><strong>{workspace?.stats.scan_pages ?? "—"}</strong><small>文字层不足</small></div><div><span>题号标记</span><strong>{workspace?.stats.question_markers ?? "—"}</strong><small>仅作边界候选</small></div></section>

    {uploadOpen && <form className="import-upload-panel" onSubmit={upload}>
      <header><span>01</span><div><h2>登记一批 PDF</h2><p>每批最多 12 份、单份不超过 100 MB；登记后由教师决定何时分析。</p></div></header>
      <label className="import-file-picker"><input type="file" accept="application/pdf,.pdf" multiple onChange={chooseFiles} /><strong>{files.length ? `已选择 ${files.length} 份 PDF` : "选择多份 PDF"}</strong><small>{files.length ? files.map((file) => file.name).join("、") : "建议首批选择函数与导数、概率统计、立体几何三种版式"}</small></label>
      <div className="import-upload-grid"><label><span>批次名称</span><input value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} /></label><label><span>使用权依据</span><select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value)}>{Object.entries(rightsLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
      <label><span>来源与使用边界</span><textarea value={rightsStatement} onChange={(event) => setRightsStatement(event.target.value)} /></label>
      <footer><label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我确认声明真实；登记、分析和拆题均不等于允许公开发布。</span></label><button type="submit" disabled={busy || !files.length || !acknowledged || rightsStatement.trim().length < 6}>{busy ? "正在登记…" : "登记批次"}</button></footer>
    </form>}

    <section className="import-layout">
      <aside className="import-queue">
        <header><strong>处理队列</strong><span>{workspace?.stats.files ?? 0} 份</span></header>
        {!workspace?.batches.length && <div className="import-empty"><strong>暂无导入批次</strong><p>从上方选择 PDF，登记后再逐份分析。</p></div>}
        {workspace?.batches.map((batch) => <section key={batch.batch_id} className="import-batch-group"><header><div><strong>{batch.title}</strong><small>{batch.file_count} 份 · {batch.page_count} 页 · {rightsLabels[batch.rights_basis]}</small></div><em>{batch.ready_count}/{batch.file_count}</em></header>{batch.files.map((file) => <button type="button" className={selectedFileId === file.file_id ? "active" : ""} key={file.file_id} onClick={() => openFile(file.file_id).catch((error: Error) => setMessage(error.message))}><span className={`import-file-status ${file.status}`}>PDF</span><div><b>{file.original_filename}</b><small>{file.page_count} 页 · {formatBytes(file.size_bytes)}</small></div><em className={file.status}>{statusLabels[file.status]}</em></button>)}</section>)}
      </aside>

      <main className="import-inspector">{!selected ? <div className="import-inspector-empty"><span>PDF</span><h2>选择文件检查页面质量</h2><p>这里会显示原文件、文字层覆盖、题号标记和需要 OCR 的页面。</p></div> : <>
        <header className="import-inspector-heading"><div><p>{selectedBatch?.title}</p><h2>{selected.original_filename}</h2><small>SHA-256：{selected.sha256.slice(0, 18)}… · {formatBytes(selected.size_bytes)}</small></div><div><a href={`/api/v1/imports/files/${selected.file_id}/source`} target="_blank" rel="noreferrer">打开原 PDF</a><button type="button" disabled={busy} onClick={analyzeFile}>{busy ? "分析中…" : selected.status === "ready_for_segmentation" ? "重新分析" : "分析此文件"}</button><button className="primary" type="button" disabled={busy || !selectedBatch || selectedBatch.ready_count === selectedBatch.file_count} onClick={analyzeBatch}>分析本批全部</button></div></header>
        <section className="import-file-metrics"><div><span>状态</span><strong className={selected.status}>{statusLabels[selected.status]}</strong></div><div><span>总页数</span><strong>{selected.page_count}</strong></div><div><span>有文字层</span><strong>{selected.text_page_count}</strong></div><div><span>待 OCR</span><strong>{selected.scan_page_count}</strong></div><div><span>题号 / 图片</span><strong>{selected.question_marker_count} / {selected.embedded_image_count}</strong></div></section>
        {selected.error_message && <div className="notice warning">{selected.error_message}</div>}{selected.warnings.map((warning) => <p className="import-warning" key={warning}>{warning}</p>)}
        <div className="import-preview-layout">
          <section className="import-pdf-preview"><header><strong>原 PDF 预览</strong><span>第 {previewPage} / {selected.page_count} 页</span></header><div className="import-preview-scroll"><img key={`${selected.file_id}-${previewPage}`} alt={`${selected.original_filename} 第 ${previewPage} 页`} src={`/api/v1/imports/files/${selected.file_id}/pages/${previewPage}/preview?width=1200`} /></div></section>
          <section className="import-page-analysis"><header><div><strong>逐页分析</strong><small>{selected.pages.length ? `${selected.pages.length} 页已分析` : "分析后生成页面指标"}</small></div><span>题号仅是候选</span></header>
            {!selected.pages.length ? <div className="import-page-empty"><strong>尚未分析</strong><p>点击“分析此文件”，系统只提取页面文字和题号标记，不生成题库内容。</p></div> : <div className="import-page-list">{selected.pages.map((page) => <button type="button" className={previewPage === page.page_number ? "active" : ""} key={page.page_id} onClick={() => setPreviewPage(page.page_number)}><span>{String(page.page_number).padStart(3, "0")}</span><div><strong>{page.has_text_layer ? `${page.character_count} 字符` : "文字层不足"}</strong><small>{page.question_marker_count} 个题号 · {page.embedded_image_count} 张图 · {Math.round(page.width_points)} × {Math.round(page.height_points)} pt</small></div><em className={page.has_text_layer ? "text" : "ocr"}>{page.has_text_layer ? "文本" : "OCR"}</em></button>)}</div>}
          </section>
        </div>
        <footer className="import-next-stage"><div><span>下一加工环节</span><strong>题目边界与小问校对</strong><p>下一阶段将在当前页坐标和文字层之上生成拆题候选，并继续保持教师确认门禁。</p></div><em>{selected.status === "ready_for_segmentation" ? "页面基础已就绪" : "请先完成页面分析"}</em></footer>
      </>}</main>
    </section>
  </div>;
}
