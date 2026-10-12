import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

/** Native <details> disclosure used for secondary evidence: closed by default, keyboard-operable, no JS state. */
export function Disclosure({ title, summary, children, id }: { title: string; summary?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <details className="disclosure" id={id}>
      <summary>
        <ChevronRight size={16} aria-hidden className="disclosure__chev" />
        <span className="disclosure__title">{title}</span>
        {summary && <span className="disclosure__summary">{summary}</span>}
      </summary>
      <div className="disclosure__body">{children}</div>
    </details>
  );
}
