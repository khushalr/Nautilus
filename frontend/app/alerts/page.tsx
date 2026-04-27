import { AlertsManager } from "@/components/AlertsManager";
import { getAlerts, getUserModels } from "@/lib/api";

export default async function AlertsPage() {
  const [alerts, models] = await Promise.all([getAlerts(), getUserModels()]);
  return (
    <div className="space-y-6">
      <section className="border border-line bg-ink/70 p-5">
        <h1 className="text-2xl font-semibold text-white">Alerts</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-steel">
          Alert rules monitor latest fair-value snapshots for net edge, confidence, and optional league filters. The
          starter job logs matches and leaves webhook or email delivery as a production extension.
        </p>
      </section>
      <AlertsManager alerts={alerts} models={models} />
    </div>
  );
}
