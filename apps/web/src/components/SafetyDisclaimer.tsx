export function SafetyDisclaimer({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 ${className}`}
      role="alert"
    >
      <div className="flex gap-3">
        <span className="text-amber-400 text-xl shrink-0" aria-hidden>
          ⚠️
        </span>
        <div>
          <p className="font-semibold text-amber-300">Educational Tool — Not for Operational Use</p>
          <p className="mt-1 text-sm text-amber-200/80">
            AeroRoute is an educational route optimization platform. It is{" "}
            <strong>not</strong> certified flight-planning software. Always verify routes,
            weather, NOTAMs, fuel requirements, and airspace restrictions using official
            sources (FAA, ICAO, operator manuals) before any flight.
          </p>
        </div>
      </div>
    </div>
  );
}
