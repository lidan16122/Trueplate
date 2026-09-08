

export function NameField({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-[7px]">
      <span className="text-caption text-muted">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-[50px] w-full min-w-0 rounded-card border border-line bg-surface px-3.5 text-lead text-ink outline-none focus:border-accent"
      />
    </label>
  );
}
