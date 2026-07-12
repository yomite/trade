"""Historical backfill orchestration (Section 10 Phase 1).

Fills the missing sub-ranges of a requested window, at BOTH ends: the deep
history (older than the earliest stored bar) and the recent tail (newer than the
latest). This is why an initial 5-year backfill still runs even when a small
recent slice already exists — the naive "resume from latest bar" strategy would
skip the whole deep history. The contiguous middle is not re-fetched; idempotent
upserts make any boundary overlap harmless.
"""

from __future__ import annotations

from src.common.logging import get_logger
from src.common.time import from_ms, timeframe_seconds, to_ms
from src.data.ingestion.bybit_rest import BybitREST
from src.data.storage.timescale import Database

log = get_logger("ingestion.backfill")


def compute_segments(
    earliest_ms: int | None,
    latest_ms: int | None,
    count: int,
    start_ms: int,
    end_ms: int,
    step_ms: int,
) -> list[tuple[int, int]]:
    """Sub-ranges of [start_ms, end_ms) not already covered by stored bars.

    Pure function (no I/O) so it is cheap to unit-test.
    """
    if start_ms >= end_ms:
        return []
    if count == 0 or earliest_ms is None or latest_ms is None:
        return [(start_ms, end_ms)]
    segments: list[tuple[int, int]] = []
    if start_ms < earliest_ms:
        segments.append((start_ms, earliest_ms))  # deep history
    if latest_ms + step_ms < end_ms:
        segments.append((latest_ms + step_ms, end_ms))  # recent tail
    return segments


def backfill_symbol(
    db: Database,
    client: BybitREST,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> int:
    """Load the missing bars for one symbol/timeframe into the database."""
    step_ms = timeframe_seconds(timeframe) * 1000
    earliest, latest, count = db.bar_span(symbol, timeframe)
    segments = compute_segments(
        to_ms(earliest) if earliest else None,
        to_ms(latest) if latest else None,
        count,
        start_ms,
        end_ms,
        step_ms,
    )
    if not segments:
        log.info("already_current", symbol=symbol, timeframe=timeframe)
        return 0

    written = 0
    for seg_start, seg_end in segments:
        log.info(
            "segment",
            symbol=symbol,
            timeframe=timeframe,
            frm=from_ms(seg_start).isoformat(),
            to=from_ms(seg_end).isoformat(),
        )
        for batch in client.iter_klines_range(symbol, timeframe, seg_start, seg_end):
            written += db.upsert_bars(batch)
            log.info(
                "batch",
                symbol=symbol,
                timeframe=timeframe,
                up_to=batch[-1].ts.isoformat(),
                written=written,
            )
    return written
