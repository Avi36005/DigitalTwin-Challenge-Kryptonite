import { useEffect, useState } from "react";

/** Live result of a CSS media query (false where matchMedia is unavailable, e.g. tests). */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches;
  const [match, setMatch] = useState(get);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [query]);
  return match;
}

/** Between phone and laptop widths the sidebar becomes the 64px rail automatically. */
export const RAIL_QUERY = "(min-width: 761px) and (max-width: 1024px)";
