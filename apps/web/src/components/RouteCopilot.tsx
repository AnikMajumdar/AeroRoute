"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { api, CopilotChatResponse } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

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
  const { userId, getToken } = useAuth();
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
      void (async () => {
        try {
          const token = await getToken();
          const s = await api.getCopilotSuggestions(routeId, activeUserId, token);
          if (s.suggested_questions?.length) {
            setSuggestedQuestions(s.suggested_questions);
          }
        } catch {
          // ignore
        }
      })();
    }
  }, [routeId, activeUserId, getToken]);

  const ask = useCallback(
    async (q: string) => {
      if (!activeUserId || !q.trim()) return;
      setLoading(true);
      setError("");
      setResponse(null);
      try {
        const token = await getToken();
        const result = await api.copilotChat(routeId, q.trim(), activeUserId, token);
        setResponse(result);
        setQuestion("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Copilot request failed");
      } finally {
        setLoading(false);
      }
    },
    [activeUserId, routeId, getToken]
  );

  return (
    <Card
      className="mb-8 border-violet-500/20 bg-gradient-to-br from-violet-500/[0.08] via-transparent to-indigo-500/[0.06] shadow-glow-sm"
      padding="p-6"
      data-testid="route-copilot"
    >
      <CardHeader
        title="AeroRoute Copilot"
        subtitle="Powered by Gemini · answers from this route's data only"
        action={
          enabled === true ? (
            <Badge tone="success">Online</Badge>
          ) : enabled === false ? (
            <Badge tone="muted">Offline</Badge>
          ) : null
        }
      />
      {model && enabled && (
        <p className="-mt-3 mb-4 font-mono text-xs text-muted">{model}</p>
      )}

      {enabled === null && (
        <p className="animate-pulse text-sm text-muted">Checking copilot status...</p>
      )}

      {enabled === false && (
        <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-muted">
          <p>
            Add <code className="text-sky-300">GEMINI_API_KEY</code> and{" "}
            <code className="text-sky-300">COPILOT_ENABLED=true</code> to{" "}
            <code className="text-xs">apps/api/.env</code>, then restart the API.
          </p>
        </div>
      )}

      {enabled === true && (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {suggestedQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void ask(q)}
                disabled={loading}
                className="rounded-full border border-violet-500/25 bg-violet-500/10 px-3 py-1.5 text-xs text-violet-100/90 transition-colors hover:border-violet-400/40 hover:bg-violet-500/15 disabled:opacity-50"
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
            <Input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about this route..."
              disabled={loading}
              className="flex-1 border-violet-500/20 focus:border-violet-400/50 focus:ring-violet-400/20"
              data-testid="copilot-input"
            />
            <Button
              type="submit"
              disabled={loading || !question.trim()}
              className="!bg-gradient-to-r !from-violet-500 !to-indigo-500 !text-white shrink-0"
              data-testid="copilot-submit"
            >
              {loading ? "Thinking..." : "Ask"}
            </Button>
          </form>
        </>
      )}

      {error && (
        <div
          className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          data-testid="copilot-error"
        >
          {error}
        </div>
      )}

      {response && (
        <div className="mt-4 space-y-3" data-testid="copilot-response">
          <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4 text-sm leading-relaxed">
            {response.answer}
          </div>
          <p className="rounded-xl border border-amber-500/25 bg-amber-500/[0.06] p-3 text-xs text-amber-100/80">
            {response.safety_note}
          </p>
          <p className="text-xs text-muted">Sources: {response.sources_used.join(", ")}</p>
        </div>
      )}

      <p className="mt-4 text-xs text-muted">
        Educational tool only — not for operational flight planning.
      </p>
    </Card>
  );
}
