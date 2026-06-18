export function SafetyDisclaimer({ className = "" }: { className?: string }) {
  return (
    <div
      className={`glass-card rounded-2xl border-amber-500/25 bg-amber-500/[0.06] p-5 ${className}`}
      role="alert"
    >
      <div className="flex gap-4">
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-lg"
          aria-hidden
        >
          ⚠
        </span>
        <div>
          <p className="font-semibold text-amber-200">Educational tool — not for operational use</p>
          <p className="mt-1.5 text-sm leading-relaxed text-amber-100/75">
            AeroRoute is an educational route optimization platform. It is{" "}
            <strong className="text-amber-100">not</strong> certified flight-planning software.
            Always verify routes, weather, NOTAMs, fuel, and airspace through official FAA briefings,
            ForeFlight/Garmin, POH, and pilot judgment before any flight.
          </p>
        </div>
      </div>
    </div>
  );
}
