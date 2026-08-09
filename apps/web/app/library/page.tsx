"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import "./library.css";

type LibrarySummary = {
  library_item_id: string; title: string; original_filename: string; file_kind: "pdf" | "docx" | "image";
  mime_type: string; size_bytes: number; page_count: number | null; extraction_status: "extracted" | "needs_ocr" | "failed";
  text_review_status: "pending" | "confirmed"; extracted_char_count: number; corrected_char_count: number;
  rights_basis: "original" | "licensed" | "private_teaching_only"; version: number; updated_at: string;
};
type LibraryItem = LibrarySummary & {
  source_sha256: string; extracted_text: string; corrected_text: string; rights_statement: string;
  adaptation_allowed: boolean; warnings: string[]; review_note: string;
};
type LibraryStats = { total: number; pending_review: number; confirmed: number; needs_ocr: number; by_file_kind: Record<string, number> };

const extractionLabels = { extracted: "已提取文字", needs_ocr: "待 OCR / 转录", failed: "提取失败" };
const rightsLabels = { original: "本人原创", licensed: "已获授权", private_teaching_only: "仅限私人教学" };
const fileKindLabels = { pdf: "PDF", docx: "Word", image: "图片" };

async function errorText(response: Response) {
  try { const payload = await response.json(); return payload.detail || `请求失败（HTTP ${response.status}）`; }
  catch { return `请求失败（HTTP ${response.status}）`; }
}
function formatBytes(value: number) { return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }

