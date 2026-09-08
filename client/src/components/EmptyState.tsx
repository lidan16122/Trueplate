export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-dashed border-hairline px-5 py-8 text-center">
      <div className="text-caption font-medium text-ink">{title}</div>
      <div className="text-caption leading-relaxed text-subtle">{body}</div>
    </div>
  );
}
