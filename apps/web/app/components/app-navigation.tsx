"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { label: "工作台", short: "台", href: "/" },
  { label: "教材备课", short: "材", href: "/curriculum" },
  { label: "智能搜题", short: "题", href: "/search" },
  { label: "教案", short: "案", href: "/lesson-plans" },
];

const upcomingItems = ["组卷", "我的资料"];

function isCurrent(pathname: string, href: string) {
  return href === "/" ? pathname === href : pathname.startsWith(href);
}

function NavigationLinks({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  return (
    <nav className={mobile ? "mobile-nav-links" : "sidebar-nav"} aria-label={mobile ? "移动端主导航" : "主导航"}>
      {navItems.map((item) => {
        const current = isCurrent(pathname, item.href);
        return (
          <Link className={current ? "nav-link is-current" : "nav-link"} key={item.href} href={item.href} aria-current={current ? "page" : undefined}>
            <span aria-hidden="true">{item.short}</span>
            <strong>{item.label}</strong>
          </Link>
        );
      })}
      {upcomingItems.map((label) => (
        <span className="nav-link is-disabled" aria-disabled="true" key={label}>
          <span aria-hidden="true">{label.slice(0, 1)}</span>
          <strong>{label}</strong>
          <small>后续</small>
        </span>
      ))}
    </nav>
  );
}

export function AppNavigation() {
  return <NavigationLinks />;
}

export function MobileNavigation() {
  return (
    <details className="mobile-nav">
      <summary aria-label="打开主导航"><span>菜单</span></summary>
      <div className="mobile-nav-sheet"><NavigationLinks mobile /></div>
    </details>
  );
}

