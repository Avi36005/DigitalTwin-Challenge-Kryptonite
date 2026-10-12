import { ArrowDown, ArrowUp, ArrowUpDown, X, type LucideIcon } from "lucide-react";
import {
  Children,
  forwardRef,
  Fragment,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";

/* ---------------------------------------------------------------- Button */
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** primary: the one main action in a region · secondary: bordered · ghost: borderless · quiet: text action in rows */
  variant?: "primary" | "secondary" | "ghost" | "quiet";
  size?: "md" | "sm";
  block?: boolean;
  icon?: LucideIcon;
  iconEnd?: LucideIcon;
  /** marks an in-flight action: disabled and announced as busy, label supplied by the caller */
  busy?: boolean;
};
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", block, icon: Icon, iconEnd: IconEnd, busy, className = "", children, type = "button", disabled, ...rest },
  ref,
) {
  const cls = ["btn", `btn--${variant}`, size === "sm" && "btn--sm", block && "btn--block", className].filter(Boolean).join(" ");
  const s = size === "sm" ? 15 : 16;
  return (
    <button ref={ref} type={type} className={cls} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {Icon && <Icon size={s} aria-hidden strokeWidth={1.9} />}
      {children}
      {IconEnd && <IconEnd size={s} aria-hidden strokeWidth={1.9} />}
    </button>
  );
});

/* ---------------------------------------------------------------- Tooltip (hover and keyboard focus) */
export function Tooltip({ label, children, side = "top" }: { label: string; children: ReactNode; side?: "top" | "right" | "below" }) {
  return (
    <span className={`tip tip--${side}`}>
      {children}
      <span className="tip__bubble" aria-hidden>
        {label}
      </span>
    </span>
  );
}

/* ---------------------------------------------------------------- IconButton (always named) */
type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: LucideIcon;
  label: string;
  variant?: "secondary" | "ghost" | "primary";
  size?: "md" | "sm";
  tooltip?: boolean;
  tooltipSide?: "top" | "right" | "below";
};
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon: Icon, label, variant = "ghost", size = "md", tooltip = true, tooltipSide = "top", className = "", ...rest },
  ref,
) {
  const btn = (
    <button ref={ref} type="button" aria-label={label}
      className={["icon-btn", `icon-btn--${variant}`, size === "sm" && "icon-btn--sm", className].filter(Boolean).join(" ")} {...rest}>
      <Icon size={size === "sm" ? 16 : 18} aria-hidden strokeWidth={1.8} />
    </button>
  );
  return tooltip ? <Tooltip label={label} side={tooltipSide}>{btn}</Tooltip> : btn;
});

