/** Uppercase mono micro-label, e.g. "SETUP · 2 / 6". */
export function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-label tracking-[0.14em] text-subtle uppercase">
      {children}
    </div>
  );
}
