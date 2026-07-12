-- TimescaleDB schema (CLAUDE.md Section 11).
-- All timestamps are UTC TIMESTAMPTZ; all prices/quantities NUMERIC (never float —
-- float arithmetic loses cents, Section 11 / 21.4). Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 11.1 Core tables
-- ============================================================================

-- OHLCV bars
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,        -- '1m', '5m', '15m', '1h'
    ts          TIMESTAMPTZ NOT NULL,
    open        NUMERIC NOT NULL,
    high        NUMERIC NOT NULL,
    low         NUMERIC NOT NULL,
    close       NUMERIC NOT NULL,
    volume      NUMERIC NOT NULL,
    trades      INTEGER,
    PRIMARY KEY (symbol, timeframe, ts)
);
SELECT create_hypertable('bars', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS bars_symbol_tf_ts_idx ON bars (symbol, timeframe, ts DESC);

-- Tick-level trades (for slippage model calibration)
CREATE TABLE IF NOT EXISTS trades_raw (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    price       NUMERIC NOT NULL,
    size        NUMERIC NOT NULL,
    side        TEXT NOT NULL,        -- 'buy' or 'sell'
    trade_id    TEXT NOT NULL,
    PRIMARY KEY (symbol, ts, trade_id)
);
SELECT create_hypertable('trades_raw', 'ts', if_not_exists => TRUE);

-- Order book snapshots (top 20 levels every 1s)
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    bids        JSONB NOT NULL,       -- [[price, size], ...]
    asks        JSONB NOT NULL,
    PRIMARY KEY (symbol, ts)
);
SELECT create_hypertable('orderbook_snapshots', 'ts', if_not_exists => TRUE);

-- Computed features
CREATE TABLE IF NOT EXISTS features (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    feature_set TEXT NOT NULL,        -- versioned, e.g. 'v1.2'
    values      JSONB NOT NULL,       -- {feature_name: value}
    PRIMARY KEY (symbol, timeframe, ts, feature_set)
);
SELECT create_hypertable('features', 'ts', if_not_exists => TRUE);

-- ============================================================================
-- 11.2 Trading tables
-- ============================================================================

-- Every signal generated, including rejected ones.
-- NOTE (deviation from Section 11): kept as a regular table, NOT a hypertable.
-- TimescaleDB requires the partition column (ts) in every unique index, which
-- conflicts with the signal_id-only PRIMARY KEY that `orders.signal_id`
-- references via foreign key. Signals are low-volume (~200/day), so partition
-- pruning buys little; referential integrity is worth more here.
CREATE TABLE IF NOT EXISTS signals (
    signal_id     UUID PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL,
    symbol        TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    model_ver     TEXT NOT NULL,
    direction     TEXT NOT NULL,      -- 'long', 'short', 'flat'
    confidence    NUMERIC NOT NULL,
    features      JSONB NOT NULL,     -- snapshot of inputs
    regime        TEXT,
    decision      TEXT NOT NULL,      -- 'approved', 'rejected', 'reason...'
    reject_reason TEXT
);
CREATE INDEX IF NOT EXISTS signals_ts_idx ON signals (ts DESC);
CREATE INDEX IF NOT EXISTS signals_symbol_ts_idx ON signals (symbol, ts DESC);

-- Every order placed
CREATE TABLE IF NOT EXISTS orders (
    order_id        UUID PRIMARY KEY,
    signal_id       UUID REFERENCES signals(signal_id),
    ts_placed       TIMESTAMPTZ NOT NULL,
    ts_filled       TIMESTAMPTZ,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    type            TEXT NOT NULL,    -- 'market', 'limit', 'stop'
    qty             NUMERIC NOT NULL,
    price_target    NUMERIC,
    price_filled    NUMERIC,
    fee             NUMERIC,
    slippage_bps    NUMERIC,
    status          TEXT NOT NULL,
    exchange_id     TEXT
);

-- Every trade (entry + exit pair)
CREATE TABLE IF NOT EXISTS trades (
    trade_id           UUID PRIMARY KEY,
    symbol             TEXT NOT NULL,
    strategy           TEXT NOT NULL,
    model_ver          TEXT NOT NULL,
    regime_at_entry    TEXT,
    ts_entry           TIMESTAMPTZ NOT NULL,
    ts_exit            TIMESTAMPTZ,
    entry_price        NUMERIC NOT NULL,
    exit_price         NUMERIC,
    qty                NUMERIC NOT NULL,
    side               TEXT NOT NULL,
    pnl                NUMERIC,
    pnl_pct            NUMERIC,
    fees_total         NUMERIC,
    slippage_total_bps NUMERIC,
    exit_reason        TEXT,          -- 'stop', 'target', 'signal', 'time', 'manual'
    features_at_entry  JSONB
);

-- Equity curve, recorded every minute
CREATE TABLE IF NOT EXISTS equity (
    ts              TIMESTAMPTZ PRIMARY KEY,
    equity          NUMERIC NOT NULL,
    cash            NUMERIC NOT NULL,
    positions_value NUMERIC NOT NULL,
    drawdown_pct    NUMERIC NOT NULL
);
SELECT create_hypertable('equity', 'ts', if_not_exists => TRUE);

-- Circuit breaker events (regular table per Section 11 — very low volume)
CREATE TABLE IF NOT EXISTS circuit_breakers (
    ts              TIMESTAMPTZ NOT NULL,
    breaker_type    TEXT NOT NULL,
    trigger_value   NUMERIC,
    action          TEXT NOT NULL,
    auto_resume_at  TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS circuit_breakers_ts_idx ON circuit_breakers (ts DESC);

-- ============================================================================
-- 11.3 Learning tables
-- ============================================================================

-- Strategy lifecycle states
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy        TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    status          TEXT NOT NULL,    -- 'shadow', 'live', 'suspended', 'retired'
    params          JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    last_updated    TIMESTAMPTZ NOT NULL,
    live_sharpe_30d NUMERIC,
    live_trades_30d INTEGER
);

-- Model registry
CREATE TABLE IF NOT EXISTS models (
    model_id        UUID PRIMARY KEY,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    status          TEXT NOT NULL,    -- 'trained', 'validated', 'deployed', 'retired'
    trained_at      TIMESTAMPTZ NOT NULL,
    train_window    TSTZRANGE NOT NULL,
    test_window     TSTZRANGE NOT NULL,
    backtest_sharpe NUMERIC,
    backtest_dd     NUMERIC,
    artifact_path   TEXT NOT NULL,
    UNIQUE (name, version)
);

-- Regime memory: regime descriptors with associated outcomes
CREATE TABLE IF NOT EXISTS regime_memory (
    id              UUID PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    regime_vector   JSONB NOT NULL,   -- multidimensional regime descriptor
    forward_return  NUMERIC,          -- realized return next N bars
    n_bars          INTEGER NOT NULL
);

-- ============================================================================
-- Data-ingestion bookkeeping (not in Section 11; supports gap detection and
-- resumable backfills — Section 10 Phase 1 / data validation).
-- ============================================================================
CREATE TABLE IF NOT EXISTS ingestion_log (
    source      TEXT NOT NULL,        -- 'bybit_rest', 'bybit_ws', 'yfinance'
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    ts_start    TIMESTAMPTZ NOT NULL,
    ts_end      TIMESTAMPTZ NOT NULL,
    rows        INTEGER NOT NULL,
    gaps        INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, symbol, timeframe, ts_start)
);