/* ---------------------------------------------------------------- StatusLabel (text, never an interactive-looking pill) */
export type Tone = "neutral" | "info" | "attention" | "danger" | "muted";
export function StatusLabel({ tone = "neutral", icon: Icon, children, title }: {
  tone?: Tone; icon?: LucideIcon; children: ReactNode; title?: string;
}) {
  return (
    <span className={`status status--${tone}`} title={title}>
      {Icon ? <Icon size={14} aria-hidden strokeWidth={2} /> : tone === "attention" || tone === "danger" ? <span className="status__dot" aria-hidden /> : null}
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- Page header */
export function PageHeader({ title, children, actions, meta, titleId }: {
  title: ReactNode; children?: ReactNode; actions?: ReactNode; meta?: ReactNode; titleId?: string;
}) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        <h1 id={titleId} tabIndex={-1} className="page-title">{title}</h1>
        {meta && <div className="page-header__meta">{meta}</div>}
        {children && <p className="page-header__desc">{children}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

/* ---------------------------------------------------------------- Section: heading + content on the page, divided by a rule */
export function Section({ title, description, actions, children, id, className = "", divider = true, level = 2 }: {
  title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string; className?: string;
  divider?: boolean; level?: 2 | 3;
}) {
  const auto = useId();
  const hid = `${id ?? auto}-title`;
  const H = level === 2 ? "h2" : "h3";
  return (
    <section className={`section ${divider ? "section--rule" : ""} ${className}`} aria-labelledby={title ? hid : undefined} id={id}>
      {(title || actions) && (
        <div className="section__head">
          <div className="section__titles">
            {title && <H className={level === 2 ? "section__title" : "section__title section__title--sm"} id={hid}>{title}</H>}
            {description && <p className="section__desc">{description}</p>}
          </div>
          {actions && <div className="section__actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- Metadata line: "a · b · c" */
export function MetadataLine({ children, className = "" }: { children: ReactNode; className?: string }) {
  const items = Children.toArray(children).filter(Boolean);
  return (
    <p className={`meta-line ${className}`}>
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="meta-line__sep" aria-hidden>·</span>}
          <span>{c}</span>
        </Fragment>
      ))}
    </p>
  );
}

/* ---------------------------------------------------------------- Inline notice: icon + words, no filled panel */
export function InlineNotice({ tone = "neutral", icon: Icon, children, role, action }: {
  tone?: Tone; icon?: LucideIcon; children: ReactNode; role?: "status" | "alert" | "note"; action?: ReactNode;
}) {
  return (
    <div className={`notice notice--${tone}`} role={role}>
      {Icon && <Icon size={16} aria-hidden strokeWidth={1.9} className="notice__icon" />}
      <div className="notice__body">{children}</div>
      {action && <div className="notice__action">{action}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Dialog / drawer (native modal: focus trap, Escape, restore) */
export function Dialog({ open, onClose, title, children, footer, className = "", width, labelledBy, bare, variant = "center", description }: {
  open: boolean; onClose: () => void; title?: string; children: ReactNode; footer?: ReactNode; className?: string;
  width?: number; labelledBy?: string; bare?: boolean; variant?: "center" | "drawer"; description?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      opener.current = document.activeElement;
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    } else if (!open && d.open) {
      d.close();
    }
  }, [open]);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const onCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    const onClosed = () => {
      const el = opener.current as HTMLElement | null;
      if (el && typeof el.focus === "function" && document.contains(el)) el.focus();
    };
    d.addEventListener("cancel", onCancel);
    d.addEventListener("close", onClosed);
    return () => {
      d.removeEventListener("cancel", onCancel);
      d.removeEventListener("close", onClosed);
    };
  }, [onClose]);
  return (
    <dialog ref={ref} className={`dialog dialog--${variant} ${className}`} aria-labelledby={title ? titleId : labelledBy}
      style={width ? { width: `min(${width}px, calc(100vw - ${variant === "drawer" ? 0 : 32}px))` } : undefined}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on the backdrop
      }}>
      {open && (
        <>
          {!bare && title && (
            <div className="dialog__head">
              <div>
                <h2 className="dialog__title" id={titleId}>{title}</h2>
                {description && <p className="dialog__desc">{description}</p>}
              </div>
              <IconButton icon={X} label="Close" size="sm" tooltip={false} onClick={onClose} />
            </div>
          )}
          {bare ? children : <div className="dialog__body">{children}</div>}
          {footer && <div className="dialog__foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

/* ---------------------------------------------------------------- Empty state */
export function EmptyState({ icon: Icon, title, children, action }: {
  icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="empty">
      {Icon && <Icon size={20} aria-hidden strokeWidth={1.75} className="empty__icon" />}
      <p className="empty__title">{title}</p>
      {children && <div className="empty__text">{children}</div>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, ...style }} aria-hidden />;
}

/* ---------------------------------------------------------------- Sortable table heading (aria-sort + labelled button) */
export function SortTh<K extends string>({ k, label, sort, onSort, num, className = "" }: {
  k: K; label: string; sort: { key: K; dir: 1 | -1 }; onSort: (k: K) => void; num?: boolean; className?: string;
}) {
  const active = sort.key === k;
  const Icon = !active ? ArrowUpDown : sort.dir === 1 ? ArrowUp : ArrowDown;
  return (
    <th scope="col" className={[num && "num", className].filter(Boolean).join(" ")}
      aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort" onClick={() => onSort(k)}
        aria-label={`Sort by ${label}${active ? (sort.dir === 1 ? ", ascending" : ", descending") : ""}`}>
        {label}
        <Icon size={12} aria-hidden className={active ? "th-sort__icon th-sort__icon--on" : "th-sort__icon"} />
      </button>
    </th>
  );
}