export default function LibraryPage() {
  const [items, setItems] = useState<LibrarySummary[]>([]);
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const [draftText, setDraftText] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [rightsBasis, setRightsBasis] = useState<LibrarySummary["rights_basis"]>("private_teaching_only");
  const [rightsStatement, setRightsStatement] = useState("本人确认该资料仅上传至私人空间，用于本人日常教学与备课。");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) => !keyword || `${item.title} ${item.original_filename}`.toLowerCase().includes(keyword));
  }, [items, query]);

  async function openItem(itemId: string) {
    const response = await fetch(`/api/v1/library/${itemId}`);
    if (!response.ok) throw new Error(await errorText(response));
    const item: LibraryItem = await response.json();
    setSelected(item);
    setDraftText(item.corrected_text || item.extracted_text);
    setReviewNote(item.review_note);
  }

  async function refresh(preferredId?: string) {
    const [listResponse, statsResponse] = await Promise.all([fetch("/api/v1/library"), fetch("/api/v1/library/stats")]);
    if (!listResponse.ok) throw new Error(await errorText(listResponse));
    if (!statsResponse.ok) throw new Error(await errorText(statsResponse));
    const list = await listResponse.json();
    setItems(list.items);
    setStats(await statsResponse.json());
    const nextId = preferredId || selected?.library_item_id || list.items[0]?.library_item_id;
    if (nextId) await openItem(nextId);
  }

  useEffect(() => { refresh().catch((error: Error) => setMessage(error.message)); }, []);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    if (next && !title.trim()) setTitle(next.name.replace(/\.[^.]+$/, ""));
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) { setMessage("请选择要上传的 PDF、DOCX 或图片。"); return; }
    if (!acknowledged) { setMessage("请先确认资料来源和使用权声明。"); return; }
    setBusy(true); setMessage(null);
    try {
      const body = new FormData();
      body.append("file", file); body.append("title", title); body.append("rights_basis", rightsBasis);
      body.append("rights_statement", rightsStatement); body.append("rights_acknowledged", String(acknowledged));
      const response = await fetch("/api/v1/library", { method: "POST", body });
      if (!response.ok) throw new Error(await errorText(response));
      const item: LibraryItem = await response.json();
      await refresh(item.library_item_id);
      setFile(null); setTitle(""); setAcknowledged(false); setUploadOpen(false);
      setMessage(item.extraction_status === "extracted" ? "资料已安全上传并提取文字，请进行人工校对。" : "资料已安全上传；当前需要 OCR 或人工转录。" );
    } catch (error) { setMessage(error instanceof Error ? error.message : "资料上传失败"); }
    finally { setBusy(false); }
  }

  async function saveReview(confirm: boolean) {
    if (!selected) return;
    if (confirm && !draftText.trim()) { setMessage("确认校对前必须填写可用文本。"); return; }
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/v1/library/${selected.library_item_id}/review`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrected_text: draftText, note: reviewNote, confirm }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const item: LibraryItem = await response.json();
      setSelected(item); setDraftText(item.corrected_text); await refresh(item.library_item_id);
      setMessage(confirm ? "文本校对已确认；资料仍保持私人状态。" : "校对草稿已保存为新版本。" );
    } catch (error) { setMessage(error instanceof Error ? error.message : "校对保存失败"); }
    finally { setBusy(false); }
  }

  return <div className="page-content library-workspace">
    <section className="page-title library-title"><div><p className="eyebrow">个人资料库 · 默认私人</p><h1>先安全收进来，再逐份校对。</h1><p className="subtle">原文件、提取文本与教师修订分开保存；未经明确授权不会进入公共题库或模型训练。</p></div><button className="primary-button" type="button" onClick={() => setUploadOpen((current) => !current)}>{uploadOpen ? "收起上传" : "＋ 上传资料"}</button></section>
    {message && <div className="notice info-notice"><span>{message}</span><button type="button" onClick={() => setMessage(null)}>关闭</button></div>}

    <section className="library-stats"><div><span>私人资料</span><strong>{stats?.total ?? "—"}</strong><small>不会公开检索</small></div><div><span>待人工校对</span><strong>{stats?.pending_review ?? "—"}</strong><small>保留原始提取文本</small></div><div className="confirmed"><span>已确认文本</span><strong>{stats?.confirmed ?? "—"}</strong><small>可进入后续结构化</small></div><div className={stats?.needs_ocr ? "attention" : ""}><span>待 OCR / 转录</span><strong>{stats?.needs_ocr ?? "—"}</strong><small>图片或扫描件</small></div></section>

    {uploadOpen && <form className="library-upload-panel" onSubmit={upload}>
      <div className="library-upload-heading"><span>入</span><div><h2>上传私人资料</h2><p>支持 PDF、DOCX、PNG、JPEG、WebP，单文件不超过 50 MB</p></div></div>
      <label className="library-file-drop"><input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" onChange={selectFile} /><span>{file ? file.name : "点击选择文件"}</span><small>{file ? formatBytes(file.size) : "系统会校验真实格式，不只检查扩展名"}</small></label>
      <label><span>资料标题</span><input value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} placeholder="例如：函数性质专题讲义" /></label>
      <label><span>使用权依据</span><select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as LibrarySummary["rights_basis"])}><option value="private_teaching_only">仅限本人私人教学使用</option><option value="original">本人原创</option><option value="licensed">已获得明确授权</option></select></label>
      <label className="library-rights-statement"><span>来源与权利说明</span><textarea value={rightsStatement} onChange={(event) => setRightsStatement(event.target.value)} /></label>
      <label className="library-ack"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我确认上述声明真实；该资料默认保持私人，不自动用于公共展示或模型训练。</span></label>
      <button className="library-upload-submit" disabled={busy || !file || !acknowledged || rightsStatement.trim().length < 6} type="submit">{busy ? "正在校验并提取…" : "上传并提取文字"}</button>
    </form>}

    <div className="library-layout">
      <aside className="library-list-panel">
        <header><div><strong>我的资料</strong><span>{filtered.length} 份</span></div><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或文件名" /></header>
        <div className="library-item-list">{filtered.map((item) => <button className={selected?.library_item_id === item.library_item_id ? "active" : ""} type="button" key={item.library_item_id} onClick={() => openItem(item.library_item_id).catch((error: Error) => setMessage(error.message))}><span className={`library-kind ${item.file_kind}`}>{fileKindLabels[item.file_kind]}</span><div><b>{item.title}</b><p>{item.original_filename}</p><small>{extractionLabels[item.extraction_status]} · {item.text_review_status === "confirmed" ? "教师已确认" : "待校对"} · v{item.version}</small></div></button>)}{!filtered.length && <div className="empty-state"><strong>暂无私人资料</strong><p>从上方上传第一份 PDF、Word 或图片。</p></div>}</div>
      </aside>

      <main className="library-review-panel">
        {!selected ? <div className="library-empty"><span>资</span><h2>上传资料后从这里开始校对</h2><p>系统保留原文件和自动提取结果；教师修订会生成新版本，不会覆盖原文。</p></div> : <>
          <header className="library-document-heading"><div><p>{fileKindLabels[selected.file_kind]} · {formatBytes(selected.size_bytes)}{selected.page_count ? ` · ${selected.page_count} 页` : ""}</p><h2>{selected.title}</h2><small>{selected.original_filename}</small></div><div><span className={`library-review-status ${selected.text_review_status}`}>{selected.text_review_status === "confirmed" ? "教师已确认" : "待人工校对"}</span><a href={`/api/v1/library/${selected.library_item_id}/file`}>下载原文件</a></div></header>
          <section className="library-privacy-strip"><div><span>可见范围</span><strong>仅本人</strong></div><div><span>模型训练</span><strong>禁止</strong></div><div><span>改编权限</span><strong>{selected.adaptation_allowed ? "已声明允许" : "未授权"}</strong></div><div><span>权利依据</span><strong>{rightsLabels[selected.rights_basis]}</strong></div></section>
          {selected.warnings.map((warning) => <p className="library-warning" key={warning}>{warning}</p>)}
          {selected.file_kind === "image" && <div className="library-image-preview"><img src={`/api/v1/library/${selected.library_item_id}/file`} alt={selected.title} /></div>}
          <div className="library-text-compare">
            <section><header><div><strong>自动提取原文</strong><small>{selected.extracted_char_count} 字符 · 不可覆盖</small></div><span>{extractionLabels[selected.extraction_status]}</span></header><pre>{selected.extracted_text || "尚无自动提取文字。请在右侧根据原文件进行人工转录。"}</pre></section>
            <section className="library-correction"><header><div><strong>教师校对文本</strong><small>{draftText.length} 字符 · 保存即生成新版本</small></div><span>v{selected.version}</span></header><textarea value={draftText} onChange={(event) => setDraftText(event.target.value)} placeholder="在此修正识别错误、补充公式或人工转录图片内容……" /></section>
          </div>
          <label className="library-review-note"><span>本次校对说明</span><input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="例如：核对第 1—5 页，修正函数公式与上下标" /></label>
          <footer className="library-review-actions"><div><span>确认后仍只进入私人资料库</span><small>后续拆题和进入题库需要再次审核</small></div><button type="button" disabled={busy} onClick={() => saveReview(false)}>保存校对草稿</button><button className="confirm" type="button" disabled={busy || !draftText.trim()} onClick={() => saveReview(true)}>{busy ? "保存中…" : "确认文本可用"}</button></footer>
        </>}
      </main>
    </div>
  </div>;
}
