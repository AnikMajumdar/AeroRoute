type BadgeTone = "default" | "success" | "warning" | "danger" | "accent" | "muted";

const tones: Record<BadgeTone, string> = {
  default: "bg-white/10 text-slate-200 border-white/10",
  success: "bg-emerald-500/15 text-emerald-300 border-emerald-500/25",
  warning: "bg-amber-500/15 text-amber-300 border-amber-500/25",
  danger: "bg-red-500/15 text-red-300 border-red-500/25",
  accent: "bg-sky-500/15 text-sky-300 border-sky-500/25",
  muted: "bg-slate-700/50 text-slate-300 border-slate-600/50",
};

export function Badge({
  children,
  tone = "default",
  className = "",
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium tracking-wide ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
