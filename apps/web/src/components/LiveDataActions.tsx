"use client";

import { useRouter } from "next/navigation";

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
    <div className="flex flex-wrap gap-2 items-center" data-testid="live-data-actions">
      <p className="text-sm text-slate-400 w-full">
        Live FAA and aviation weather integrations are disabled. Route planning uses Open-Meteo winds and airport
        data only.
      </p>
      <button
        type="button"
        onClick={() => router.refresh()}
        className="rounded-lg border border-border bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700"
      >
        Reload Page
      </button>
      <button
        type="button"
        onClick={askCopilotHazards}
        className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm text-accent hover:bg-accent/20"
      >
        Ask Copilot About Hazards
      </button>
    </div>
  );
}
