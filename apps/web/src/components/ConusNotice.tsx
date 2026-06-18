export function ConusNotice({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg border border-sky-500/40 bg-sky-500/10 p-4 ${className}`}
      role="note"
    >
      <div className="flex gap-3">
        <span className="text-sky-300 text-xl shrink-0" aria-hidden>
          🇺🇸
        </span>
        <div>
          <p className="font-semibold text-sky-200">Continental U.S. routes only</p>
          <p className="mt-1 text-sm text-sky-100/80">
            Departure and destination airports are limited to the continental United States
            (lower 48). Only medium and large airports with US ICAO codes and routine METAR/TAF
            weather reporting are available for planning.
          </p>
        </div>
      </div>
    </div>
  );
}
