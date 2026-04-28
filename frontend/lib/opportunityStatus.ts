export type OpportunityStatus = {
  label: "Possible YES underpricing" | "Possible YES overpricing" | "Near fair value";
  tone: "positive" | "negative" | "neutral";
};

export function opportunityStatus(netEdge: number | null | undefined, tolerance = 0.001): OpportunityStatus {
  if (netEdge == null || Math.abs(netEdge) <= tolerance) {
    return { label: "Near fair value", tone: "neutral" };
  }
  if (netEdge > 0) {
    return { label: "Possible YES underpricing", tone: "positive" };
  }
  return { label: "Possible YES overpricing", tone: "negative" };
}
