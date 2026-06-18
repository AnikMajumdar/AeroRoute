import { Card, CardHeader } from "@/components/ui/Card";

interface HazardsCardProps {
  integrationDisabled?: boolean;
}

export function HazardsCard({ integrationDisabled = true }: HazardsCardProps) {
  return (
    <Card data-testid="hazards-card" padding="p-6">
      <CardHeader title="Hazards" subtitle="SIGMETs, AIRMETs, and PIREPs" />
      {integrationDisabled ? (
        <p className="rounded-xl border border-sky-500/20 bg-sky-500/[0.06] p-4 text-sm leading-relaxed text-sky-100/80">
          Aviation weather hazard integration is not connected. Verify weather through official
          briefings before any flight.
        </p>
      ) : null}
    </Card>
  );
}
