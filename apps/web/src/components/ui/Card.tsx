import { HTMLAttributes, ReactNode } from "react";

type CardVariant = "default" | "glass" | "gradient" | "elevated";

const variantClasses: Record<CardVariant, string> = {
  default: "bg-card/80 border-border/80",
  glass: "glass-card",
  gradient: "glass-card border-sky-500/20 bg-gradient-to-br from-sky-500/5 via-card/40 to-indigo-500/5",
  elevated: "bg-card border-border/60 shadow-card",
};

export function Card({
  children,
  className = "",
  variant = "glass",
  hover = false,
  padding = "p-6",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  variant?: CardVariant;
  hover?: boolean;
  padding?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, "className" | "children">) {
  // `rest` forwards data-* / aria-* attributes (e.g. data-testid) that Playwright and assistive tech rely on.
  return (
    <div
      {...rest}
      className={`rounded-2xl border ${variantClasses[variant]} ${padding} ${
        hover ? "transition-all duration-300 hover:border-sky-400/30 hover:shadow-glow-sm hover:-translate-y-0.5" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
