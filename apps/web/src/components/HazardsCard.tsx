interface HazardItem {
  hazard_type?: string;
  severity?: string;
  summary?: string;
  intersects_route?: boolean;
  latitude?: number;
  longitude?: number;
}

interface HazardsCardProps {
  hazards?: HazardItem[];
  fetchedAt?: string;
  integrationDisabled?: boolean;
}

export function HazardsCard({ hazards = [], fetchedAt, integrationDisabled = true }: HazardsCardProps) {
  if (integrationDisabled) {
    return (
      <div className="rounded-xl border border-border bg-card p-6" data-testid="hazards-card">
        <h2 className="text-lg font-semibold mb-2">Hazards</h2>
        <p className="text-sm text-amber-200/90 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3">
          Aviation weather hazard integration (METAR/TAF, PIREPs, SIGMETs, AIRMETs) is not connected. Verify
          weather through official briefings before any flight.
        </p>
      </div>
    );
  }

  const sigmets = hazards.filter((h) => String(h.hazard_type || "").toLowerCase().includes("sigmet"));
  const airmets = hazards.filter(
    (h) => String(h.hazard_type || "").toLowerCase().includes("airmet") || h.hazard_type === "gairmet"
  );
  const pireps = hazards.filter((h) => h.hazard_type === "pirep");

  return (
    <div className="rounded-xl border border-border bg-card p-6" data-testid="hazards-card">
      <h2 className="text-lg font-semibold mb-2">Hazards</h2>
      <p className="text-xs text-slate-500 mb-4">
        Source: AviationWeather.gov
        {fetchedAt ? ` · fetched ${new Date(fetchedAt).toLocaleString()}` : ""}
        {" · "}
        Advisory only.
      </p>

      {hazards.length === 0 ? (
        <p className="text-sm text-slate-400">No SIGMETs, AIRMETs, or route-relevant PIREPs in current snapshot.</p>
      ) : (
        <div className="space-y-4 text-sm">
          {sigmets.length > 0 && (
            <section>
              <h3 className="font-medium text-red-300 mb-2">SIGMETs ({sigmets.length})</h3>
              <ul className="space-y-2">
                {sigmets.map((h, i) => (
                  <li key={`sig-${i}`} className="rounded border border-red-500/20 bg-red-500/5 p-2">
                    {h.intersects_route && <span className="text-red-300 text-xs">Intersects route · </span>}
                    {h.summary}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {airmets.length > 0 && (
            <section>
              <h3 className="font-medium text-amber-300 mb-2">AIRMETs / G-AIRMETs ({airmets.length})</h3>
              <ul className="space-y-2">
                {airmets.map((h, i) => (
                  <li key={`air-${i}`} className="rounded border border-amber-500/20 bg-amber-500/5 p-2">
                    {h.summary}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {pireps.length > 0 && (
            <section>
              <h3 className="font-medium text-sky-300 mb-2">PIREPs near route ({pireps.length})</h3>
              <ul className="space-y-2">
                {pireps.map((h, i) => (
                  <li key={`pirep-${i}`} className="rounded border border-sky-500/20 bg-sky-500/5 p-2">
                    {h.summary}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
