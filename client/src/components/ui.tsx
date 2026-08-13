/** Small primitives shared across screens, built from the design's tokens. */

import { Link } from "react-router";

import { percentOf } from "@/lib/format";

/** The rounded-square "T" mark. */
export function Logo({ size = 44 }: { size?: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-card bg-ink font-bold text-white"
      style={{ width: size, height: size, fontSize: size * 0.43 }}
    >
      T
    </div>
  );
}

export function PrimaryButton({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`flex items-center justify-center gap-3 rounded-lg bg-ink font-semibold text-white transition-colors hover:bg-accent disabled:opacity-35 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

/** Uppercase mono micro-label, e.g. "SETUP · 2 / 6". */
export function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-label tracking-[0.14em] text-subtle uppercase">
      {children}
    </div>
  );
}

/** A big number. Always mono — every figure in this app is. */
export function Stat({
  value,
  size = 44,
  className = "",
}: {
  value: string;
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={`tabular font-mono leading-none font-medium tracking-[-0.04em] text-ink ${className}`}
      style={{ fontSize: size }}
    >
      {value}
    </div>
  );
}

export function ProgressBar({
  value,
  total,
  height = 6,
}: {
  value: number;
  total: number | null | undefined;
  height?: number;
}) {
  return (
    <div
      className="overflow-hidden rounded-bar bg-fill"
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemax={total ?? undefined}
    >
      <div className="h-full bg-accent" style={{ width: percentOf(value, total) }} />
    </div>
  );
}

/**
 * "Fairly sure" / "Rough guess".
 *
 * Two states rather than a percentage: a number like "0.62 confidence" is not
 * something a person can act on, but "rough guess — tap to correct" is.
 */
export function ConfidenceChip({ label, isRough }: { label: string; isRough: boolean }) {
  return (
    <span className={`text-label ${isRough ? "text-warn" : "text-accent"}`}>{label}</span>
  );
}

export function Avatar({ initials, to = "/profile" }: { initials: string; to?: string }) {
  return (
    <Link
      to={to}
      className="flex h-[38px] w-[38px] items-center justify-center rounded-full bg-ink text-body font-semibold text-white"
      aria-label="Profile"
    >
      {initials}
    </Link>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-dashed border-hairline px-5 py-8 text-center">
      <div className="text-[15px] font-medium text-ink">{title}</div>
      <div className="text-caption leading-relaxed text-subtle">{body}</div>
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-warn/30 bg-warn/5 px-4 py-3 text-caption text-warn">
      {children}
    </div>
  );
}
