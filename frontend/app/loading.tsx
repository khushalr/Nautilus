export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-24 animate-pulse border border-line bg-ink/70" />
        ))}
      </div>
      <div className="h-32 animate-pulse border border-line bg-ink/70" />
      <div className="h-96 animate-pulse border border-line bg-ink/70" />
    </div>
  );
}
