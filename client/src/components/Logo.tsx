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
