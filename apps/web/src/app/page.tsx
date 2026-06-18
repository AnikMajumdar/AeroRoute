import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { ConusNotice } from "@/components/ConusNotice";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

const FEATURES = [
  {
    title: "Altitude-Aware Winds",
    desc: "GFS pressure-level winds at cruise altitude adjust groundspeed, ETE, and fuel estimates.",
    icon: "🌬️",
    gradient: "from-sky-500/20 to-cyan-500/5",
  },
  {
    title: "Fuel & Performance",
    desc: "Climb, cruise, descent, and reserve fuel with margin warnings — educational estimates only.",
    icon: "⛽",
    gradient: "from-amber-500/20 to-orange-500/5",
  },
  {
    title: "Route Scoring",
    desc: "Normalized 0–100 scores across time, fuel, weather, delays, and diversions.",
    icon: "📊",
    gradient: "from-violet-500/20 to-purple-500/5",
  },
  {
    title: "Diversion Planning",
    desc: "PostGIS corridor search for alternate airports filtered by runway and type.",
    icon: "🛬",
    gradient: "from-emerald-500/20 to-teal-500/5",
  },
  {
    title: "Route Variants",
    desc: "Compare direct, offset, diversion, and weather-checkpoint candidates side by side.",
    icon: "🗺️",
    gradient: "from-indigo-500/20 to-blue-500/5",
  },
  {
    title: "AeroRoute Copilot",
    desc: "AI-assisted Q&A from your route context — always with safety disclaimers.",
    icon: "✦",
    gradient: "from-fuchsia-500/20 to-pink-500/5",
  },
];

function LandingHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-400/20 to-indigo-500/20 ring-1 ring-white/10">
            <span className="text-lg">✈</span>
          </span>
          <span className="text-xl font-bold tracking-tight">
            <span className="gradient-text">Aero</span>
            <span className="text-foreground">Route</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <SignedOut>
            <SignInButton mode="modal">
              <button className="nav-link px-3 py-2">Sign In</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <Button size="sm">Get Started</Button>
            </SignUpButton>
          </SignedOut>
          <SignedIn>
            <ButtonLink href="/dashboard" size="sm">
              Dashboard
            </ButtonLink>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
        </div>
      </div>
    </header>
  );
}

export default function LandingPage() {
  return (
    <div className="mesh-bg min-h-screen">
      <LandingHeader />

      <main>
        <section className="relative overflow-hidden px-4 pb-20 pt-16 sm:px-6 sm:pt-24">
          <div className="pointer-events-none absolute left-1/2 top-20 h-72 w-72 -translate-x-1/2 rounded-full bg-sky-500/20 blur-[100px]" />
          <div className="relative mx-auto max-w-5xl text-center animate-slide-up">
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-500/10 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.2em] text-sky-300">
              Educational flight planning
            </p>
            <h1 className="text-5xl font-bold tracking-tight sm:text-6xl lg:text-7xl">
              Plan smarter routes.
              <br />
              <span className="gradient-text">Learn real tradeoffs.</span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted">
              Compare primary and alternate routes with cruise-altitude winds, fuel modeling,
              diversion corridors, and transparent scoring — built for learning, not dispatch.
            </p>
            <div className="mx-auto mt-8 max-w-xl">
              <ConusNotice />
            </div>
            <div className="mt-10 flex flex-wrap justify-center gap-4">
              <SignedIn>
                <ButtonLink href="/routes/new" size="lg">
                  Plan a Route
                </ButtonLink>
              </SignedIn>
              <SignedOut>
                <SignUpButton mode="modal">
                  <Button size="lg">Get Started Free</Button>
                </SignUpButton>
              </SignedOut>
              <ButtonLink href="#features" variant="outline" size="lg">
                Explore Features
              </ButtonLink>
            </div>
          </div>

          <div className="relative mx-auto mt-16 max-w-4xl animate-slide-up">
            <Card variant="glass" className="overflow-hidden p-2" padding="p-2">
              <div className="rounded-xl bg-slate-950/60 p-6 sm:p-8">
                <div className="mb-6 flex items-center gap-2">
                  <div className="h-2.5 w-2.5 rounded-full bg-red-400/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
                  <span className="ml-3 font-mono text-xs text-muted">KJFK → KLAX · Cirrus SR22</span>
                </div>
                <div className="grid grid-cols-3 gap-3 sm:gap-4">
                  {[
                    { label: "Distance", value: "2,145", unit: "NM" },
                    { label: "ETE", value: "11h 42m", unit: "wind-adjusted" },
                    { label: "Score", value: "82", unit: "/ 100" },
                  ].map((stat) => (
                    <div
                      key={stat.label}
                      className="rounded-xl border border-white/5 bg-white/[0.03] p-4 text-center"
                    >
                      <p className="text-2xl font-bold gradient-text sm:text-3xl">{stat.value}</p>
                      <p className="mt-1 text-xs text-muted">{stat.unit}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-5 h-2 overflow-hidden rounded-full bg-white/5">
                  <div className="h-full w-[82%] rounded-full bg-gradient-to-r from-sky-400 to-indigo-400" />
                </div>
                <p className="mt-4 text-center text-xs text-muted">Illustrative preview — not a live flight plan</p>
              </div>
            </Card>
          </div>
        </section>

        <section id="features" className="border-t border-white/[0.06] px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-7xl">
            <div className="mb-12 text-center">
              <h2 className="section-title">Built for aviation learners</h2>
              <p className="mx-auto mt-4 max-w-2xl text-muted">
                Real data where connected, transparent scoring, and clear limitations — so you
                understand how route planning works.
              </p>
            </div>
            <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <Card
                  key={f.title}
                  hover
                  className={`bg-gradient-to-br ${f.gradient}`}
                  padding="p-6"
                >
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-white/5 text-2xl">
                    {f.icon}
                  </span>
                  <h3 className="mt-4 text-lg font-semibold text-foreground">{f.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{f.desc}</p>
                </Card>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-3xl px-4 pb-16 sm:px-6">
          <SafetyDisclaimer />
        </section>
      </main>

      <footer className="border-t border-white/[0.06] py-10 text-center text-sm text-muted">
        AeroRoute — Educational use only. Not for operational flight planning.
      </footer>
    </div>
  );
}
