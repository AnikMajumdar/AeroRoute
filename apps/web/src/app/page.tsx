import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { ConusNotice } from "@/components/ConusNotice";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";

const FEATURES = [
  {
    title: "Altitude-Aware Winds",
    desc: "GFS pressure-level winds at cruise altitude adjust groundspeed, ETE, and fuel — with surface fallback when needed.",
    icon: "🌬️",
  },
  {
    title: "Fuel & Performance Model",
    desc: "Climb, cruise, descent, and reserve fuel planning with margin warnings (educational estimates).",
    icon: "⛽",
  },
  {
    title: "Route Scoring",
    desc: "Normalized 0–100 scores across time, fuel, weather, delays, and diversions with route preferences.",
    icon: "📊",
  },
  {
    title: "En-Route Weather",
    desc: "METAR checkpoints along your route with VFR/MVFR/IFR/LIFR classification and segment penalties.",
    icon: "🌦️",
  },
  {
    title: "PostGIS Diversions",
    desc: "Corridor-based diversion airport search filtered by runway length and airport type.",
    icon: "🛬",
  },
  {
    title: "AeroRoute Copilot",
    desc: "Deterministic briefings today; AI-assisted Q&A coming soon — always with safety disclaimers.",
    icon: "🤖",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
      <header className="border-b border-border/60 bg-card/30 backdrop-blur-md sticky top-0 z-50">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-2">
            <span className="text-2xl">✈️</span>
            <span className="text-xl font-bold tracking-tight text-accent">AeroRoute</span>
          </div>
          <div className="flex items-center gap-3">
            <SignedOut>
              <SignInButton mode="modal">
                <button className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-card transition-colors">
                  Sign In
                </button>
              </SignInButton>
              <SignUpButton mode="modal">
                <button className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent/90 transition-colors">
                  Sign Up
                </button>
              </SignUpButton>
            </SignedOut>
            <SignedIn>
              <Link
                href="/dashboard"
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent/90 transition-colors"
              >
                Dashboard
              </Link>
              <UserButton afterSignOutUrl="/" />
            </SignedIn>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-sky-900/20 via-transparent to-transparent" />
          <div className="relative mx-auto max-w-6xl px-4 py-24 text-center">
            <p className="text-sm font-medium uppercase tracking-widest text-accent/80 mb-4">
              Educational Flight Planning
            </p>
            <h1 className="text-5xl md:text-6xl font-bold tracking-tight">
              Smarter Routes,
              <br />
              <span className="bg-gradient-to-r from-sky-300 to-cyan-400 bg-clip-text text-transparent">
                Real Aviation Data
              </span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-400">
              Compare primary and alternate routes with cruise-altitude winds, fuel planning,
              en-route weather checkpoints, and diversion corridors — built for learning, not
              dispatch.
            </p>
            <div className="mx-auto mt-6 max-w-2xl">
              <ConusNotice />
            </div>
            <div className="mt-10 flex flex-wrap justify-center gap-4">
              <SignedIn>
                <Link
                  href="/routes/new"
                  className="rounded-xl bg-accent px-8 py-3.5 font-semibold text-slate-900 shadow-lg shadow-sky-500/20 hover:bg-accent/90 transition-colors"
                >
                  Plan a Route
                </Link>
              </SignedIn>
              <SignedOut>
                <SignUpButton mode="modal">
                  <button className="rounded-xl bg-accent px-8 py-3.5 font-semibold text-slate-900 shadow-lg shadow-sky-500/20 hover:bg-accent/90 transition-colors">
                    Get Started Free
                  </button>
                </SignUpButton>
              </SignedOut>
              <Link
                href="#features"
                className="rounded-xl border border-border px-8 py-3.5 font-semibold hover:bg-card/50 transition-colors"
              >
                Explore Features
              </Link>
            </div>

            <div className="mx-auto mt-16 max-w-4xl rounded-2xl border border-border/60 bg-card/40 p-2 shadow-2xl backdrop-blur-sm">
              <div className="rounded-xl bg-slate-900/80 p-8 text-left">
                <div className="flex items-center gap-3 mb-6">
                  <div className="h-3 w-3 rounded-full bg-red-400/80" />
                  <div className="h-3 w-3 rounded-full bg-amber-400/80" />
                  <div className="h-3 w-3 rounded-full bg-green-400/80" />
                  <span className="ml-2 text-xs text-slate-500 font-mono">KJFK → KLAX · Cirrus SR22</span>
                </div>
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div className="rounded-lg bg-slate-800/50 p-4">
                    <p className="text-2xl font-bold text-accent">2,145</p>
                    <p className="text-xs text-slate-400">NM</p>
                  </div>
                  <div className="rounded-lg bg-slate-800/50 p-4">
                    <p className="text-2xl font-bold text-accent">11h 42m</p>
                    <p className="text-xs text-slate-400">ETE (wind-adjusted)</p>
                  </div>
                  <div className="rounded-lg bg-slate-800/50 p-4">
                    <p className="text-2xl font-bold text-accent">82</p>
                    <p className="text-xs text-slate-400">Route score</p>
                  </div>
                </div>
                <div className="mt-4 h-2 rounded-full bg-slate-800 overflow-hidden">
                  <div className="h-full w-3/4 bg-gradient-to-r from-sky-500 to-cyan-400 rounded-full" />
                </div>
                <p className="mt-3 text-xs text-slate-500 text-center">
                  Illustrative preview — not a live flight plan
                </p>
              </div>
            </div>
          </div>
        </section>

        <section id="features" className="border-t border-border/60 py-20">
          <div className="mx-auto max-w-6xl px-4">
            <h2 className="text-center text-3xl font-bold mb-4">Built for Aviation Learners</h2>
            <p className="text-center text-slate-400 mb-12 max-w-2xl mx-auto">
              Real data sources, transparent scoring, and clear limitations — so you understand
              how route planning works without mistaking this for certified software.
            </p>
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <div
                  key={f.title}
                  className="rounded-xl border border-border/60 bg-card/50 p-6 hover:border-accent/30 transition-colors"
                >
                  <span className="text-2xl">{f.icon}</span>
                  <h3 className="mt-3 text-lg font-semibold text-accent">{f.title}</h3>
                  <p className="mt-2 text-sm text-slate-400">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-4xl px-4 py-12">
          <SafetyDisclaimer />
        </section>
      </main>

      <footer className="border-t border-border/60 py-8 text-center text-sm text-slate-500">
        AeroRoute — Educational use only. Not for operational flight planning.
      </footer>
    </div>
  );
}
