import { InputHTMLAttributes, forwardRef } from "react";

export const inputClassName =
  "w-full rounded-xl border border-border/80 bg-white/[0.03] px-4 py-3 text-foreground placeholder:text-slate-500 transition-colors focus:border-sky-400/50 focus:bg-white/[0.05] focus:outline-none focus:ring-2 focus:ring-sky-400/20";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${inputClassName} ${className}`} {...props} />;
  }
);

export function Label({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <label className={`mb-2 block text-sm font-medium text-slate-300 ${className}`}>{children}</label>
  );
}
