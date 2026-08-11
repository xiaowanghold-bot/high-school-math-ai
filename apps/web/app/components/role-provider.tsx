"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type AppRole = "teacher" | "admin";

type RoleContextValue = {
  role: AppRole;
  ready: boolean;
  isAdmin: boolean;
  actorId: "owner_teacher" | "owner_admin";
  setRole: (role: AppRole) => void;
};

const STORAGE_KEY = "math-studio-role";
const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const [role, setRoleState] = useState<AppRole>("teacher");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "admin" || saved === "teacher") setRoleState(saved);
    setReady(true);
  }, []);

  function setRole(nextRole: AppRole) {
    setRoleState(nextRole);
    window.localStorage.setItem(STORAGE_KEY, nextRole);
    document.cookie = `math_studio_role=${nextRole}; path=/; max-age=31536000; samesite=lax`;
  }

  const value = useMemo<RoleContextValue>(() => ({
    role,
    ready,
    isAdmin: role === "admin",
    actorId: role === "admin" ? "owner_admin" : "owner_teacher",
    setRole,
  }), [ready, role]);

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useAppRole() {
  const context = useContext(RoleContext);
  if (!context) throw new Error("useAppRole 必须在 RoleProvider 内使用");
  return context;
}

