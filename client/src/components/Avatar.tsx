import { Link } from "react-router";

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
