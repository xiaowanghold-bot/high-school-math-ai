import type { Metadata } from "next";
import "katex/dist/katex.min.css";
import { AppSidebar } from "./components/app-sidebar";
import { RoleProvider } from "./components/role-provider";
import { TopbarTools } from "./components/topbar-tools";
import "./globals.css";

export const metadata: Metadata = {
  title: "数研备课",
  description: "高中数学教师的 AI 备课、搜题与组卷工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <RoleProvider>
          <div className="app-shell">
            <AppSidebar />
            <main className="main-column">
              <TopbarTools />
              {children}
            </main>
          </div>
        </RoleProvider>
      </body>
    </html>
  );
}
