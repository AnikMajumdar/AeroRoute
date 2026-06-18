"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface LiveDataActionsProps {
  routeId: string;
  userId: string;
}

export function LiveDataActions({ routeId: _routeId, userId: _userId }: LiveDataActionsProps) {
  const router = useRouter();

  function askCopilotHazards() {
    const el = document.querySelector<HTMLInputElement>("[data-testid='copilot-input']");
    if (el) {
      el.value =
        "What weather and restriction data is available for this route? Note that live FAA and aviation weather APIs are not connected.";
      el.focus();
    }
  }

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
        <Button type="button" variant="outline" size="sm" onClick={askCopilotHazards}>
          Ask Copilot about hazards
        </Button>
      </div>
    </Card>
  );
}
