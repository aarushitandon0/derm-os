import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { href } from "../router";
import { Icon, type IconName } from "./Icon";

export function Wordmark({ size = "md" }: { size?: "md" | "lg" | "xl" }) {
  return (
    <span className={`wordmark wordmark--${size}`} aria-label="derm os">
      derm<span className="wordmark__slash">//</span>os
    </span>
  );
}

/** iOS-style navigation row: back chevron (or custom left), optional centre and right items. */
export function NavBar({
  back,
  left,
  center,
  right,
}: {
  back?: string | null;
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <header className="navbar no-print">
      <div className="navbar__side">
        {left ??
          (back ? (
            <a className="iconbtn" href={href(back)} aria-label="Back">
              <Icon name="back" />
            </a>
          ) : null)}
      </div>
      <div className="navbar__center">{center}</div>
      <div className="navbar__side navbar__side--end">{right}</div>
    </header>
  );
}

/** Kept for the screens that already use it. The title now lives in the page head. */
export function TopBar({ back = "/" }: { back?: string | null; title?: string }) {
  return <NavBar back={back} />;
}

/** Serif title with a small grey subtitle underneath, as on every template screen. */
export function PageHead({ eyebrow, title, lede }: { eyebrow?: string; title: ReactNode; lede?: ReactNode }) {
  return (
    <div className="pagehead">
      <h1 className="title">{title}</h1>
      {eyebrow && <p className="subtitle subtitle--meta">{eyebrow}</p>}
      {lede && <p className="subtitle">{lede}</p>}
    </div>
  );
}

export function Section({ label, children, aside }: { label: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="section">
      <div className="section__head">
        <h2 className="section__label">{label}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Btn({
  children,
  onClick,
  kind = "primary",
  disabled,
  to,
  type = "button",
  wide,
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: "primary" | "ghost" | "quiet" | "danger";
  disabled?: boolean;
  to?: string;
  type?: "button" | "submit";
  wide?: boolean;
  icon?: IconName;
}) {
  const cls = `btn btn--${kind}${wide ? " btn--wide" : ""}`;
  const inner = (
    <>
      <span>{children}</span>
      {icon && <Icon name={icon} size={18} />}
    </>
  );
  if (to && !disabled)
    return (
      <a className={cls} href={href(to)}>
        {inner}
      </a>
    );
  return (
    <button className={cls} type={type} onClick={onClick} disabled={disabled}>
      {inner}
    </button>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "stop"; children: ReactNode }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "stop" ? "alert" : undefined}>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="loading__dot" aria-hidden />
      {label}
    </div>
  );
}

export function PreparedTag() {
  return <span className="tag tag--prepared">Prepared data</span>;
}

/** Segmented control acting as tabs. Arrow keys move between tabs. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  idBase,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  idBase: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + options.length) % options.length;
    onChange(options[n].value);
    refs.current[n]?.focus();
  };
  return (
    <div className="segmented" role="tablist" aria-label={label}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => (refs.current[i] = el)}
          role="tab"
          id={`${idBase}-tab-${o.value}`}
          aria-controls={`${idBase}-panel-${o.value}`}
          aria-selected={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          className={`segmented__opt${o.value === value ? " is-on" : ""}`}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ idBase, value, children }: { idBase: string; value: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idBase}-panel-${value}`} aria-labelledby={`${idBase}-tab-${value}`} className="tabpanel">
      {children}
    </div>
  );
}

/** A tappable row: line icon, title, grey subline, chevron. Used for lists of choices and links. */
export function RowLink({
  to,
  onClick,
  icon,
  title,
  sub,
  trailing,
  selected,
  radio,
}: {
  to?: string;
  onClick?: () => void;
  icon?: IconName | ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  trailing?: ReactNode;
  selected?: boolean;
  /** Render as a radio option (inside a role="radiogroup"). */
  radio?: boolean;
}) {
  const body = (
    <>
      {icon && <span className="row__icon">{typeof icon === "string" ? <Icon name={icon as IconName} /> : icon}</span>}
      <span className="row__body">
        <span className="row__title">{title}</span>
        {sub && <span className="row__sub">{sub}</span>}
      </span>
      <span className="row__trail">{trailing ?? (to ? <Icon name="chevron" size={18} /> : null)}</span>
    </>
  );
  const cls = `row${selected ? " is-selected" : ""}`;
  if (!to && !onClick) return <div className="row row--static">{body}</div>;
  if (to)
    return (
      <a className={cls} href={href(to)}>
        {body}
      </a>
    );
  return (
    <button
      type="button"
      className={cls}
      onClick={onClick}
      role={radio ? "radio" : undefined}
      aria-checked={radio ? !!selected : undefined}
      aria-pressed={radio ? undefined : selected}
    >
      {body}
    </button>
  );
}

/** Shown on any product whose ingredient list is incomplete, whatever its exclusion status. */
export function IncompleteTag() {
  return <span className="tag tag--unknown">Ingredient list incomplete</span>;
}
