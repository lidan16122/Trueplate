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
