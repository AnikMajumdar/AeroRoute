interface TfrItem {
  notam_number?: string;
  title?: string;
  summary?: string;
  impact?: string;
  effective_start?: string;
  effective_end?: string;
}

interface LiveRestrictionsCardProps {
  tfrs?: TfrItem[];
  fetchedAt?: string;
  notamConnected?: boolean;
  integrationDisabled?: boolean;
}

function impactLabel(impact?: string): { text: string; className: string } {
  switch (impact) {
    case "intersects":
      return { text: "TFR intersects route corridor", className: "text-red-300" };
    case "nearby":
      return { text: "TFR nearby", className: "text-amber-300" };
    case "unmapped":
      return { text: "TFR geometry unavailable — verify manually", className: "text-amber-200" };
    default:
      return { text: "TFR advisory", className: "text-slate-300" };
  }
}

export function LiveRestrictionsCard({
  tfrs = [],
  fetchedAt,
  notamConnected,
  integrationDisabled = true,
}: LiveRestrictionsCardProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-6" data-testid="live-restrictions-card">
      <h2 className="text-lg font-semibold mb-2">Live Restrictions</h2>

      {integrationDisabled ? (
        <p className="text-sm text-amber-200/90 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3">
          FAA live data (TFRs, NAS delays, NOTAMs) is not connected. Verify all restrictions through official
          sources: 1800WXBRIEF, FAA NOTAM Search, ForeFlight/Garmin.
        </p>
      ) : (
        <>
          <p className="text-xs text-slate-500 mb-4">
            Source: FAA
            {fetchedAt ? ` · fetched ${new Date(fetchedAt).toLocaleString()}` : ""}
            {" · "}
            Educational advisory only.
          </p>

          {!notamConnected && (
            <p className="text-sm text-amber-200/90 mb-4 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3">
              NOTAM integration not connected. Verify NOTAMs through official sources.
            </p>
          )}

          {tfrs.length === 0 ? (
            <p className="text-sm text-slate-400">No active TFRs intersecting or near this route corridor.</p>
          ) : (
            <ul className="space-y-3 text-sm">
              {tfrs.map((tfr) => {
                const label = impactLabel(tfr.impact);
                return (
                  <li key={tfr.notam_number || tfr.title} className="rounded-lg border border-border/60 p-3">
                    <p className={`font-medium ${label.className}`}>{label.text}</p>
                    <p className="mt-1 font-mono text-accent">{tfr.notam_number}</p>
                    <p className="text-slate-300">{tfr.title || tfr.summary}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
