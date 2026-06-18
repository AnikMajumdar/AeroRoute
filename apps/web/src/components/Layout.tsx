import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";
import { Button, ButtonLink } from "@/components/ui/Button";

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-3">
      <span className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-400/20 to-indigo-500/20 ring-1 ring-white/10 transition group-hover:ring-sky-400/30">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-sky-300" fill="currentColor" aria-hidden>
          <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" />
        </svg>
      </span>
      <span className="text-xl font-bold tracking-tight">
        <span className="gradient-text">Aero</span>
        <span className="text-foreground">Route</span>
      </span>
    </Link>
  );
}

export function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
        <Logo />
        <nav className="flex items-center gap-1 sm:gap-2">
          <SignedIn>
            <Link href="/dashboard" className="nav-link hidden px-3 py-2 sm:inline-block">
              Dashboard
            </Link>
            <ButtonLink href="/routes/new" variant="primary" size="sm" className="hidden sm:inline-flex">
              New Route
            </ButtonLink>
            <Link href="/routes" className="nav-link hidden px-3 py-2 md:inline-block">
              Saved
            </Link>
            <div className="ml-2 pl-2 border-l border-white/10">
              <UserButton afterSignOutUrl="/" />
            </div>
          </SignedIn>
          <SignedOut>
            <SignInButton mode="modal">
              <button className="nav-link px-3 py-2">Sign In</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <Button size="sm">Sign Up</Button>
            </SignUpButton>
          </SignedOut>
        </nav>
      </div>
    </header>
  );
}

export function PageLayout({
  children,
  title,
  subtitle,
  showDisclaimer = true,
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  showDisclaimer?: boolean;
}) {
  return (
    <div className="mesh-bg min-h-screen">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 animate-fade-in">
        {title && (
          <header className="mb-8">
            <h1 className="section-title">{title}</h1>
            {subtitle && <p className="mt-2 max-w-2xl text-muted">{subtitle}</p>}
          </header>
        )}
        {showDisclaimer && <SafetyDisclaimer className="mb-8" />}
        {children}
      </main>
    </div>
  );
}
