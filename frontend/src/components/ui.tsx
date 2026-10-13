import type { ReactNode } from "react";

export function Section({ title, children, right, open = true }: { title: string; children: ReactNode; right?: ReactNode; open?: boolean }) {
  return (
    <details className="section" open={open}>
      <summary>
        <span>{title}</span>
        {right}
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

export function Num({ label, value, onChange, step = 1, min, max, unit, title }: {
  label: string; value: number | null | undefined; onChange: (v: number | null) => void; step?: number; min?: number; max?: number; unit?: string; title?: string;
}) {
  return (
    <label className="field" title={title}>
      <span>{label}</span>
      <span className="with-unit">
        <input
          type="number"
          value={value ?? ""}
          step={step}
          min={min}
          max={max}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
        {unit && <em>{unit}</em>}
      </span>
    </label>
  );
}

export function Txt({ label, value, onChange, area }: { label: string; value: string; onChange: (v: string) => void; area?: boolean }) {
  return (
    <label className="field">
      <span>{label}</span>
      {area ? <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={3} /> : <input value={value} onChange={(e) => onChange(e.target.value)} />}
    </label>
  );
}

export function Sel({ label, value, options, onChange, allowEmpty }: {
  label?: string; value: string | null | undefined; options: { value: string; label: string }[]; onChange: (v: string) => void; allowEmpty?: string;
}) {
  const sel = (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {allowEmpty !== undefined && <option value="">{allowEmpty}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
  if (!label) return sel;
  return (
    <label className="field">
      <span>{label}</span>
      {sel}
    </label>
  );
}

export function Check({ label, checked, onChange, title }: { label: string; checked: boolean; onChange: (v: boolean) => void; title?: string }) {
  return (
    <label className="check" title={title}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {label}
    </label>
  );
}

export function MultiCheck({ options, value, onChange }: { options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="multicheck">
      {options.map((o) => (
        <label key={o.value} className="check">
          <input
            type="checkbox"
            checked={value.includes(o.value)}
            onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((x) => x !== o.value))}
          />
          {o.label}
        </label>
      ))}
      {!options.length && <span className="muted">none available</span>}
    </div>
  );
}

export function Kpi({ label, value, unit, warn, title }: { label: string; value: string; unit?: string; warn?: boolean; title?: string }) {
  return (
    <div className={`kpi ${warn ? "warn" : ""}`} title={title}>
      <div className="kpi-v">
        {value}
        {unit && <small> {unit}</small>}
      </div>
      <div className="kpi-l">{label}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
