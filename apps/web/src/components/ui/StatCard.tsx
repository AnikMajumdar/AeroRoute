import { Card } from "./Card";

export function StatCard({
  title,
  value,
  subtitle,
  icon,
  highlight,
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon?: string;
  highlight?: boolean;
}) {
  return (
    <Card
      variant={highlight ? "gradient" : "glass"}
      padding="p-5"
      className={highlight ? "ring-1 ring-sky-400/20" : ""}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{title}</p>
          <p
            className={`mt-2 text-2xl font-bold tracking-tight ${
              highlight ? "gradient-text" : "text-foreground"
            }`}
          >
            {value}
          </p>
          {subtitle && <p className="mt-1.5 text-xs text-muted">{subtitle}</p>}
        </div>
        {icon && (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/5 text-lg">
            {icon}
          </span>
        )}
      </div>
    </Card>
  );
}
