import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export interface Preferences {
  sidebarCollapsed: boolean;
  density: "comfortable" | "compact";
  defaultSpeed: number; // replay minutes per wall-clock second
  motion: "system" | "reduce";
  shortcuts: boolean;
}

const DEFAULTS: Preferences = {
  sidebarCollapsed: false,
  density: "comfortable",
  defaultSpeed: 10,
  motion: "system",
  shortcuts: true,
};
const KEY = "glucotwin.preferences.v1";

function load(): Preferences {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS;
  } catch {
    return DEFAULTS; // storage unavailable: continue with usable defaults
  }
}

interface Ctx {
  prefs: Preferences;
  update: (patch: Partial<Preferences>) => void;
  reduceMotion: boolean;
}
const PrefContext = createContext<Ctx | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Preferences>(load);
  const [systemReduce, setSystemReduce] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const fn = () => setSystemReduce(mq.matches);
    mq.addEventListener?.("change", fn);
    return () => mq.removeEventListener?.("change", fn);
  }, []);
  const update = useCallback((patch: Partial<Preferences>) => {
    setPrefs((p) => {
      const next = { ...p, ...patch };
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const reduceMotion = prefs.motion === "reduce" || systemReduce;
  useEffect(() => {
    const el = document.documentElement;
    el.dataset.density = prefs.density;
    el.dataset.motion = reduceMotion ? "reduce" : "allow";
  }, [prefs.density, reduceMotion]);
  const value = useMemo(() => ({ prefs, update, reduceMotion }), [prefs, update, reduceMotion]);
  return <PrefContext.Provider value={value}>{children}</PrefContext.Provider>;
}

export function usePreferences(): Ctx {
  const c = useContext(PrefContext);
  if (!c) throw new Error("PreferencesProvider missing");
  return c;
}
