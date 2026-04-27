export default function MarketLoading() {
  return (
    <div className="space-y-6">
      <div className="h-5 w-28 animate-pulse bg-line" />
      <div className="border border-line bg-ink/70 p-5">
        <div className="h-7 w-2/3 animate-pulse bg-panel" />
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-16 animate-pulse bg-panel" />
          ))}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-72 animate-pulse border border-line bg-ink/70" />
        ))}
      </div>
    </div>
  );
}
