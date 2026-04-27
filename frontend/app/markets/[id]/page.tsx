import { MarketDetailDashboard } from "@/components/MarketDetailDashboard";

export default function MarketDetailPage({ params }: { params: { id: string } }) {
  return <MarketDetailDashboard marketId={params.id} />;
}
