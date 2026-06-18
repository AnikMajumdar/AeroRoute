import { Card } from "@/components/ui/Card";

export function ConusNotice({ className = "" }: { className?: string }) {
  return (
    <Card variant="gradient" className={`border-sky-500/20 ${className}`} padding="p-5">
      <div className="flex gap-4">
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 text-lg"
          aria-hidden
        >
          🇺🇸
        </span>
        <div>
          <p className="font-semibold text-sky-200">Continental U.S. routes only</p>
          <p className="mt-1.5 text-sm leading-relaxed text-sky-100/70">
            Departure and destination are limited to the continental United States. Only medium and
            large airports with US ICAO codes are available for planning.
          </p>
        </div>
      </div>
    </Card>
  );
}
