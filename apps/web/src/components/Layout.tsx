import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";

export function Header() {
  return (
    <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-40">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <Link href="/" className="flex items-center gap-2">
          <span className="text-2xl">✈️</span>
          <span className="text-xl font-bold text-accent">AeroRoute</span>
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          <SignedIn>
            <Link href="/dashboard" className="text-slate-300 hover:text-accent transition-colors">
              Dashboard
            </Link>
            <Link href="/routes/new" className="text-slate-300 hover:text-accent transition-colors">
              New Route
            </Link>
            <Link href="/routes" className="text-slate-300 hover:text-accent transition-colors">
              Saved Routes
            </Link>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
          <SignedOut>
            <SignInButton mode="modal">
              <button className="text-slate-300 hover:text-accent transition-colors">Sign In</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-slate-900 hover:bg-accent/90 transition-colors">
                Sign Up
              </button>
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
  showDisclaimer = true,
}: {
  children: React.ReactNode;
  title?: string;
  showDisclaimer?: boolean;
}) {
  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-6xl px-4 py-8">
        {title && <h1 className="mb-6 text-3xl font-bold">{title}</h1>}
        {showDisclaimer && <SafetyDisclaimer className="mb-6" />}
        {children}
      </main>
    </div>
  );
}
