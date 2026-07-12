"""Order-book microstructure features (Section 15.1).

Pure functions over a single :class:`OrderBookSnapshot`, so they are
deterministic and testable without a live feed. Depth is measured within a
basis-point band around the mid price.
"""

from __future__ import annotations

from decimal import Decimal

from src.common.types import OrderBookSnapshot

Levels = list[tuple[Decimal, Decimal]]


def _sum_size(levels: Levels) -> Decimal:
    return sum((size for _, size in levels), Decimal(0))


def mid_price(snap: OrderBookSnapshot) -> Decimal | None:
    if not snap.bids or not snap.asks:
        return None
    return (snap.bids[0][0] + snap.asks[0][0]) / 2


def spread_bps(snap: OrderBookSnapshot) -> float | None:
    mid = mid_price(snap)
    if mid is None or mid == 0:
        return None
    best_bid, best_ask = snap.bids[0][0], snap.asks[0][0]
    return float((best_ask - best_bid) / mid) * 1e4


def imbalance(snap: OrderBookSnapshot, top_n: int = 10) -> float | None:
    """(bid_size - ask_size) / (bid_size + ask_size) over the top N levels."""
    bid = _sum_size(snap.bids[:top_n])
    ask = _sum_size(snap.asks[:top_n])
    total = bid + ask
    if total == 0:
        return None
    return float((bid - ask) / total)


def depth_within_bps(snap: OrderBookSnapshot, bps: float = 10.0) -> tuple[float, float] | None:
    """Total (bid, ask) size within `bps` of the mid price."""
    mid = mid_price(snap)
    if mid is None:
        return None
    band = mid * Decimal(str(bps)) / Decimal("10000")
    bid_depth = _sum_size([lvl for lvl in snap.bids if lvl[0] >= mid - band])
    ask_depth = _sum_size([lvl for lvl in snap.asks if lvl[0] <= mid + band])
    return float(bid_depth), float(ask_depth)


def orderbook_features(
    snap: OrderBookSnapshot, top_n: int = 10, bps: float = 10.0
) -> dict[str, float]:
    """Feature dict for one snapshot; omits keys that can't be computed."""
    out: dict[str, float] = {}
    sp = spread_bps(snap)
    if sp is not None:
        out["spread_bps"] = sp
    imb = imbalance(snap, top_n)
    if imb is not None:
        out["ob_imbalance"] = imb
    depth = depth_within_bps(snap, bps)
    if depth is not None:
        out["depth_bid"], out["depth_ask"] = depth
    return out
