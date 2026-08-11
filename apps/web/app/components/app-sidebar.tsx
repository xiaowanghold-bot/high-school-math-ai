"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AppRole, useAppRole } from "./role-provider";

const teacherNav = [
  ["工作台", "/"], ["教材备课", "/curriculum"], ["智能搜题", "/search"],
  ["解题助手", "/solve"], ["教案", "/lesson-plans"], ["组卷", "/papers"], ["我的资料", "/library"],
];
const adminNav = [
  ["管理总览", "/admin"], ["题库审核", "/search"], ["教材目录", "/curriculum"],
  ["教材审核", "/curriculum/review"], ["资料管理", "/library"], ["批量导入", "/imports"],
  ["模型运行", "/admin/models"],
];

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { role, ready, setRole } = useAppRole();
  const [open, setOpen] = useState(false);
  const switcherRef = useRef<HTMLDivElement>(null);
  const navItems = role === "admin" ? adminNav : teacherNav;

  useEffect(() => {
    function close(event: MouseEvent) {
      if (!switcherRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function choose(nextRole: AppRole) {
    setRole(nextRole);
    setOpen(false);
    if (nextRole === "admin") router.push("/admin");
    else if (pathname === "/admin" || pathname === "/imports" || pathname.startsWith("/curriculum/review")) router.push("/");
  }

  return <aside className={`sidebar ${role}-mode`}>
    <Link className="brand" href={role === "admin" ? "/admin" : "/"} aria-label="数研备课首页">
      <span className="brand-mark">Σ</span>
      <span><strong>数研备课</strong><small>Math Studio</small></span>
    </Link>
    <div className="sidebar-mode-label">{role === "admin" ? "平台管理" : "教师工作区"}</div>
    <nav aria-label="主导航">
      {navItems.map(([label, href]) => {
        const matched = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
        const shadowedBySpecificItem = navItems.some(([, candidate]) => candidate !== href && candidate.startsWith(`${href}/`) && (pathname === candidate || pathname.startsWith(`${candidate}/`)));
        const active = matched && !shadowedBySpecificItem;
        return <Link className={active ? "active" : ""} key={href} href={href}>{label}</Link>;
      })}
    </nav>
    <div className="sidebar-footer">
      <p>人教 A 版 · 新高考Ⅰ卷</p>
      <div className="role-switcher" ref={switcherRef}>
        {open && <div className="role-menu" role="menu" aria-label="切换工作模式">
          <button className={role === "teacher" ? "selected" : ""} type="button" role="menuitem" onClick={() => choose("teacher")}><span>教</span><div><strong>教师模式</strong><small>备课、搜题、教案与组卷</small></div><b>{role === "teacher" ? "✓" : ""}</b></button>
          <button className={role === "admin" ? "selected" : ""} type="button" role="menuitem" onClick={() => choose("admin")}><span>管</span><div><strong>管理员模式</strong><small>题库、教材与批量内容生产</small></div><b>{role === "admin" ? "✓" : ""}</b></button>
        </div>}
        <button className="role-switch-button" type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)} disabled={!ready}>
          <span>{role === "admin" ? "管" : "教"}</span><strong>{role === "admin" ? "管理员模式" : "教师模式"}</strong><b>{open ? "⌃" : "⌄"}</b>
        </button>
      </div>
    </div>
  </aside>;
}
