import type { Metadata } from "next";
import Link from "next/link";
import "katex/dist/katex.min.css";
import { TopbarTools } from "./components/topbar-tools";
import "./globals.css";

export const metadata: Metadata = {
  title: "数研备课",
  description: "高中数学教师的 AI 备课、搜题与组卷工作台",
};

const navItems = [
  ["工作台", "/"],
  ["教材备课", "/curriculum"],
  ["智能搜题", "/search"],
  ["解题助手", "/solve"],
  ["教案", "/lesson-plans"],
  ["组卷", "/papers"],
  ["我的资料", "/library"],
  ["批量导入", "/imports"],
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
            <TopbarTools />
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
