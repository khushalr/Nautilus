import { UserModelEditor } from "@/components/UserModelEditor";
import { getUserModels } from "@/lib/api";

export default async function UserModelsPage() {
  const models = await getUserModels();
  return (
    <div className="space-y-6">
      <section className="border border-line bg-ink/70 p-5">
        <h1 className="text-2xl font-semibold text-white">User models</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-steel">
          Store strategy assumptions as JSON configuration: edge thresholds, max spread, minimum liquidity, sportsbook
          weights, and excluded bookmakers. Nautilus never executes user-provided Python code.
        </p>
      </section>
      <UserModelEditor models={models} />
    </div>
  );
}
