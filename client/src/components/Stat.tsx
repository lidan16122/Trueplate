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
