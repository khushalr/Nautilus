"use client";

import Link from "next/link";
import { AlertCircle, ArrowLeft, RefreshCw } from "lucide-react";

export default function MarketError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="space-y-4">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-steel transition hover:text-mint">
        <ArrowLeft className="h-4 w-4" />
        Scanner
      </Link>
      <div className="border border-red-400/40 bg-red-950/30 p-5 text-sm text-red-100">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <h1 className="font-medium text-white">Market error</h1>
            <p className="mt-1 text-red-100/80">{error.message}</p>
            <button
              type="button"
              onClick={reset}
              className="mt-4 inline-flex items-center gap-2 border border-red-300/50 px-3 py-2 text-white transition hover:bg-red-300/10"
            >
              <RefreshCw className="h-4 w-4" />
              Retry
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
