import type { Metadata } from "next";
import Link from "next/link";
import "katex/dist/katex.min.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "数研备课",
  description: "高中数学教师的 AI 备课、搜题与组卷工作台",
};

const navItems = [
  ["工作台", "/"],
  ["教材备课", "/curriculum"],
  ["智能搜题", "/search"],
  ["教案", "/lesson-plans"],
  ["组卷", "/papers"],
  ["我的资料", "/library"],
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <Link className="brand" href="/" aria-label="数研备课首页">
              <span className="brand-mark">Σ</span>
              <span><strong>数研备课</strong><small>Math Studio</small></span>
            </Link>
            <nav aria-label="主导航">
              {navItems.map(([label, href]) => <Link key={href} href={href}>{label}</Link>)}
            </nav>
            <div className="sidebar-footer">
              <p>人教 A 版 · 新高考Ⅰ卷</p>
              <button type="button">教师 / 管理员</button>
            </div>
          </aside>
          <main className="main-column">
            <header className="topbar">
              <div className="global-search">⌕ <span>搜索知识点、题型或直接描述你要找的题目</span></div>
              <button className="ghost-button" type="button">任务中心</button>
              <button className="primary-button" type="button">＋ 新建</button>
            </header>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
