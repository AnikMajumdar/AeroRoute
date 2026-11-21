"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export const HAZARDS_QUESTION =
  "What hazards does this route face based on its winds, weather checkpoints, diversion airports, and runway data? Say clearly which hazard data is missing, since live FAA and aviation weather feeds are not connected.";

interface LiveDataActionsProps {
  /** Sends a question to the copilot (through React state, see RouteCopilot's `prefill`). */
  onAskCopilot: (question: string) => void;
}

export function LiveDataActions({ onAskCopilot }: LiveDataActionsProps) {
  const router = useRouter();

  return (
    <Card padding="p-5" data-testid="live-data-actions">
      <p className="text-sm text-muted">
        Live FAA and aviation weather integrations are disabled. Route planning uses Open-Meteo winds
        and airport data only.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button type="button" variant="secondary" size="sm" onClick={() => router.refresh()}>
          Reload page
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onAskCopilot(HAZARDS_QUESTION)}
          data-testid="ask-copilot-hazards"
        >
          Ask Copilot about hazards
        </Button>
      </div>
    </Card>
  );
}
