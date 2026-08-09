import type { Metadata } from "next";
import Link from "next/link";
import { Noto_Sans_SC, Noto_Serif_SC } from "next/font/google";
import "katex/dist/katex.min.css";
import "./globals.css";
import { AppNavigation, MobileNavigation } from "./components/app-navigation";

const notoSans = Noto_Sans_SC({
  variable: "--font-noto-sans-sc",
  display: "swap",
  weight: ["400", "500", "700"],
});

const notoSerif = Noto_Serif_SC({
  variable: "--font-noto-serif-sc",
  display: "swap",
  weight: ["500", "700"],
});

export const metadata: Metadata = {
  title: "数研备课",
  description: "高中数学教师的 AI 备课、搜题与教案工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${notoSans.variable} ${notoSerif.variable}`}>
        <div className="app-shell">
          <aside className="sidebar">
            <Link className="brand" href="/" aria-label="数研备课首页">
              <span className="brand-mark" aria-hidden="true">Σ</span>
              <span><strong>数研备课</strong><small>Math Studio</small></span>
            </Link>
            <AppNavigation />
            <div className="sidebar-footer">
              <p>人教 A 版<br />新高考Ⅰ卷地区</p>
              <div className="teacher-profile"><span className="teacher-avatar">王</span><span><strong>教师工作区</strong><small>内容审核权限</small></span></div>
            </div>
          </aside>
          <main className="main-column">
            <header className="topbar">
              <MobileNavigation />
              <Link className="global-search" href="/search" aria-label="打开智能搜题">
                <span className="search-symbol" aria-hidden="true">⌕</span>
                <span>搜索知识点、题型或描述一道题</span>
                <kbd>搜题</kbd>
              </Link>
              <span className="workspace-status"><i aria-hidden="true" />本地工作区</span>
              <Link className="primary-button" href="/lesson-plans/new">新建教案</Link>
            </header>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
