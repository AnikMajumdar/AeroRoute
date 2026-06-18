"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { api, CopilotChatResponse } from "@/lib/api";

const DEFAULT_SUGGESTED_QUESTIONS = [
  "Why was this route selected?",
  "What are the biggest risks?",
  "Are departure and destination runways long enough for this aircraft?",
  "What fuel price was used and what is the total fuel cost?",
];

interface RouteCopilotProps {
  routeId: string;
}

export function RouteCopilot({ routeId }: RouteCopilotProps) {
  const { userId } = useAuth();
  const e2eUserId =
    process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true" ? "e2e-test-user" : null;
  const activeUserId = userId || e2eUserId;

  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>(DEFAULT_SUGGESTED_QUESTIONS);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<CopilotChatResponse | null>(null);

  useEffect(() => {
    api.getCopilotStatus().then((s) => {
      setEnabled(s.enabled);
      setModel(s.model ?? null);
    }).catch(() => setEnabled(false));

    if (activeUserId) {
      api
        .getCopilotSuggestions(routeId, activeUserId)
        .then((s) => {
          if (s.suggested_questions?.length) {
            setSuggestedQuestions(s.suggested_questions);
          }
        })
        .catch(() => {});
    }
  }, [routeId, activeUserId]);

  const ask = useCallback(
    async (q: string) => {
      if (!activeUserId || !q.trim()) return;
      setLoading(true);
      setError("");
      setResponse(null);
      try {
        const result = await api.copilotChat(routeId, q.trim(), activeUserId);
        setResponse(result);
        setQuestion("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Copilot request failed");
      } finally {
        setLoading(false);
      }
    },
    [activeUserId, routeId]
  );

  return (
    <div
      className="rounded-xl border border-violet-500/20 bg-gradient-to-br from-card via-card to-violet-950/20 p-6 mb-8 shadow-lg shadow-violet-950/20"
      data-testid="route-copilot"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 text-lg">
            ✦
          </div>
          <div>
            <h2 className="text-lg font-semibold">AeroRoute Copilot</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Powered by Gemini · answers from this route&apos;s data only
            </p>
            {model && enabled && (
              <p className="text-xs text-slate-500 mt-1 font-mono">{model}</p>
            )}
          </div>
        </div>
        {enabled === true && (
          <span className="shrink-0 rounded-full bg-green-500/20 px-2.5 py-1 text-xs text-green-300">
            Online
          </span>
        )}
        {enabled === false && (
          <span className="shrink-0 rounded-full bg-slate-700 px-2.5 py-1 text-xs text-slate-400">
            Offline
          </span>
        )}
      </div>

      {enabled === null && (
        <p className="text-sm text-slate-500 animate-pulse">Checking copilot status...</p>
      )}

      {enabled === false && (
        <div className="rounded-lg border border-border bg-slate-900/50 p-4 text-sm text-slate-400">
          <p>
            Add <code className="text-accent">GEMINI_API_KEY</code> and{" "}
            <code className="text-accent">COPILOT_ENABLED=true</code> to{" "}
            <code className="text-xs">apps/api/.env</code>, then restart the API.
          </p>
        </div>
      )}

      {enabled === true && (
        <>
          <div className="flex flex-wrap gap-2 mb-4">
            {suggestedQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void ask(q)}
                disabled={loading}
                className="rounded-full border border-violet-500/20 bg-violet-500/5 px-3 py-1.5 text-xs text-slate-300 hover:border-violet-400/40 hover:bg-violet-500/10 hover:text-violet-200 disabled:opacity-50 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(question);
            }}
            className="flex gap-2"
          >
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about this route..."
              disabled={loading}
              className="flex-1 rounded-lg border border-border bg-slate-900/80 px-4 py-2.5 text-sm focus:border-violet-400/50 focus:outline-none focus:ring-1 focus:ring-violet-400/30 disabled:opacity-50"
              data-testid="copilot-input"
            />
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="rounded-lg bg-violet-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-400 disabled:opacity-50 transition-colors"
              data-testid="copilot-submit"
            >
              {loading ? "Thinking..." : "Ask"}
            </button>
          </form>
        </>
      )}

      {error && (
        <div
          className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          data-testid="copilot-error"
        >
          {error}
        </div>
      )}

      {response && (
        <div className="mt-4 space-y-3" data-testid="copilot-response">
          <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4 text-sm leading-relaxed text-slate-200">
            {response.answer}
          </div>
          <p className="text-xs text-amber-300/90 border border-amber-500/30 rounded-lg p-3">
            {response.safety_note}
          </p>
          <p className="text-xs text-slate-500">
            Sources: {response.sources_used.join(", ")}
          </p>
        </div>
      )}

      <p className="mt-4 text-xs text-slate-500">
        Educational tool only — not for operational flight planning.
      </p>
    </div>
  );
}
