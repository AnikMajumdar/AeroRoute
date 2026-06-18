import { Card, CardHeader } from "@/components/ui/Card";

interface LiveRestrictionsCardProps {
  integrationDisabled?: boolean;
}

export function LiveRestrictionsCard({ integrationDisabled = true }: LiveRestrictionsCardProps) {
  return (
    <Card data-testid="live-restrictions-card" padding="p-6">
      <CardHeader
        title="Live restrictions"
        subtitle="FAA TFRs, NAS delays, and NOTAMs"
      />
      {integrationDisabled ? (
        <p className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 text-sm leading-relaxed text-amber-100/80">
          FAA live data is not connected. Verify all restrictions through official sources:
          1800WXBRIEF, FAA NOTAM Search, ForeFlight/Garmin.
        </p>
      ) : null}
    </Card>
  );
}
