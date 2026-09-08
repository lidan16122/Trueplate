export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-warn/30 bg-warn/5 px-4 py-3 text-caption text-warn">
      {children}
    </div>
  );
}
