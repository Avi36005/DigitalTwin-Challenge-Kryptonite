import { createContext, useContext } from "react";

export type ShellDialog = "search" | "new-replay" | "preferences" | "help" | "mobile-nav" | null;

export interface ShellCtx {
  open: (d: Exclude<ShellDialog, null>, opts?: { patientId?: string }) => void;
  close: () => void;
}

export const ShellContext = createContext<ShellCtx | null>(null);

export function useShell(): ShellCtx {
  const c = useContext(ShellContext);
  if (!c) throw new Error("ShellContext missing");
  return c;
}
