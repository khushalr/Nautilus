import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { Activity, Bell, BookOpen, SlidersHorizontal } from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nautilus",
  description: "Prediction-market fair-value scanner"
};

const navItems = [
  { href: "/", label: "Scanner", icon: Activity },
  { href: "/methodology", label: "Methodology", icon: BookOpen },
  { href: "/user-models", label: "Models", icon: SlidersHorizontal },
  { href: "/alerts", label: "Alerts", icon: Bell }
];

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <div className="terminal-grid min-h-screen">
          <header className="border-b border-line/80 bg-ink/90 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
              <Link href="/" className="flex items-center gap-3">
                <div className="grid h-9 w-9 place-items-center border border-mint/60 bg-mint/10 text-sm font-bold text-mint">
                  N
                </div>
                <div>
                  <div className="text-lg font-semibold tracking-normal">Nautilus</div>
                  <div className="text-xs uppercase tracking-[0.18em] text-steel">Fair-value scanner</div>
                </div>
              </Link>
              <nav className="flex items-center gap-1">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="flex items-center gap-2 border border-transparent px-3 py-2 text-sm text-steel transition hover:border-line hover:bg-panel hover:text-white"
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      {item.label}
                    </Link>
                  );
                })}
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-5 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
