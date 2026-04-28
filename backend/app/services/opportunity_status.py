from __future__ import annotations


def opportunity_status_label(net_edge: float | None, tolerance: float = 0.001) -> str:
    if net_edge is None or abs(net_edge) <= tolerance:
        return "Near fair value"
    if net_edge > 0:
        return "Possible YES underpricing"
    return "Possible YES overpricing"
