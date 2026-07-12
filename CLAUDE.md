# Autonomous Self-Learning Trading Bot — Project Specification

**Version:** 1.5
**Status:** Pre-implementation
**Document type:** Project specification for Claude Code

---

## 0. How to use this document

This document is the complete specification for the project. It is intended for Claude Code (or any engineer) to read in full before writing code. It is the source of truth — if anything in the codebase contradicts this document, the document wins unless it is explicitly updated first.

When working on this project, Claude Code should:

1. Read this entire document before writing or modifying code
2. Treat all rules marked **HARD CONSTRAINT** as non-negotiable — they exist because violating them can cause real financial loss
3. Build in the phase order specified in Section 10 — phases have dependencies and skipping ahead breaks things
4. Update this document whenever architecture, constraints, or interfaces change
5. Never disable safety features (circuit breakers, risk checks, slippage gates) without explicit human approval
6. Always prefer explicit failure over silent recovery — a crashed bot is safe, a bot trading on bad data is not

### 0.1 Environment ground rules — read this first

Before generating any setup scripts, Dockerfiles, docker-compose files, or deployment instructions, Claude Code must respect these facts about the operator's environment:

- **The operator develops on a native Ubuntu Linux machine.** Local setup steps use standard Ubuntu tooling (`apt`, `systemctl`, `python3`, `psql`) directly. No WSL, no VM, no Windows shim layer.
- **Do NOT use Docker or Docker Desktop.** Docker was tried previously and crashed the operator's system. Never suggest, generate, or reference Docker files, docker-compose configurations, or Docker-based workflows. The `deploy/` directory contains systemd units, not container definitions. The whole point of choosing native systemd is to avoid Docker entirely.
- **Do NOT provision Oracle Cloud, AWS, GCP, or Azure resources.** The chosen host is **DigitalOcean** (see Section 6.3). Oracle Cloud Free Tier was explicitly evaluated and rejected. Never generate setup scripts targeting other clouds unless the operator explicitly requests migration.
- **Do NOT suggest WSL, dual-boot, or Windows-native tooling.** The Windows path was abandoned. Assume Ubuntu everywhere: on the operator's local machine and on the DigitalOcean droplet.
- **Environment parity is real.** The operator's local Ubuntu and the DigitalOcean droplet run the same OS family, so code that works locally should work on the droplet with only configuration differences. Preserve this parity: don't introduce dev-only tooling that isn't on the droplet, or production-only tooling that isn't available locally.
- **The exchange is Bybit spot.** No other exchanges, no futures, no forex, no equities, no prop firms. See Section 5.4 for the reasoning.
- **When in doubt about infrastructure, ask before generating.** A wrong assumption about environment produces work the operator has to throw away.

---

## 1. Mission

Build a fully autonomous trading bot that:

- Selects which instruments to trade without human input
- Generates and selects strategies based on detected market regime
- Sizes positions and manages risk autonomously
- Executes trades against a live exchange
- Continuously learns from its own performance and improves over time

The system must be safe enough to run unattended on a $1,000 live account, and must improve its risk-adjusted returns over time without human intervention.

---

## 2. Core principles

These principles drive every design decision. When in doubt, fall back to these.

1. **Safety beats cleverness.** A simple system that survives is better than a sophisticated one that blows up.
2. **Closed loop or it doesn't count.** Every output (a trade) must produce a measured outcome (P&L, slippage, regime context) that flows back into the learning system.
3. **Walk-forward, never look-ahead.** Any model trained or evaluated with data from after the prediction point is useless.
4. **Explicit over implicit.** All risk limits, all model versions, all strategy parameters live in config — never hardcoded in business logic.
5. **Fail loud, fail fast.** If anything is wrong — bad data, broken API, model output out of bounds — halt trading and alert. Never trade through uncertainty.
6. **Reproducibility.** Any historical decision must be reproducible from logs alone — same inputs, same code version, same outputs.
7. **Cost is a first-class concern.** Spread, fees, and slippage must be modeled in every backtest and every live decision.

---

## 3. System overview

### 3.1 The five layers

The system is organized into five layers, each with clear responsibilities and interfaces. Data flows downward; learning flows upward.

```
┌─────────────────────────────────────────────────────────┐
│ LAYER 1 — DATA INGESTION                                │
│ Price feeds, order book, news/NLP, on-chain, macro      │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ LAYER 2 — INTELLIGENCE ENGINE                           │
│ Instrument scanner · Regime detector · Strategy         │
│ selector · Signal generator (LSTM + XGBoost + RL)       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ LAYER 3 — DECISION ENGINE                               │
│ Risk engine · Position sizer · Portfolio manager ·      │
│ Trade approver                                          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ LAYER 4 — EXECUTION LAYER                               │
│ Smart router · Broker API · Fill tracker · P&L tracker  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ LAYER 5 — SELF-LEARNING LOOP                            │
│ Performance analyzer · Model retrainer · Strategy       │
│ evolver · Memory store                                  │
└─────────────────────────────────────────────────────────┘
                          │
                          └──── feedback to all layers ───┐
                                                          │
                                                          ▼
                                              (config & model updates)
```

### 3.2 Key invariants

- **No trade fires without passing every Layer 3 check.** This is enforced by the trade approver, which is the only path to the execution layer.
- **No model is deployed without a successful walk-forward evaluation.** The model registry rejects models whose out-of-sample Sharpe is below threshold.
- **No strategy is funded without a minimum live performance record.** New strategies start in shadow mode (decisions logged, not executed) before going live.
- **Every order has a stop loss.** Market orders without protective stops are forbidden in code.

---

## 4. HARD CONSTRAINTS — risk and safety rules

These are non-negotiable. They are enforced in code and cannot be bypassed by any strategy, model, or configuration override at runtime. Changing any of these requires editing the constants file and committing the change with explicit justification.

### 4.1 Capital and position limits

| Constraint | Value | Enforced in |
|---|---|---|
| Risk per trade | 1.0% of account equity | `risk_engine.py` |
| Max single position size | 25% of account equity | `position_sizer.py` |
| Max concurrent open positions | 3 | `portfolio_manager.py` |
| Max leverage | 1.0× (spot only, no margin) | `execution.py` |
| Kelly fraction cap | 0.25 (quarter Kelly) | `position_sizer.py` |
| Min trade size | $10 notional | `trade_approver.py` |

### 4.2 Drawdown circuit breakers

| Trigger | Action | Recovery |
|---|---|---|
| Daily loss ≥ 3% of equity | Pause all new trades for 24h | Auto-resume |
| Weekly loss ≥ 8% of equity | Pause all trading for 7 days | Manual restart required |
| Total drawdown from peak ≥ 15% | Full shutdown | Manual review + restart |
| 5 consecutive losing trades in one strategy | Suspend that strategy | Auto-resume after retraining |

### 4.3 Data and model safety

| Trigger | Action |
|---|---|
| Stale data feed (> 60 seconds for 1m bars) | Halt trading, alert |
| Order book depth missing | Halt trading, alert |
| Model output NaN, inf, or out of [-1, 1] | Reject signal, log, alert |
| Real slippage > 3× expected slippage | Suspend strategy, investigate |
| Model confidence < 0.60 | Filter out signal |
| Backtest Sharpe < 1.0 on out-of-sample window | Reject deployment |
| Live performance deviation > 2σ from backtest | Auto-pause, alert |

### 4.4 Operational

- The bot must never trade in the first 5 minutes after startup (warmup period for data buffers)
- The bot must never trade if system clock has drifted > 1 second from exchange time
- The bot must never resume after a circuit breaker trip without explicit logging of the trigger
- API keys must have **trade** permission only, never **withdraw**

---

## 5. Market and instruments

### 5.1 Initial scope (Phase 1)

- **Exchange:** Bybit (spot)
- **Instruments:** BTC/USDT, ETH/USDT
- **Timeframes:** 1m, 5m, 15m, 1h (model can use any combination)
- **Hours:** 24/7

### 5.2 Future scope

After 90 days of stable live operation, the universe expands to top-10 by market cap, restricted to coins with:

- Daily volume ≥ $1B average over 30 days
- Listed on Bybit spot for ≥ 1 year
- No active exchange warning labels

Other markets (forex, equities, futures) are out of scope for v1.

### 5.3 Why this market

Crypto majors offer 24/7 markets (3× the learning opportunities of forex), deep liquidity that resists manipulation at our trade size, free and mature APIs, and fractional trading. The tradeoffs (higher volatility, regulatory risk, exchange counterparty risk) are accepted and managed via the constraints in Section 4.

### 5.4 Broker portability — what's supported and what isn't

The execution layer (Section 16) uses a `broker.py` abstraction, so adding new brokers is architecturally possible. But not all brokers are equally compatible with this system. This subsection makes the boundaries explicit.

**Compatible in v1:** Bybit spot only.

**Compatible in v2 with low effort:** other crypto spot exchanges — Binance, Kraken, Coinbase Advanced. Each is a new `adapter.py` file plus instrument-rule handling; no changes to risk, sizing, or learning layers. A few days of work per adapter.

**Not compatible without substantial spec changes:**

- **Traditional equity brokers** (Interactive Brokers, Alpaca, TD Ameritrade). Different asset class, market hours (not 24/7), pattern day trader rule for US accounts under $25k, different API paradigms.
- **Forex/CFD brokers** (OANDA, IG, most MetaTrader brokers). Overnight swap fees violate the "no funding fees" HARD CONSTRAINT. Would require adding a swap fee module to the cost-vs-edge check and reworking the strategies.
- **Futures brokers**. Contract expiry, rollover, and margin mechanics don't fit the current design.

**Explicitly NOT compatible:** prop firms (FTMO, MyForexFunds, Topstep, The5ers, and similar). Reasons documented separately here because this is a common question:

- **Rule incompatibility.** Prop firm rules (max daily loss, max total drawdown, minimum/maximum trading days, no weekend holds, consistency rules capping single-day profit, no-hedging restrictions) conflict with the bot's autonomous risk management and strategy diversity.
- **Algorithmic trading restrictions.** Many prop firms explicitly prohibit algorithmic or EA-based trading, or require prior approval and can invalidate accounts retroactively for violations.
- **Subjective rule enforcement.** Prop firms make revenue primarily from challenge fees, not from traders' profits. Rules are frequently interpreted subjectively; there is no arbitration path.
- **Technical integration.** Most prop firms provide MetaTrader 4/5 accounts, not proper APIs. Integrating MT4/MT5 requires MQL bridges or paid third-party services like MetaAPI, adding latency and dependency risk.
- **Business incentive misalignment.** Even a technically successful bot can be invalidated for violating a subjective consistency clause.

Prop firm compatibility is not a v2 or v3 goal. Operators who want prop firm profits should use a different approach designed specifically for those constraints, with human oversight for rule compliance.

---

## 6. Technology stack

### 6.1 Languages and runtime

- **Python 3.11+** — primary language
- **asyncio** — for concurrent data feeds and order management
- **Type hints required everywhere** — enforced via `mypy --strict`

### 6.2 Core libraries

| Purpose | Library | Why |
|---|---|---|
| Exchange API | `ccxt` (unified) + `pybit` (Bybit native) | ccxt for portability, pybit for performance |
| ML — sequential | `pytorch` | LSTM, attention models |
| ML — tabular | `xgboost`, `lightgbm` | Gradient boosting on engineered features |
| ML — RL | `stable-baselines3` | PPO, SAC for execution and sizing |
| Data | `pandas`, `polars`, `numpy` | polars for hot paths, pandas for analysis |
| Time-series DB | `psycopg2`, `sqlalchemy` | TimescaleDB connection |
| Indicators | `pandas-ta`, `ta-lib` | Technical indicators |
| Backtesting | Custom (see Section 13) | No off-the-shelf library — too many compromises |
| Web framework | `fastapi` | For monitoring dashboard backend |
| Config | `pydantic-settings` | Validated config from env + YAML |
| Logging | `structlog` | Structured JSON logs |
| Testing | `pytest`, `pytest-asyncio`, `hypothesis` | Property-based tests for risk logic |
| Notifications | `python-telegram-bot` | Telegram alerts |

### 6.3 Infrastructure

- **Cloud:** DigitalOcean droplet, Singapore region (closest to Bybit)
- **Instance:** Basic Droplet, 2 vCPU / 4 GB RAM / 80 GB SSD, Ubuntu 24.04 LTS, ~$24/month
- **Latency to Bybit:** ~30ms (acceptable; we are not HFT)
- **No containers.** The system runs directly on the host using a Python virtual environment and **systemd** services. Docker is explicitly NOT used — it adds weight and a failure surface we don't need for a single-host deployment. (Docker was tried previously and crashed the operator's system; avoiding it is a deliberate simplification, not a limitation.)
- **DB:** TimescaleDB (PostgreSQL extension), installed natively on the droplet as a system service (`postgresql.service`).
- **Process management:** systemd units for the bot, the dashboard, and scheduled jobs (retraining, backups). systemd handles restart-on-crash, boot startup, and logging to journald.
- **Remote access / dashboard exposure:** Tailscale (free for personal use). The dashboard binds to the Tailscale private network only — no public ports exposed to the internet. No reverse proxy or public TLS certificate needed. (An optional nginx + domain path is documented in Section 19.3 for users who prefer public access.)
- **Backup:** nightly `pg_dump` + model artifacts to **DigitalOcean Spaces** (S3-compatible object storage, $5/month for 250 GB — we use < 10 GB).

#### 6.3.1 Why DigitalOcean

- **Reliable.** Paid infrastructure with an SLA. The operator's prior experience with free tiers (specifically Oracle Cloud Free) was poor; that path was evaluated and rejected in favor of DigitalOcean's paid stability.
- **Simple.** DigitalOcean's control panel and API are the least friction of the major cloud providers. Setup is minutes, not hours.
- **Well-known to the ecosystem.** Ubuntu droplets are a widely documented target; troubleshooting resources are abundant.
- **Right-sized.** The Basic Droplet at $24/month is precisely enough for v1's compute needs (model training, TimescaleDB, dashboard, bot) without paying for capacity we don't use.
- **Object storage integrated.** DO Spaces is S3-compatible, cheap, and integrated with the droplet region.

### 6.4 Local development on Ubuntu

The operator's development machine is a native Ubuntu Linux workstation. This gives us real dev-prod parity: the same OS family runs locally and on the droplet, so code that works in one place works in the other.

#### 6.4.1 Local setup

One-time steps on the operator's Ubuntu machine:

1. **System packages**
   ```
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv python3-pip git build-essential \
                       postgresql-16 postgresql-server-dev-16 curl
   ```
2. **TimescaleDB extension** — follow the [official Ubuntu install instructions](https://docs.timescale.com/self-hosted/latest/install/installation-linux/) to add the TimescaleDB apt repo and install the extension against the local PostgreSQL 16.
3. **Create the development database:**
   ```
   sudo -u postgres createuser -P tradingbot     # set a local dev password
   sudo -u postgres createdb -O tradingbot tradingbot_dev
   sudo -u postgres psql -d tradingbot_dev -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
   ```
4. **Clone the repo and create the virtual environment:**
   ```
   git clone <repo-url> ~/tradingbot
   cd ~/tradingbot
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
5. **Configure `.env`** with the local `DATABASE_URL` (e.g., `postgresql://tradingbot:PASSWORD@localhost:5432/tradingbot_dev`), Bybit **testnet** API keys, and Telegram credentials.
6. **Run tests:** `make test`.

Full setup steps live in `docs/dev-setup-ubuntu.md`, which Claude Code generates as part of Phase 0.

#### 6.4.2 Development workflow

- **Editor:** VS Code, PyCharm, or any editor the operator prefers — all work natively on Ubuntu.
- **Running the bot locally:** `make run-paper` for paper mode, `make backtest` for backtesting. Both target the local TimescaleDB.
- **Live data on the local machine:** the bot connects to Bybit websockets from the operator's Ubuntu machine during development. Fine for testing; production live trading happens on the droplet where 24/7 uptime is guaranteed.
- **systemd on the local machine:** the systemd units in `deploy/systemd/` can optionally be installed on the local machine for long-running paper trading tests. Not required — running via `make run-paper` in a terminal is fine for most development.

#### 6.4.3 Optional: development directly on the droplet

Once the droplet is provisioned, VS Code's Remote-SSH extension (also available for other editors) lets the operator work directly on the server. Useful when:

- Testing something that requires the droplet's exact environment
- Working from a device that isn't the main Ubuntu workstation
- Debugging a production-only issue

The operator's local Ubuntu is the primary environment. Remote-SSH is a secondary option, not a replacement.

#### 6.4.4 Environment parity checklist

Because the local machine and the droplet run the same OS family, most compatibility is automatic. A few things to watch:

- **Python minor version** — pin to 3.11 in `pyproject.toml`. Ubuntu 24.04 ships 3.12 by default; install 3.11 explicitly.
- **PostgreSQL version** — use PostgreSQL 16 in both places. If the local machine has an older version, install 16 alongside.
- **TimescaleDB version** — pin in the setup docs so both machines run the same release.
- **System time** — enable NTP (`sudo timedatectl set-ntp true`) on both to keep the clock-drift check in the risk engine from spuriously firing.

### 6.5 Why custom backtester

`backtrader`, `vectorbt`, `zipline`, and `qlib` were all evaluated. Each has fatal compromises for our use case:

- None handle realistic order book slippage well
- None support walk-forward retraining loops natively
- All require contortions to model regime-aware multi-strategy ensembles
- Most are slow on tick-level data

A custom backtester (~1500 lines) is the right call. It will be event-driven, mirror live trading exactly, and use the same risk/execution code paths so backtest behavior matches live behavior.

---

## 7. Costs and economics

A clear-eyed view of what running this system costs, what generates returns, and the realistic economics at different capital levels. The system can be profitable, but only if the costs are properly understood and the strategies clear them.

### 7.1 Fixed monthly costs

These are paid regardless of trading activity.

| Service | Cost | Required? | Notes |
|---|---|---|---|
| DigitalOcean droplet (2 vCPU, 4 GB, Singapore, Ubuntu 24.04) | $24/month | Required | Includes 4 TB outbound transfer |
| DigitalOcean Spaces (backups) | $5/month | Required | 250 GB storage, 1 TB transfer included; we use < 10 GB |
| Tailscale (private dashboard access) | $0 | Recommended | Free for personal use up to 100 devices |
| Domain name | ~$1/month ($12/year) | Optional | Only if exposing dashboard publicly instead of via Tailscale |
| Telegram Bot API | $0 | Required | Free, no rate-card |
| yfinance (cross-asset data) | $0 | Required | Free Yahoo Finance API |
| FRED API | $0 | Optional | Free, US Federal Reserve |
| **Total fixed** | **~$29/month** | | $30/month if a public domain is used |

**Why paid hosting over free tiers.** Free tiers (Oracle Cloud Always Free, AWS/GCP/Azure new-account credits) were considered and rejected. The operator's prior experience with Oracle Cloud Free specifically was poor, and free tiers generally carry no SLA — inappropriate for a system that will hold real capital positions 24/7. $29/month is a reasonable insurance premium against server outages during open positions.


### 7.2 Variable costs — Bybit trading fees

Bybit's base spot trading fees are 0.10% maker and 0.10% taker for non-VIP accounts. Round-trip cost is therefore 0.20% per trade. These are paid to the exchange and are unavoidable; they enter the cost-vs-edge check (see Section 18 Stage 9 for the trade-time mechanics).

**Estimated monthly fee burden by activity level:**

For a $1,000 account doing 5-10 trades per day at average $200 trade size:
- Per-trade cost: ~$0.40
- Daily: $2-4
- **Monthly: $60-120**

This works out to roughly 6-12% of capital per month in trading fees alone — which is significant. The risk engine's cost-vs-edge filter rejects any trade where the expected edge doesn't exceed expected costs by 1.2×, which means many marginal signals never become trades.

#### Bybit VIP fee tiers

VIP tiers reduce fees substantially but require monthly volume that's out of reach for a $1,000 account. Approximate thresholds:

| Tier | 30-day volume required | Maker / Taker |
|---|---|---|
| Non-VIP | < $250k | 0.10% / 0.10% |
| VIP 1 | ≥ $250k | 0.08% / 0.085% |
| VIP 2 | ≥ $1M | 0.05% / 0.075% |
| VIP 3+ | ≥ $5M | Lower still |

Reaching VIP 1 with a $25,000 account doing 30× monthly turnover is plausible and is one of the reasons capital scaling matters.

### 7.3 What you don't pay for

To be explicit, the bot has zero cost for:

- AI APIs (no Claude, OpenAI, or any LLM in the trade loop)
- ML model hosting (PyTorch, XGBoost run locally on the droplet)
- Database (TimescaleDB on the same droplet, free open-source)
- Monitoring (Prometheus + Grafana, both free)
- Web framework / dashboard (FastAPI, free)
- Remote access / dashboard exposure (Tailscale, free for personal use)
- Containers (no Docker; no container registry costs)
- News/sentiment APIs (deferred to v2)
- On-chain analytics (deferred to v2; would cost $30-300/month if added)

### 7.4 Total cost of ownership

| Period | Cost |
|---|---|
| Year 1 fixed (droplet + Spaces) | ~$348 |
| Year 1 domain (optional) | ~$12 |
| Year 1 trading fees (estimate) | ~$1,000 (varies with strategy frequency) |
| **Year 1 total** | **~$1,360** |
| Monthly steady state | ~$29 fixed + variable trading fees |

### 7.5 Capital scaling — the honest economics

There is a common misconception that trading economics improve dramatically at higher capital. They do — but not in the obvious way.

**What scales linearly with capital:**
- Position sizes
- Trading turnover
- **Trading fees** (still ~0.2% round-trip × turnover)

**What does NOT scale with capital:**
- Required edge per trade — still need to clear ~0.30% per trade after costs

**What improves with capital:**
- Fixed costs become negligible ($29 / $10,000 = 0.3%, vs $29 / $1,000 = 2.9%)
- VIP fee tiers become reachable (saving ~10-25% on fees at VIP 1+)
- Slippage cost as a percentage stabilizes (no longer constrained to micro-trades near minimums)
- Strategy diversification becomes possible (room for 5-8 concurrent strategies vs 2-3)
- Drawdown headroom is psychologically and practically larger

| Capital | Fixed cost % | Trading fees % (typical) | Required gross monthly |
|---|---|---|---|
| $1,000 | 2.9% | ~10% | **~13%** — tough |
| $5,000 | 0.6% | ~10% | ~10.6% |
| $10,000 | 0.3% | ~10% | ~10.3% — comfortable |
| $25,000 | 0.12% | ~9% (VIP 1) | ~9.1% |
| $100,000 | 0.03% | ~8% (VIP 2-3) | ~8% |

Trading fees are the dominant cost at every capital level. Fixed hosting costs are a meaningful percentage only at the $1k validation phase; they become negligible from $10k upward.

### 7.6 Implications for the v1 plan

The $1,000 phase requires the bot to generate roughly 13% monthly *gross* returns just to break even after costs. **This is a difficult bar.** The honest framing:

- The $1,000 phase is best understood as **a learning and validation phase**, not a profit-generation phase.
- Success at $1,000 is defined as: positive Sharpe ratio, controlled drawdowns, validated strategies — not large dollar profits.
- The dollar profits become meaningful only after capital scaling — which itself requires demonstrating the system works at $1,000.
- The bot's design is intentionally fee-aware: every trade has a hard cost-vs-edge gate that prevents the death-by-fees scenario.
- The $29/month hosting is an unavoidable drag at $1k capital. It stops mattering economically at $10k+.

### 7.7 What could make economics worse

For completeness, the things to watch that could increase costs:

- **Bybit fee schedule changes** — historically rare, but possible. Bot's edge filter adapts automatically since it uses live fee data.
- **Slippage worse than modeled** — particularly during volatile periods. Auto-suspend triggers if real slippage exceeds 3× model.
- **Excessive strategy turnover** — a poorly-tuned strategy that flips frequently burns fees. Strategy evolver will kill these via Sharpe ratio threshold.
- **Database / compute scaling** — if data volume grows beyond the droplet's capacity, upgrade to a $48/month tier. Not expected for v1's two-symbol scope.
- **Bandwidth overage** — the $24 droplet includes 4 TB outbound; realistic v1 usage is well under 100 GB. Non-issue unless something is misbehaving.

---

## 8. AI and external service dependencies

### 8.1 The bot does NOT call external AI APIs at decision time

This is a deliberate architectural choice. The bot is fully self-contained — it runs its own ML models locally on the droplet, and makes no API calls to Anthropic, OpenAI, Google, or any other LLM provider during trade decisions.

### 8.2 Why no LLM in the trade decision path

| Concern | Reality |
|---|---|
| **Latency** | LLM API round-trip is 500ms-3s. Markets move within that window. |
| **Cost** | Hundreds of decisions per hour × any non-zero per-call cost exceeds expected bot profit |
| **Non-determinism** | Same input → different outputs. Backtests become unreproducible. |
| **No predictive alpha** | LLMs weren't trained on price prediction. They have no edge on financial time series. |
| **Single point of failure** | Provider outage or rate limit = bot stops trading mid-position |
| **Unauditable** | LLM versions change. A decision from 6 months ago can't be reproduced. |
| **Constraint violations** | LLMs don't reliably respect hard limits. We need deterministic risk gates. |

### 8.3 What the bot uses instead

The "intelligence" of the bot is built from local ML models, all of which are deterministic and reproducible:

- **LSTM neural networks** (PyTorch) — for sequential pattern recognition in price/volume time series
- **XGBoost / LightGBM** — for tabular feature-based directional prediction
- **Reinforcement learning agent** (stable-baselines3, PPO/SAC) — for execution timing and sizing refinement
- **Hidden Markov Model** — for regime classification
- **Ensemble layer** — weighted combination of the above

These are trained on your historical data, run inference in milliseconds, are version-controlled, and produce the same output for the same input every time.

### 8.4 Approved external APIs (non-AI)

The bot does call these external services. None are in the critical trade decision path — they all feed into the data layer and have local fallbacks.

| Service | Purpose | v1 status | Failure behavior |
|---|---|---|---|
| Bybit REST API | Historical data, account state | Required | Halt trading if down > 5 min |
| Bybit Websocket | Live market data | Required | Halt trading if disconnected > 60s |
| Telegram Bot API | Notifications and commands | Required | Log only, do not block trading |
| yfinance | Cross-asset data (VIX, DXY, S&P, gold) for regime features | Required | Use cached values if down |
| FRED API | Macro indicators (rates, etc.) | Optional | Use cached values if down |
| News API | News headlines | **Deferred to v2** | N/A |

### 8.5 Why no news/sentiment pipeline in v1

A real-time news and sentiment pipeline was considered and explicitly deferred. The reasoning:

- **Timing mismatch.** News is priced into the market in seconds. By the time a non-HFT system reads and parses an article, the price reaction is already over. The bot would be reacting to news, not anticipating it.
- **Market action contains the signal.** Cross-asset price action — volatility spikes, correlation breakdowns, DXY moves — captures the *same context* news provides, with less ambiguity and no NLP risk.
- **Engineering cost vs benefit.** A robust news pipeline (sourcing, deduplication, sentiment scoring, event extraction) is 2-3 weeks of work for marginal predictive value at our timeframe.
- **The right place for context is regime features, not signals.** See Section 15 for the cross-asset regime features that capture macro context without parsing news.

The operator (you) reads the news, not the bot. The bot reads the market.

### 8.6 Where LLMs can legitimately fit (deferred to v2)

These uses are explicitly **out of scope for v1** but reasonable additions later. All are offline or low-frequency batch — never in the trade hot path:

- **News and earnings parsing** — extract structured sentiment/event signals from text once per minute, output cached as features. Could use Claude or GPT in a periodic batch job.
- **Strategy code generation** — having an LLM help write new strategy candidates *offline*, then validating them through the normal walk-forward backtest process before any are deployed.
- **Post-trade analysis** — generating natural-language weekly performance summaries from trade logs.
- **Anomaly explanation** — when a circuit breaker trips, summarizing the events leading up to it for the operator.
- **Daily operator briefing** — a summary of overnight market action and upcoming calendar events (FOMC, CPI, etc.) sent to the operator each morning. Read by the human, not the bot. Useful for keeping the operator's mental model aligned with what the bot is doing.
- **Documentation maintenance** — keeping `CLAUDE.md` updated as architecture evolves.

If any of these are added later, they go through the same approval gates as any other feature: written into this spec, tested, deployed in shadow mode first.

### 8.7 Model artifacts and reproducibility

Every model used in the bot is:

- Stored as a versioned artifact in `data/models/{name}/{version}/`
- Registered in the `models` table with full provenance (training window, code hash, metrics)
- Backed up nightly to DigitalOcean Spaces
- Loadable and runnable offline — no internet required for inference

If Anthropic, OpenAI, AWS, or any external service disappeared overnight, the bot would continue trading without disruption.

---

## 9. Repository structure

```
trading-bot/
├── CLAUDE.md                   # This document
├── README.md                   # Quick start for humans
├── pyproject.toml              # Dependencies, mypy, ruff config
├── .env.example                # All env vars documented, no secrets
├── .gitignore
├── Makefile                    # Common commands
│
├── config/
│   ├── base.yaml               # Default config
│   ├── paper.yaml              # Paper trading overrides
│   ├── live.yaml               # Live trading overrides
│   └── backtest.yaml           # Backtesting overrides
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point — wires everything together
│   ├── constants.py            # HARD CONSTRAINTS from Section 4
│   │
│   ├── data/                   # LAYER 1
│   │   ├── ingestion/
│   │   │   ├── bybit_ws.py     # Live websocket feeds
│   │   │   ├── bybit_rest.py   # Historical loader
│   │   │   ├── crossasset.py   # VIX, DXY, S&P, gold via yfinance
│   │   │   └── macro.py        # Macro indicators (FRED API, optional)
│   │   ├── storage/
│   │   │   ├── timescale.py    # DB connection + writers
│   │   │   └── schema.sql      # All table definitions
│   │   ├── features/
│   │   │   ├── price.py        # Returns, vol, momentum
│   │   │   ├── volume.py       # Volume features
│   │   │   ├── orderbook.py    # Imbalance, depth features
│   │   │   ├── indicators.py   # RSI, MACD, BB, etc
│   │   │   └── regime.py       # Regime classification features
│   │   └── validation.py       # Data quality checks
│   │
│   ├── intelligence/           # LAYER 2
│   │   ├── scanner/
│   │   │   └── instrument_scanner.py  # Ranks tradeable assets
│   │   ├── regime/
│   │   │   └── detector.py     # HMM or classifier-based
│   │   ├── strategies/
│   │   │   ├── base.py         # Strategy ABC
│   │   │   ├── trend.py        # Trend-following
│   │   │   ├── mean_reversion.py
│   │   │   ├── breakout.py
│   │   │   └── registry.py     # Strategy registry + lifecycle
│   │   ├── models/
│   │   │   ├── lstm.py
│   │   │   ├── xgb.py
│   │   │   ├── rl_agent.py
│   │   │   ├── ensemble.py     # Weighted combination
│   │   │   └── registry.py     # Model registry + versioning
│   │   └── selector.py         # Strategy selector
│   │
│   ├── decision/               # LAYER 3
│   │   ├── risk_engine.py      # All risk checks
│   │   ├── position_sizer.py   # Kelly + vol-adjusted sizing
│   │   ├── portfolio_manager.py
│   │   └── trade_approver.py   # Single gate to execution
│   │
│   ├── execution/              # LAYER 4
│   │   ├── router.py           # Smart order routing
│   │   ├── broker.py           # Broker abstraction
│   │   ├── bybit_adapter.py    # Bybit-specific impl
│   │   ├── paper_adapter.py    # Paper trading impl
│   │   ├── instrument_rules.py # Precision, tick/lot size, minimums (Section 16.3)
│   │   ├── fill_tracker.py
│   │   └── pnl_tracker.py
│   │
│   ├── learning/               # LAYER 5
│   │   ├── performance.py      # Sharpe, drawdown, win rate, etc
│   │   ├── retrainer.py        # Walk-forward retraining
│   │   ├── evolver.py          # Strategy parameter optimization
│   │   ├── journal.py          # Trade journal
│   │   └── memory.py           # Regime + outcome memory store
│   │
│   ├── backtest/               # Backtesting engine
│   │   ├── engine.py           # Event-driven core
│   │   ├── slippage.py         # Realistic slippage model
│   │   ├── walk_forward.py     # WF orchestration
│   │   └── reports.py          # HTML/JSON output
│   │
│   ├── monitoring/
│   │   ├── dashboard.py        # FastAPI + simple frontend
│   │   ├── alerts.py           # Telegram notifications
│   │   └── metrics.py          # Prometheus metrics
│   │
│   └── common/
│       ├── logging.py          # structlog setup
│       ├── config.py           # pydantic config
│       ├── time.py             # Time utilities (always UTC)
│       └── types.py            # Shared types
│
├── tests/
│   ├── unit/                   # Mirrors src/ structure
│   ├── integration/
│   ├── property/               # Hypothesis-based
│   └── fixtures/
│
├── notebooks/                  # Jupyter notebooks for exploration
│   └── README.md               # "Notebooks are scratch — never imported"
│
├── scripts/
│   ├── load_history.py         # Bulk historical data loader
│   ├── run_backtest.py
│   ├── train_models.py
│   ├── healthcheck.py          # Pre-trade system health validation
│   └── backup.py               # pg_dump + model artifacts → DigitalOcean Spaces
│
├── deploy/                     # No Docker — host-level deployment
│   ├── setup_server.sh         # One-time droplet bootstrap (Python, TimescaleDB, Tailscale)
│   ├── install_services.sh     # Installs + enables systemd units
│   ├── update.sh               # git pull + migrate + restart services
│   └── systemd/
│       ├── tradingbot.service       # Main bot process
│       ├── tradingbot-dashboard.service  # FastAPI dashboard
│       ├── tradingbot-retrain.service    # Retraining job (oneshot)
│       ├── tradingbot-retrain.timer      # Schedules retraining
│       ├── tradingbot-backup.service     # Backup job (oneshot)
│       └── tradingbot-backup.timer       # Schedules nightly backup
│
└── data/                       # Gitignored — local data only
    ├── raw/
    ├── processed/
    └── models/                 # Trained model artifacts
```

---

## 10. Build phases

Phases must be built in order. Each phase has a Definition of Done — the next phase cannot start until DoD is met.

### Phase 0 — Project foundation (1-2 days)

**Goal:** Repo, tooling, CI, local environment.

- Repo with structure from Section 9
- `pyproject.toml` with all dependencies (standard x86_64 Linux wheels)
- Python virtual environment setup documented in `docs/dev-setup-ubuntu.md` (local Ubuntu workflow) and `docs/dev-setup-remote-ssh.md` (optional remote workflow on the droplet)
- TimescaleDB installed locally on the operator's Ubuntu machine as a system service; `DATABASE_URL` configurable
- `.env.example` with every env var documented
- `Makefile` targets: `make install`, `make test`, `make lint`, `make run-paper`, `make backtest`
- Pre-commit hooks: `ruff`, `mypy --strict`, `pytest -m fast`
- GitHub Actions CI running tests on every push (CI runner installs deps into a venv — no containers)
- `README.md` with a Ubuntu-first quick start pointing to the setup guide

**Definition of Done:** `make test` passes on a fresh clone after `make install` on the operator's local Ubuntu machine.

### Phase 1 — Data pipeline (3-5 days)

**Goal:** Reliable historical and live data ingestion into TimescaleDB.

- TimescaleDB schema (Section 11)
- Bybit historical loader: pulls 1m candles for BTC/USDT and ETH/USDT for last 5 years
- Bybit websocket: subscribes to live trades, candles, order book; writes to DB
- Data validation: gaps detected, late data flagged, duplicates rejected
- Cross-asset and macro feeds (VIX, DXY, S&P, gold via yfinance; FRED optional — can stub with empty data initially)
- Feature computation: implemented as deterministic transforms over the time-series, must produce identical output for identical input

**Definition of Done:**
- 5 years of historical 1m data loaded with < 0.1% gap rate
- Live feed running for 24h with no missed candles
- All features computed and stored, with unit tests verifying determinism

### Phase 2 — Risk engine and position sizing (2-3 days)

**Goal:** All risk checks built before any signal logic. This order is deliberate — we will not have a path to execute trades until risk gates exist.

- `risk_engine.py` implementing every check in Section 4
- `position_sizer.py` with Kelly + volatility scaling
- `portfolio_manager.py` tracking open positions, exposure
- `trade_approver.py` as the single gate
- Property-based tests with Hypothesis: no input combination should be able to produce a position size larger than the hard caps

**Definition of Done:**
- 100% test coverage on risk engine
- Hypothesis test suite passes with 10,000 generated scenarios
- All hard constraints from Section 4 have a corresponding test that fails when the constraint is violated

### Phase 3 — Backtesting engine (4-6 days)

**Goal:** A backtester that mirrors live behavior exactly.

- Event-driven engine: bar-by-bar replay
- Uses the same risk engine, position sizer, and approver as live trading (no parallel implementations)
- Realistic slippage model: function of order size, volatility, and order book depth
- Fee model matching Bybit's actual fee schedule
- Walk-forward orchestrator: rolling train/test windows
- HTML report with equity curve, drawdown, trade list, regime overlay

**Definition of Done:**
- Backtest of buy-and-hold BTC for 2020-2024 produces results within 2% of actual market performance
- Walk-forward backtest of a simple SMA crossover runs end-to-end
- Slippage model validated against real fills (after Phase 6)

### Phase 4 — First strategies and models (5-7 days)

**Goal:** Working baseline strategies to populate the system.

- `strategies/trend.py` — donchian breakout
- `strategies/mean_reversion.py` — Bollinger reversion
- `strategies/breakout.py` — volatility expansion
- `models/xgb.py` — feature-based directional prediction
- `models/lstm.py` — sequential prediction
- `intelligence/regime/detector.py` — HMM-based regime classifier
- `intelligence/selector.py` — picks strategy based on regime
- `intelligence/models/ensemble.py` — combines model outputs

**Definition of Done:**
- Each strategy backtests with Sharpe > 0.5 on out-of-sample data
- Ensemble outperforms any individual model on the validation set
- Regime detector identifies trending vs ranging periods with ≥ 70% accuracy on labeled data

### Phase 5 — Paper trading execution (3-5 days)

**Goal:** End-to-end live data, simulated fills.

- `execution/paper_adapter.py` — fills based on next bar with realistic slippage
- `execution/broker.py` — abstraction layer
- `execution/fill_tracker.py` and `pnl_tracker.py`
- Full pipeline runs: live data → features → models → strategy → risk → simulated execution
- Trade journal records every decision (including rejected ones)

**Definition of Done:**
- Bot runs for 7 consecutive days in paper mode without crashing
- Trade journal captures every decision with full context
- P&L matches manual recalculation from logs

### Phase 6 — Live execution (Bybit) (3-5 days)

**Goal:** Real orders, micro size.

- `execution/bybit_adapter.py` — order placement, cancellation, status
- Reconciliation: bot's view of positions matches exchange every 60s
- API key uses trade-only permissions (no withdraw)
- Initial capital: $100 (validation, not full $1000)
- Slippage model validated against real fills

**Definition of Done:**
- 14 consecutive days of live trading with $100
- Reconciliation never disagrees with exchange
- No circuit breaker trips
- Real slippage within 50% of model predictions

### Phase 7 — Learning loop (5-7 days)

**Goal:** The system improves itself.

- `learning/performance.py` — computes all metrics per strategy, per regime, per time window
- `learning/retrainer.py` — scheduled walk-forward retraining (daily for fast models, weekly for slow)
- `learning/evolver.py` — Bayesian optimization of strategy parameters; kills strategies whose live Sharpe drops below threshold for 30 days
- `learning/journal.py` — every trade with full feature context
- `learning/memory.py` — regime → outcome lookup for similarity-based reasoning

**Definition of Done:**
- Retraining pipeline runs end-to-end without manual intervention
- A strategy with deliberately degraded performance is auto-suspended
- New model versions deploy only if walk-forward Sharpe exceeds incumbent

### Phase 8 — Monitoring and operations (3-4 days)

**Goal:** Observable, controllable, alertable.

- FastAPI dashboard: equity curve, open positions, recent trades, system health, model versions, regime
- Prometheus metrics + Grafana
- Telegram bot: alerts on circuit breakers, daily summaries, manual commands (pause, resume, status)
- Daily backup script
- Runbook in `docs/runbook.md`: how to start, stop, recover

**Definition of Done:**
- Dashboard accessible via HTTPS
- Telegram alerts fire correctly for every circuit breaker
- Recovery runbook tested by stopping the bot and restarting from cold

### Phase 9 — Full live deployment (ongoing)

**Goal:** $1,000 live, autonomous, learning.

- Capital ramp from $100 → $250 → $500 → $1,000 over 30 days
- Weekly review (automated report via Telegram)
- Monthly drift analysis: does live performance match backtest?

---

## 11. Database schema

TimescaleDB. All timestamps in UTC, stored as `TIMESTAMPTZ`. All prices and quantities as `NUMERIC` (never float — float arithmetic loses cents).

### 11.1 Core tables

```sql
-- OHLCV bars
CREATE TABLE bars (
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
SELECT create_hypertable('bars', 'ts');
CREATE INDEX ON bars (symbol, timeframe, ts DESC);

-- Tick-level trades (for slippage model calibration)
CREATE TABLE trades_raw (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    price       NUMERIC NOT NULL,
    size        NUMERIC NOT NULL,
    side        TEXT NOT NULL,        -- 'buy' or 'sell'
    trade_id    TEXT NOT NULL,
    PRIMARY KEY (symbol, ts, trade_id)
);
SELECT create_hypertable('trades_raw', 'ts');

-- Order book snapshots (top 20 levels every 1s)
CREATE TABLE orderbook_snapshots (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    bids        JSONB NOT NULL,       -- [[price, size], ...]
    asks        JSONB NOT NULL,
    PRIMARY KEY (symbol, ts)
);
SELECT create_hypertable('orderbook_snapshots', 'ts');

-- Computed features
CREATE TABLE features (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    feature_set TEXT NOT NULL,        -- versioned, e.g. 'v1.2'
    values      JSONB NOT NULL,       -- {feature_name: value}
    PRIMARY KEY (symbol, timeframe, ts, feature_set)
);
SELECT create_hypertable('features', 'ts');
```

### 11.2 Trading tables

```sql
-- Every signal generated, including rejected ones
CREATE TABLE signals (
    signal_id   UUID PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    model_ver   TEXT NOT NULL,
    direction   TEXT NOT NULL,        -- 'long', 'short', 'flat'
    confidence  NUMERIC NOT NULL,
    features    JSONB NOT NULL,       -- snapshot of inputs
    regime      TEXT,
    decision    TEXT NOT NULL,        -- 'approved', 'rejected', 'reason...'
    reject_reason TEXT
);
SELECT create_hypertable('signals', 'ts');

-- Every order placed
CREATE TABLE orders (
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
CREATE TABLE trades (
    trade_id        UUID PRIMARY KEY,
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    model_ver       TEXT NOT NULL,
    regime_at_entry TEXT,
    ts_entry        TIMESTAMPTZ NOT NULL,
    ts_exit         TIMESTAMPTZ,
    entry_price     NUMERIC NOT NULL,
    exit_price      NUMERIC,
    qty             NUMERIC NOT NULL,
    side            TEXT NOT NULL,
    pnl             NUMERIC,
    pnl_pct         NUMERIC,
    fees_total      NUMERIC,
    slippage_total_bps NUMERIC,
    exit_reason     TEXT,             -- 'stop', 'target', 'signal', 'time', 'manual'
    features_at_entry JSONB
);

-- Equity curve, recorded every minute
CREATE TABLE equity (
    ts              TIMESTAMPTZ PRIMARY KEY,
    equity          NUMERIC NOT NULL,
    cash            NUMERIC NOT NULL,
    positions_value NUMERIC NOT NULL,
    drawdown_pct    NUMERIC NOT NULL
);
SELECT create_hypertable('equity', 'ts');

-- Circuit breaker events
CREATE TABLE circuit_breakers (
    ts              TIMESTAMPTZ NOT NULL,
    breaker_type    TEXT NOT NULL,
    trigger_value   NUMERIC,
    action          TEXT NOT NULL,
    auto_resume_at  TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    notes           TEXT
);
```

### 11.3 Learning tables

```sql
-- Strategy lifecycle states
CREATE TABLE strategy_state (
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
CREATE TABLE models (
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

-- Regime memory: store regime descriptors with associated outcomes
CREATE TABLE regime_memory (
    id              UUID PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    regime_vector   JSONB NOT NULL,   -- multidimensional regime descriptor
    forward_return  NUMERIC,          -- realized return next N bars
    n_bars          INTEGER NOT NULL
);
```

---

## 12. Configuration

### 12.1 Layered config

Config loads in this order, each layer overriding the previous:

1. `config/base.yaml` — defaults
2. `config/{mode}.yaml` — mode-specific (paper, live, backtest)
3. Environment variables (prefix `BOT_`)
4. CLI args

Validated via Pydantic. Invalid config = startup failure.

### 12.2 Example `base.yaml`

```yaml
mode: paper                         # paper | live | backtest

exchange:
  name: bybit
  testnet: false

universe:
  symbols: [BTC/USDT, ETH/USDT]
  timeframes: [1m, 5m, 15m, 1h]

risk:
  risk_per_trade_pct: 1.0
  max_position_pct: 25.0
  max_concurrent: 3
  kelly_cap: 0.25
  daily_loss_pause_pct: 3.0
  weekly_loss_pause_pct: 8.0
  shutdown_drawdown_pct: 15.0
  consec_losses_suspend: 5

execution:
  default_order_type: limit
  limit_price_offset_bps: 2.0
  max_slippage_bps: 20.0

models:
  ensemble_weights: {lstm: 0.4, xgb: 0.4, rl: 0.2}
  min_confidence: 0.60
  retrain_schedule:
    xgb: daily
    lstm: weekly
    rl: continuous

monitoring:
  telegram_chat_id: ${TELEGRAM_CHAT_ID}
  alert_levels: [warning, error, critical]

logging:
  level: INFO
  format: json
```

### 12.3 Secrets

Never in config files. Always in environment variables, sourced from `.env` (gitignored), with permissions `600` on the instance:

```
# Exchange (trade-only permissions, never withdraw)
BYBIT_API_KEY=...
BYBIT_API_SECRET=...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_AUTHORIZED_CHAT_IDS=...
TELEGRAM_TOTP_SECRET=...            # optional, for critical-command 2FA

# Database
DATABASE_URL=postgresql://...

# Optional macro data
FRED_API_KEY=...                    # optional

# Backups (DigitalOcean Spaces, S3-compatible)
DO_SPACES_BUCKET=...
DO_SPACES_KEY=...
DO_SPACES_SECRET=...
```

---

## 13. Backtesting requirements

### 13.1 Core requirement

The backtester and live trader must share code paths for everything except the broker adapter. If a strategy behaves differently in backtest vs live, that's a backtester bug. Specifically:

- Same risk engine code
- Same position sizer code
- Same trade approver code
- Same signal generation code
- Different: broker adapter (paper/live/backtest)

### 13.2 Walk-forward methodology

For any model deployment, the validation must be walk-forward, never simple train/test split:

```
Window 1:  train [Jan 2019 - Jun 2020]  →  test [Jul 2020 - Sep 2020]
Window 2:  train [Apr 2019 - Sep 2020]  →  test [Oct 2020 - Dec 2020]
Window 3:  train [Jul 2019 - Dec 2020]  →  test [Jan 2021 - Mar 2021]
...
```

The model gets retrained at each step. Reported metrics are aggregated across all test windows.

### 13.3 Slippage model

Cannot use a fixed slippage assumption. Model must depend on:

- Order size relative to recent average volume
- Current order book depth at the time of the order
- Volatility of the bar
- Order type (market vs limit)

Initially calibrated from public trades data; refined from real fills after Phase 6.

### 13.4 Reports

Every backtest produces:

- Equity curve (with drawdown shading)
- Trade list with per-trade attribution
- Per-strategy and per-regime metrics breakdown
- Comparison to buy-and-hold benchmark
- Monte Carlo on trade ordering (does the equity curve depend on luck?)
- Out-of-sample / in-sample Sharpe ratio
- Stored as JSON + HTML in `data/backtests/{run_id}/`

---

## 14. Strategy framework

### 14.1 Strategy contract

Every strategy implements:

```python
class Strategy(ABC):
    name: str
    version: str
    params: dict

    @abstractmethod
    def required_features(self) -> list[str]:
        """Features this strategy needs."""

    @abstractmethod
    def required_history_bars(self) -> int:
        """Minimum lookback in bars."""

    @abstractmethod
    def generate_signal(
        self,
        features: pd.DataFrame,
        regime: str,
        portfolio_state: PortfolioState,
    ) -> Signal | None:
        """Pure function. No side effects. No I/O."""

    def fits_regime(self, regime: str) -> bool:
        """Does this strategy work in the given regime?"""
        return regime in self.compatible_regimes
```

### 14.2 Strategy lifecycle

States in `strategy_state` table:

- **shadow** — runs against live data, signals logged, no trades placed. Required for first 14 days.
- **live** — trades placed with full size
- **suspended** — temporarily disabled (auto: due to circuit breaker; manual: by operator)
- **retired** — permanently disabled

Auto-promotion (shadow → live) requires: ≥ 50 shadow signals, hypothetical Sharpe > 1.0.
Auto-suspension (live → suspended): 5 consecutive losses, OR 30-day live Sharpe < 0.

### 14.3 Strategy evolution

Bayesian optimization over strategy parameters runs weekly. Process:

1. Define parameter search space per strategy
2. For each candidate parameter set, run walk-forward backtest on last 90 days
3. If best candidate's out-of-sample Sharpe exceeds incumbent's by ≥ 0.3, promote candidate
4. Old version moves to retired state, new version starts in shadow

---

## 15. Machine learning pipeline

### 15.1 Feature engineering

Features must be:

- **Stationary** — raw prices forbidden as features. Use returns, ratios, normalized indicators.
- **Time-aware** — never use future data. Every feature has a clear "as of" timestamp.
- **Versioned** — feature sets are tagged. Retraining a v1.2 model uses v1.2 features.

#### v1 feature categories

**Price features** (per timeframe: 1m, 5m, 15m, 1h, 4h)
- Log returns at multiple horizons
- Realized volatility (ATR-based) at multiple windows
- Range/ATR ratio
- Distance from N-period high/low
- Volatility-of-volatility

**Volume features**
- Relative volume (vs 20-period average)
- Volume-weighted price (VWAP) deviation
- Dollar volume

**Microstructure features**
- Order book imbalance (bids vs asks at top-N levels)
- Bid-ask spread (absolute and as percentage)
- Depth at N basis points from mid
- Recent trade flow (buy vs sell aggression)

**Technical features**
- RSI (multiple periods)
- MACD signal and histogram
- Bollinger %B
- Donchian channel position
- ADX (trend strength)

**Regime features (own asset)**
- HMM regime classification
- Trend strength score
- Volatility regime (low / normal / elevated / extreme)

**Cross-asset regime features** — added in v1 to capture macro context without parsing news

These features encode the same context a human gets from reading news, but derived from market action rather than text. They update slowly (daily for most, hourly for VIX) and tell the bot what kind of macro environment it's in.

| Feature | Source | Update frequency | Purpose |
|---|---|---|---|
| VIX level | yfinance (`^VIX`) | 15 min | Equity market fear gauge |
| VIX 1-day change | yfinance | 15 min | Fear regime shift |
| DXY level | yfinance (`DX-Y.NYB`) | 1 hour | Dollar strength |
| DXY 5-day trend | yfinance | 1 hour | Dollar regime |
| S&P 500 1-day return | yfinance (`^GSPC`) | 1 hour | Risk-on/off |
| S&P 500 20-day vol | yfinance | 1 hour | Equity vol regime |
| Gold 1-day return | yfinance (`GC=F`) | 1 hour | Risk-off / inflation hedge |
| BTC-S&P correlation 30d | computed | 1 hour | Decoupling indicator |
| Cross-asset volatility correlation spike | computed | 15 min | "Something is happening everywhere" flag |

The bot doesn't need to know *what* is happening — it just needs to know *that* something cross-market is happening. When VIX, DXY, and BTC volatility all spike together, that's a "macro event" signature. The strategies can learn to behave differently in those conditions.

**Calendar features** — known scheduled events

| Feature | Source | Update | Purpose |
|---|---|---|---|
| Hours until next FOMC | static schedule | continuous | Pre-event de-risk |
| Hours until next CPI release | static schedule | continuous | Pre-event de-risk |
| Hours until next NFP release | static schedule | continuous | Pre-event de-risk |
| Days since last BTC halving | static schedule | continuous | Cycle position |
| Days until next BTC halving | static schedule | continuous | Cycle position |
| Hours until next options expiry | computed | continuous | Crypto-specific event |
| Hour of day (UTC) | clock | continuous | Liquidity patterns |
| Day of week | clock | continuous | Weekend vs weekday liquidity |

The strategies can learn empirically that, for example, holding period is shorter in the 4 hours before FOMC, or that breakouts on Sunday have lower follow-through.

#### Explicitly NOT included in v1

These were considered and deferred to v2:

- **News sentiment scores** — deferred. See Section 8.5 for reasoning.
- **Twitter/Reddit sentiment** — deferred; high noise, costly APIs
- **On-chain analytics** (exchange flows, miner behavior, stablecoin supply) — most promising deferral; requires Glassnode or CryptoQuant subscription ($30-300/month) and integration work. Revisit at v2 with explicit cost/benefit.
- **Daily macro releases parsed from news** (specific CPI/NFP values) — already captured by calendar proximity features and post-event price action

#### Feature lifecycle and pruning

Phase 7's feature importance analyzer reviews feature contributions monthly. Features whose mean absolute importance is below 0.5% of total across all models for 60 days are flagged for removal. This prevents feature bloat and forces continuous justification for every input.

### 15.2 Model registry

Every trained model is registered with:

- Unique ID (UUID)
- Name + semantic version
- Training data window
- Validation window
- Backtest metrics (Sharpe, max DD, hit rate, profit factor)
- Feature set version
- Code commit hash at training time
- Artifact path (the model file itself)

A model cannot be deployed unless:

- Out-of-sample Sharpe ≥ 1.0
- Max drawdown ≤ 20% in backtest
- Hit rate ≥ 50% (for directional models)
- It beats the incumbent on at least 2 of 3 metrics

### 15.3 Online learning

Different cadences for different model types:

- **XGBoost models:** Full retrain nightly on rolling 180-day window. Cheap.
- **LSTM models:** Full retrain weekly. Warm-start from previous weights.
- **RL agent:** Continuous online updates (PPO with replay buffer of recent trades).

Retraining never replaces the live model directly. New version goes through:

1. Train
2. Walk-forward backtest validation
3. Shadow mode (decisions logged, not executed) for 7 days
4. Promote to live if shadow performance matches backtest within tolerance

---

## 16. Execution layer

### 16.1 Order types

Default: limit orders, posted slightly inside the best bid/ask (configurable, default 2 bps). Market orders only used when:

- Stop loss is hit (use Bybit's native TP/SL on the order)
- Position needs immediate closure (circuit breaker, manual `/flatten`)

### 16.2 Stop losses

**HARD CONSTRAINT:** every position must have an active stop loss either as a Bybit native SL on the entry order or as a separate stop order on the order book. Not a virtual stop in the bot's memory — a real instruction at the exchange. If for any reason the stop registration fails (rejection, network error, ambiguous response), the position must be closed immediately at market.

### 16.3 Instrument rules and precision

**CRITICAL:** Bybit rejects orders that don't conform to per-symbol precision and minimum requirements. The bot must respect every instrument-specific rule fetched from `/v5/market/instruments-info`.

#### 16.3.1 Per-symbol parameters

Every symbol has these parameters in its `lotSizeFilter` and `priceFilter`:

| Parameter | Meaning | Example (BTC/USDT spot) |
|---|---|---|
| `basePrecision` | Quantity increment (decimals for the base asset) | 0.000001 (6 decimals) |
| `quotePrecision` | Quote currency precision | 0.0000001 (7 decimals) |
| `tickSize` | Minimum price increment | varies by symbol |
| `qtyStep` | Minimum quantity increment | varies by symbol |
| `minOrderQty` | Smallest order quantity | 0.000011 BTC |
| `maxOrderQty` | Largest order quantity | 83 BTC (limit) |
| `minOrderAmt` | Smallest order notional value | 5 USDT (subject to change) |
| `maxOrderAmt` | Largest order notional value | 8,000,000 USDT |

These values **change**. Bybit publishes announcements when minimums or tick sizes are updated (e.g., December 2025, March 2026, April 2026 saw spot pair changes). The bot must adapt automatically.

#### 16.3.2 Required behavior — `src/execution/instrument_rules.py`

The `InstrumentRules` module:

1. **Fetches all symbols' rules at startup** from `/v5/market/instruments-info` and caches them in memory and in the database
2. **Refreshes every 24 hours** automatically; refreshes immediately on any rejection that may indicate a rule change
3. **Validates every order before sending** — any order that fails local validation never goes to the exchange
4. **Applies rounding** before order placement:
   - **Quantity:** floor to `qtyStep` — never round up (would exceed risk allowance)
   - **Limit buy price:** floor to `tickSize` — never above the requested price
   - **Limit sell price:** ceiling to `tickSize` — never below the requested price
   - **Stop trigger price:** round to nearest `tickSize` (direction depends on stop type)
5. **Validates after rounding:**
   - quantity ≥ `minOrderQty`
   - quantity × price ≥ `minOrderAmt`
   - quantity ≤ `maxOrderQty`

If after rounding any minimum is no longer met, the order is rejected locally with a clear log entry. The signal counts as rejected at Stage 9 (cost-vs-edge) — not as an execution failure.

#### 16.3.3 Implications for $1,000 account sizing

With `minOrderAmt` of 5 USDT and risk-per-trade of $10, most signals will produce orders well above the minimum. But corner cases exist:

- A very tight stop (e.g. ATR-based stop at 0.3% distance) on a $1,000 account → calculated size could be $3,300 *exposure*, but limited to the 25% position cap of $250.
- A very wide stop (3% distance) → calculated size could be $333, OK.
- After a drawdown bringing the account to $500, with same wide stop → size could be $166, OK.
- Edge case: account at $300, very wide stop, micro signal → size below $5 → **signal rejected at the broker minimum check**.

The position sizer must always check the broker minimum and reject the trade with reason `"size_below_broker_minimum"` if it fails. This is logged for analysis but is not an error condition.

#### 16.3.4 Rejection handling

When Bybit rejects an order, the response code is logged with full context. Specific rejection codes get specific handling:

| Bybit code | Meaning | Action |
|---|---|---|
| 110007 | Quantity precision mismatch | Refresh instrument rules, log as bug |
| 110008 | Price precision mismatch | Refresh instrument rules, log as bug |
| 110017 | Quantity below minimum | Should have been caught locally — log as bug, refresh rules |
| 110014 | Insufficient balance | Halt strategy, alert (state mismatch) |
| 30067 | Order limit exceeded | Back off, retry later |
| Other | Unknown | Log, escalate to operator alert |

A precision-related rejection is **always a bug** because local validation should have caught it. These rejections fire a critical alert and the affected strategy is suspended pending investigation.

### 16.4 Overnight fees and holding costs

#### 16.4.1 Spot trading: no overnight fees

The bot trades spot only. Spot trading has **no overnight fees, no funding rates, no swap fees, no rollover charges**. You own the asset outright. A position held for 1 minute and a position held for 30 days incur identical fees: just the entry and exit commission.

This is one of the reasons spot was chosen. It eliminates an entire category of cost and complexity.

#### 16.4.2 Why this matters

Many trading systems written for forex, CFDs, or futures incorrectly carry over assumptions about holding costs. For our system:

- **No daily P&L charge** for holding positions overnight
- **No funding fee calculation** in the cost-vs-edge check
- **No "close before rollover" logic** required
- **No interest rate parity considerations**

#### 16.4.3 What spot does charge

The only costs on spot:

- **Trading commission** (currently 0.10% maker, 0.10% taker for non-VIP)
- **Network/withdrawal fees** — only if moving assets off-exchange (not applicable to bot operation; bot keeps everything on exchange)
- **Slippage** — implicit cost from spread and impact, modeled separately

The fee schedule is fetched at startup via `/v5/account/fee-rate` (returns the user's actual VIP-tier fee, which may differ from the public schedule for high-volume accounts). The cost-vs-edge check uses the actual fees, not assumed fees.

#### 16.4.4 HARD CONSTRAINT: spot only

The bot has the `mode: spot` setting hardcoded as a category in every order. The execution layer rejects any attempt to set `category: linear`, `category: inverse`, or `category: option` with a configuration error. This prevents:

- Accidental futures trading
- Funding fee exposure
- Liquidation risk
- Leverage exposure beyond 1×

If derivatives are ever added in v2, this constraint is removed deliberately, with new HARD CONSTRAINTS introduced for funding fee handling, liquidation buffers, and leverage caps.

### 16.5 Reconciliation

Every 60 seconds, the bot's view of positions is reconciled with the exchange's view. Any discrepancy → halt trading, alert. Recovery requires manual investigation.

### 16.6 Idempotency

Every order has a client-generated UUID (`orderLinkId` on Bybit). The exchange API call is idempotent — retries with the same UUID never produce duplicate orders. Critical for handling network failures.

### 16.7 Capital scaling guidance

The bot's economics improve significantly with capital, but not in the way that's intuitive. This guidance helps frame expectations:

| Capital | Fixed cost % | Trading fees % | Required gross monthly | Notes |
|---|---|---|---|---|
| $1,000 | 3.0% | ~10% | ~13% | Tough hurdle. Treat as validation phase. |
| $5,000 | 0.6% | ~10% | ~10.6% | Fixed cost becomes minor. |
| $10,000 | 0.3% | ~10% | ~10.3% | Comfortable threshold. VIP tiers approach. |
| $25,000 | 0.12% | ~9% | ~9.1% | VIP 1 reachable with active trading. |
| $100,000 | 0.03% | ~8% | ~8% | VIP 2-3 reachable. Slippage becomes a concern. |

**Key insight:** trading fees as a percentage of capital don't scale down with capital — they scale with turnover, which scales proportionally with capital. The thing that improves is fixed costs (infrastructure) becoming negligible, and access to VIP fee tiers at higher monthly volumes.

The recommended capital ramp:

1. Phase 9.1: $1,000 — full v1 validation. Sustain for 90 days with positive metrics.
2. Phase 9.2: $5,000 — first scale-up. 60 days minimum.
3. Phase 9.3: $10,000+ — sustained scaling, only when system has proven itself across multiple regimes.

**Re-validation when scaling:** when capital increases by ≥ 3×, the slippage model must be re-validated at the new size before going live. Larger orders move the order book more — the model's estimates may need updating.

---

## 17. Learning loop details

### 17.1 Performance metrics

Computed continuously, persisted to `equity` table every minute:

- **Equity curve, drawdown**
- **Sharpe ratio** — annualized, computed over rolling 30 / 90 / 365 day windows
- **Sortino ratio** — same windows
- **Calmar ratio** — return / max DD
- **Win rate, average win / average loss, profit factor**
- **Per-strategy, per-regime, per-symbol breakdowns**
- **Slippage tracking** — actual vs predicted, per strategy

### 17.2 Drift detection

Live performance is continuously compared to backtest expectations. If live Sharpe falls > 2σ below backtest Sharpe over a 30-day window, an alert fires. If it falls > 3σ, the affected strategy is auto-suspended.

### 17.3 Feedback to features

The regime memory store enables similarity-based reasoning: when current market state vector closely matches a historical state, the historical outcome is available as additional context. This is consulted (not commanded) by the ensemble's weighting.

---

## 18. End-to-end trade decision walkthrough

This section illustrates the full trade lifecycle with concrete numbers, showing how every layer of the architecture contributes to a single trade decision. It is intentionally narrative — engineers building or modifying any layer should refer to this to understand how their work fits into the whole.

**Scenario:** Tuesday 14:32 UTC. BTC at $67,000. Bot has been running 30 days. Account equity $1,047. One existing open position in ETH.

### Stage 1 — New data arrives (T+0ms)

The 1-minute candle for BTC/USDT closes at 14:32:00 UTC. Bybit websocket pushes the candle. Data validator checks: timestamp matches expected, no gap from previous candle, OHLC values consistent (high ≥ low, etc.). Stored in TimescaleDB.

Decision point: only candle closes trigger evaluation; intra-candle ticks just update stored data.

### Stage 2 — Features computed (T+50ms)

Feature engine recomputes ~50 features across timeframes (1m, 5m, 15m, 1h, 4h):
- Returns at multiple horizons
- Realized volatility, ATR
- Volume relative to 20-period average (e.g., 1.3×)
- Order book imbalance (e.g., bids 60% / asks 40%)
- Technical indicators: RSI(14) on 15m = 58, MACD on 1h crossed up 2 bars ago, BB %B = 0.78
- Cross-asset regime features: VIX = 14.2 (low), DXY trend = down (risk-on), S&P = +0.4% today
- Calendar: hours to next FOMC = 287, hour-of-day = 14
- BTC-S&P 30d correlation = 0.31

All features tagged with timestamp; immutable record of what was known at this moment.

### Stage 3 — Regime detected (T+80ms)

HMM regime classifier consumes latest features:
- Regime: `trending_up` (confidence 0.74)
- Volatility regime: medium
- Cross-asset regime: risk_on
- Last regime change: 6 hours ago (was ranging)

### Stage 4 — Strategy selected (T+85ms)

Strategy selector consults active strategies and compatibility matrix:

| Strategy | Status | Fits trending_up? | Fits risk_on? |
|---|---|---|---|
| trend_v2 | live | ✓ | ✓ |
| mean_reversion_v1 | live | ✗ | – |
| breakout_v1 | live | ✓ | ✓ |
| trend_v3 | shadow | ✓ | ✓ (logs only) |

Two live strategies eligible: `trend_v2` and `breakout_v1`. Both run independently. Walkthrough follows `trend_v2`.

### Stage 5 — Models score the signal (T+150ms)

`trend_v2` calls the model ensemble. Three models run in parallel:
- **LSTM**: P(price up over next 60 min) = 0.68
- **XGBoost**: directional score = +0.55 (range -1 to +1)
- **RL agent**: action = ENTER_LONG, confidence 0.71

Ensemble combines using config weights (LSTM 0.4, XGB 0.4, RL 0.2):
- Weighted directional score: +0.62
- Weighted confidence: 0.72

### Stage 6 — Signal produced (T+155ms)

Strategy assembles a signal object with full context:

```
Signal {
  symbol: BTC/USDT
  direction: LONG
  confidence: 0.72
  expected_edge_bps: 35
  expected_holding_minutes: 60
  stop_loss_atr_multiple: 1.5
  features_snapshot: {...}      # all features captured
  regime: trending_up
  cross_asset_regime: risk_on
  strategy: trend_v2
  model_versions: {lstm: v1.4, xgb: v2.1, rl: v0.8}
  timestamp: 2026-05-12T14:32:00.155Z
}
```

Written to `signals` table immediately — even if rejected later, the decision trail is preserved.

### Stage 7 — Risk gates checked (T+158ms)

Risk engine runs every hard constraint as a sequential gate. Any failure rejects immediately.

| Gate | Check | Result |
|---|---|---|
| Confidence floor | 0.72 ≥ 0.60 | ✓ |
| Daily loss circuit | -0.4% today vs 3% limit | ✓ |
| Weekly loss circuit | -1.8% week vs 8% limit | ✓ |
| Total drawdown | -2.1% from peak vs 15% | ✓ |
| Max concurrent positions | 1 open vs 3 limit | ✓ |
| Strategy not suspended | trend_v2 active | ✓ |
| Data freshness | latest candle 8s old | ✓ |
| Clock drift | 0.2s vs 1s limit | ✓ |
| Correlation check | proposed BTC vs existing ETH = 0.82 | ✓ |
| Per-symbol cooldown | last BTC trade 47 min ago | ✓ |
| Bot not paused | running normally | ✓ |

All 11 gates pass.

### Stage 8 — Position sized (T+160ms)

Position sizer calculates trade size:

```
Account equity:           $1,047
Risk per trade (1%):      $10.47
ATR(14) on 15m:           $480
Stop distance (1.5 ATR):  $720 (~1.07% from entry)
Raw size:                 $10.47 / 1.07% = $978
Kelly fraction (30d):     0.18 (within 0.25 cap)
Kelly-adjusted size:      $978 × 0.18 = $176
Confidence multiplier:    0.72 → 0.86
Final size before caps:   $176 × 0.86 = $151
Hard caps:
  Max single position (25%): $262 — OK
  Min trade size:            $10 — OK
Approved size:            $151 (= 0.002253 BTC at $67,000)
```

### Stage 9 — Cost-vs-edge check (T+162ms)

Trade approver does final economic check:

```
Position size:    $151
Expected edge:    35 bps = $0.53
Expected costs:
  Entry fee:      $0.15
  Exit fee:       $0.15
  Slippage:       $0.08
  Total:          $0.38
Edge multiple:    1.4× (required: 1.2×)
APPROVED
```

If edge multiple was below 1.2×, trade would be rejected even with all other gates passing.

### Stage 10 — Order placed (T+200ms)

Execution layer takes over:

1. Generate idempotency UUID
2. Apply instrument rounding:
   - Quantity: 0.002253 BTC → floor to qtyStep = 0.002253 ✓
   - Price target: $67,002.00 → round to tickSize ✓
3. Validate against broker minimums:
   - Quantity ≥ minOrderQty (0.000011) ✓
   - Notional ≥ minOrderAmt ($5) ✓
4. Place limit buy: 0.002253 BTC @ $67,002 (2 bps inside ask)
5. Wait for fill (typical < 5 seconds)
6. Filled at $67,002.50
7. Place stop loss: STOP-MARKET sell at $66,282.50

If stop registration fails within 3 seconds, position closed defensively. We never hold an unprotected position.

Telegram sends:

```
🟢 BTC/USDT LONG filled @ 67,002.50
Size: $151 (0.002253 BTC)
Stop: 66,282.50 (-1.07%, -$10.47)
Strategy: trend_v2 | Regime: trending_up
```

### Stage 11 — Position managed (T+200ms to hours later)

Bot evaluates exit conditions on every new candle:

Exit triggers (any one closes position):
- Stop loss hit on exchange (automatic, fastest)
- Strategy emits exit signal
- Time-based exit if `expected_holding_minutes × 3` elapsed without target reached
- Regime change to incompatible regime
- Trailing stop activated (if profit > 1× ATR, stop ratchets up)
- Manual `/flatten` command
- Any circuit breaker tripping

In this trade: 47 minutes pass, BTC reaches $67,580 (+0.86% unrealized). Trailing stop activates and moves to $67,140. 23 minutes later BTC pulls back to $67,140 and the trailing stop fires.

### Stage 12 — Trade closed and learning loop fed

Exit fills at $67,138 (small slippage):

```
Entry:    $67,002.50
Exit:     $67,138.00
Size:     0.002253 BTC
Gross:    +$0.30
Fees:     -$0.30 (0.20% round trip)
Slippage: -$0.04
Net P&L:  -$0.04
```

A small loss — trailing stop didn't quite let the trade work. This is normal.

Trade record enriched with:
- Full feature snapshot at entry
- Regime at entry and exit
- All decisions (signals, approvals, fills) cross-referenced
- Slippage actual vs predicted (predicted $0.08, actual $0.04 — model conservative)

Data flows into Layer 5:
- **Performance analyzer** updates rolling Sharpe for `trend_v2`
- **Slippage tracker** notes this trade for the model
- **Strategy state** updates trade count and P&L
- **Memory store** records this regime → outcome pair for similarity lookups

### What you actually see

From your perspective, all of stages 1-10 happened in under 250ms. You receive one Telegram notification at fill (stage 10) and possibly another at close (stage 12). In between, you've been doing other things. The dashboard logged every stage with full context for any later investigation.

### Critical observation: the rejection rate

**Most signals never become trades.** In a typical day the bot might generate 200+ signals across both symbols and multiple strategies, but only 5-15 survive every gate. Approximate rejection rates:

| Stage | Reject rate | Why |
|---|---|---|
| Stage 5/6 (model confidence) | ~50% of signals | Below 0.60 threshold |
| Stage 7 (risk gates) | ~25% of remaining | Cooldown, correlation, limits |
| Stage 9 (cost-vs-edge) | ~15% of remaining | Insufficient edge after fees |
| Stage 10 (broker validation) | < 1% | Should be near zero |

This filtering is the entire point. Every gate that rejects a signal is a gate that prevents a likely-bad trade.

---

## 19. Operator interface — Telegram and dashboard

The bot has two complementary operator interfaces. They serve different purposes and you'll use both.

### 19.1 Interface philosophy

| Interface | Role | When you use it |
|---|---|---|
| **Telegram** | Real-time alerts and quick commands | Daily — push notifications on phone, issue commands from anywhere |
| **Dashboard** | Deep visibility and historical analysis | Weekly — investigation, post-mortem, performance review |

Telegram is the primary interface. The dashboard is the analytical companion. The bot must function fully even if both are unavailable — they are observability and control surfaces, not part of the trading logic.

---

### 19.2 Telegram — detailed specification

#### 19.2.1 Bot setup procedure

This must be completed before Phase 6 (live trading) and is documented in `docs/setup/telegram.md`. The procedure:

1. Open Telegram, search for `@BotFather`, start a chat
2. Send `/newbot` to BotFather
3. Provide a display name (e.g. "My Trading Bot")
4. Provide a username ending in `bot` (e.g. `my_trading_bot`)
5. BotFather replies with an HTTP API token of the form `123456789:ABCdefGhIJKlmNoPQRsTUVwxyz`
6. **Save this token immediately** — it is the bot's password. Store in `.env` as `TELEGRAM_BOT_TOKEN`. Never commit.
7. Search for your new bot by its username, open the chat, click Start
8. Send any message (e.g. "hi")
9. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, replacing `<TOKEN>` with your token
10. In the JSON response, find the field `result[0].message.chat.id` — this is your numeric chat ID
11. Save as `TELEGRAM_CHAT_ID` in `.env`
12. Send `/setcommands` to BotFather, select your bot, paste the command list (see 17.2.4)
13. Optionally send `/setprivacy` and `/setjoingroups` to lock the bot to direct messages only

After setup, the bot's first action on startup is to send a "Bot online" message to the configured chat ID. If that message fails, the bot halts — Telegram is considered a critical observability channel.

#### 19.2.2 Configured authorization

**HARD CONSTRAINT:** the bot only accepts commands from chat IDs listed in `TELEGRAM_AUTHORIZED_CHAT_IDS` (env var, comma-separated). Any command from any other chat is silently ignored and logged as a security event. By default, only your personal chat ID is in this list.

For higher security, the bot supports a two-factor option: critical commands (`/flatten`, `/shutdown`) require a TOTP code in the confirmation message. Configured via `TELEGRAM_REQUIRE_TOTP=true` and `TELEGRAM_TOTP_SECRET` (a base32 secret added to your authenticator app). Recommended for live mode.

#### 19.2.3 Notification levels and contents

Every notification has a level. Levels are filterable per-chat-id (so you could route critical to one chat, info to another).

**Info level:**
- **Daily summary** at 00:00 UTC. Contents: yesterday's P&L (absolute and percent), number of trades, win rate, current equity, current open positions, current regime, top winning and losing trade, any strategies that were promoted/demoted.
- **Trade fills** (configurable, off by default after first 30 days). Format: `🟢 BTC/USDT LONG filled @ 67,234.50 size $245 (trend_v2 | regime: trending_up)`
- **Weekly review** every Sunday 00:00 UTC. Contains weekly P&L, Sharpe, drawdown, comparison to backtest expectation, any drift detected.

**Warning level:**
- Slippage anomaly: actual slippage > 2× expected (alert) or > 3× (auto-suspend)
- Model confidence drop: ensemble confidence on recent signals fell below 0.65 average
- Single losing trade > 0.5% of equity
- Data feed lag: candle arriving > 30s late (still within tolerance but trending toward halt)
- Reconciliation discrepancy < $5 (small, auto-corrected)
- Strategy entered cooldown after 3 consecutive losses

**Error level:**
- Strategy auto-suspended (5 consecutive losses or 30-day Sharpe < 0)
- Daily loss circuit breaker tripped (3% daily loss → 24h pause)
- Weekly loss circuit breaker tripped (8% weekly loss → 7d pause, manual restart required)
- Order placement failed after 3 retries
- Stop loss order failed to place — position closed defensively
- Model retraining job failed
- Unable to reach exchange API for > 60 seconds

**Critical level:**
- Total drawdown circuit breaker (15% from peak → full shutdown)
- Position reconciliation mismatch > $5 (state drift, halt all trading)
- Exchange disconnected > 5 minutes during market hours
- Database connection lost
- System clock drift > 1 second from exchange time
- Bot process crashed and was restarted by supervisor
- API key authentication failure
- Withdraw permission detected on API key (security violation — keys must be trade-only)

#### 19.2.4 Command reference

Commands the bot accepts. All require authorization (see 17.2.2). Commands marked 🔒 require explicit confirmation within 30 seconds.

| Command | Description | Confirmation |
|---|---|---|
| `/start` | Welcome message + register chat | No |
| `/status` | System health: mode, equity, open positions, today's P&L, current regime, active strategies, any active circuit breakers | No |
| `/equity` | Current equity, today's P&L, drawdown from peak | No |
| `/positions` | All open positions with entry, current P&L, stop loss | No |
| `/trades [n]` | Last n trades (default 10) with summary | No |
| `/strategies` | List active strategies and their 30-day live performance | No |
| `/regime` | Current detected regime per symbol with confidence | No |
| `/models` | Active model versions and metadata | No |
| `/risk` | Current exposure, distance to each circuit breaker | No |
| `/pause` | Pause new entries; existing positions managed normally | No |
| `/resume` | Resume normal trading | No |
| `/flatten` | Close all positions immediately at market | 🔒 Yes |
| `/shutdown` | Halt all bot activity, requires manual restart | 🔒 Yes |
| `/cancel` | Cancel a pending confirmation | No |
| `/mute [level]` | Mute notifications at or below the given level for 1 hour | No |
| `/unmute` | Restore default notification levels | No |
| `/help` | Show this command list | No |

For confirmable commands, the flow is:

```
User: /flatten
Bot:  ⚠️ Confirm: close 2 open positions ($487 notional)?
      Reply YES within 30 seconds to confirm, or /cancel.
User: YES
Bot:  ✅ Flattening positions...
      Closed BTC/USDT @ 67,210 (P&L -$3.20)
      Closed ETH/USDT @ 3,524 (P&L +$8.10)
      Done. Bot is paused. /resume to restart trading.
```

If TOTP is enabled, the confirmation message must include the current TOTP code: `YES 123456`.

#### 19.2.5 Message formatting standards

- All money values shown to 2 decimal places, with currency suffix
- All percentages shown to 2 decimal places with `%` suffix
- All times shown in UTC with `UTC` suffix unless explicitly user-timezone
- Use minimal emoji as visual cues only: 🟢 long fill, 🔴 short fill or stop hit, ⚠️ warning, 🛑 critical, ✅ success, ⏸ paused, ▶️ resumed
- No marketing language. No exclamation points.
- Failures must explain *why* in plain English, not stack traces

Example daily summary:

```
📊 Daily Summary — 2026-01-15 UTC

Equity: $1,047.32 (+$8.40 / +0.81% today)
Trades today: 7 (4W / 3L, win rate 57%)
Best: BTC/USDT trend_v2 +$5.20
Worst: ETH/USDT mean_rev_v1 -$2.10

Drawdown from peak: -2.1%
Current regime: trending_up (BTC), ranging (ETH)
Active strategies: 4 (1 in shadow)

No circuit breakers triggered.
```

Example warning:

```
⚠️ Slippage Warning

Strategy: mean_rev_v1
Symbol: ETH/USDT
Expected slippage: 3 bps
Actual slippage: 8 bps (2.7×)

Strategy continues. If exceeds 3× threshold, will auto-suspend.
View details: https://yourbot.example.com/trades/abc-123
```

Example critical alert:

```
🛑 CRITICAL: Total Drawdown Breaker

Equity peak: $1,084.20 (2026-01-12)
Current equity: $921.57
Drawdown: -15.0%

ALL TRADING HALTED. Open positions closed.
Manual review and restart required.

Last 10 trades and circuit breaker context:
https://yourbot.example.com/incident/2026-01-15
```

#### 19.2.6 Implementation notes

- Use `python-telegram-bot` v21+ (async API)
- Notifications go through a queue — if Telegram API is down, messages buffer up to 1 hour, then flush
- Outbound messages are rate-limited to 30 per minute to respect Telegram's limits
- Inbound commands are processed asynchronously — never block the trading loop
- Every Telegram event (sent message, received command, auth failure) is logged

---

### 19.3 Dashboard — detailed specification

#### 19.3.1 Architecture

- **Backend:** FastAPI service running on the droplet as a systemd service (`tradingbot-dashboard.service`), bound to the Tailscale interface on port 8000
- **Frontend:** Static HTML + vanilla JavaScript + Chart.js for graphs (no SPA framework — keep it simple and fast)
- **Access:** Tailscale private network. The dashboard binds to the Tailscale IP only, never to the public internet. No reverse proxy, no public TLS certificate, no exposed ports.
- **Authentication:** Tailscale handles network-level access control (only devices on your tailnet can reach it). An optional HTTP Basic Auth layer can be added for defense in depth.
- **Real-time updates:** WebSocket for equity curve and position updates; REST for everything else

#### 19.3.2 Access setup (Tailscale — recommended)

Tailscale is the default and recommended access method. No domain, no certificates, no public exposure.

1. Create a free Tailscale account
2. Install Tailscale on the droplet: `curl -fsSL https://tailscale.com/install.sh | sh` then `tailscale up`
3. Install Tailscale on your laptop and phone, log into the same tailnet
4. The dashboard becomes reachable at `http://<instance-tailscale-name>:8000` from any of your devices, anywhere, with no public internet exposure
5. Tailscale provides its own encrypted transport, so no TLS setup is required

#### 19.3.3 Optional public access (domain + nginx)

Only if the operator specifically wants public access (not recommended for a personal trading bot):

1. Buy a domain (~$12/year)
2. Point an A record at the droplet's public IP
3. Install nginx as a reverse proxy with HTTP Basic Auth and an IP allowlist
4. Use certbot (Let's Encrypt) for TLS certificates
5. Open only port 443 in the DigitalOcean firewall

This path adds attack surface and maintenance. Tailscale is strictly safer and simpler. Documented only for completeness.

#### 19.3.4 Pages and contents

**Overview page** (`/`)

The home page. Renders within 1 second on a fresh load.

- Top banner: system status (🟢 Trading | ⏸ Paused | 🛑 Shutdown | ⚠️ Circuit breaker active)
- Equity curve chart (last 30 days, with drawdown shading underneath)
- Today's stats panel: P&L, trades count, win rate, current drawdown
- Open positions table: symbol, side, entry, current price, P&L, stop loss, time held
- Active circuit breakers (none usually): type, triggered at, auto-resume time
- Recent activity ticker: last 10 events (trades, regime changes, model updates, alerts)

**Trades page** (`/trades`)

- Filterable table: by symbol, strategy, outcome (win/loss), date range, regime
- Per-trade row: timestamp, symbol, strategy, side, entry, exit, P&L, P&L%, fees, slippage, exit reason
- Click any trade for detail view
- Trade detail view: full feature snapshot at entry, decision log, related signals (including ones that were rejected for the same symbol within 5 min), order book at entry, P&L attribution (price move vs fees vs slippage)
- Aggregations panel: total P&L, win rate, average win, average loss, profit factor, expectancy

**Strategies page** (`/strategies`)

- Card per strategy showing: name, version, status (shadow/live/suspended/retired), days in current state, 30-day live Sharpe, 30-day backtest Sharpe (for comparison), live trade count, drift indicator (live vs backtest)
- Click any strategy for detail view
- Strategy detail: parameter values, equity curve attribution to this strategy, regime breakdown (which regimes it trades, performance per regime), recent trades, lifecycle history (state changes with timestamps and reasons)

**Models page** (`/models`)

- Table of all models in registry: name, version, status, trained at, training window, backtest Sharpe, backtest max DD, in-production date
- Click for details: full feature list, training metrics curves, hyperparameter values, code commit hash, comparison to incumbent
- Retraining queue: scheduled retrains, in-progress trains, recently completed

**Regime page** (`/regime`)

- Current regime per symbol with confidence
- Regime timeline (last 90 days): visual band showing regime classification over time, overlaid on price
- Regime statistics: time spent in each regime, average performance per regime, transition matrix

**Risk page** (`/risk`)

- Current exposure: per-symbol, per-strategy, total
- Distance to each circuit breaker shown as a horizontal gauge:
  - Daily loss: -1.2% / -3.0% (40% of way to trip)
  - Weekly loss: -2.8% / -8.0%
  - Total drawdown: -4.5% / -15.0%
  - Each gauge color-coded: green / amber / red
- Position concentration: pie chart by symbol
- Correlation matrix between current open positions

**Logs page** (`/logs`)

- Live tail of structured logs with filters by level, module, time range, free-text search
- Last 7 days searchable; older logs archived to compressed files

**Settings page** (`/settings`)

Read-only display of current configuration. Cannot edit live (config changes require redeploy — see Section 22). Useful for auditing what's running.

#### 19.3.4 API endpoints

The dashboard backend exposes a JSON REST API. Useful if you want to build custom integrations later.

| Endpoint | Returns |
|---|---|
| `GET /api/status` | System status, mode, uptime |
| `GET /api/equity?from=&to=` | Equity time series |
| `GET /api/positions` | Open positions |
| `GET /api/trades?filters` | Trade list |
| `GET /api/trades/{id}` | Trade details |
| `GET /api/strategies` | Strategy states |
| `GET /api/strategies/{name}` | Strategy details |
| `GET /api/models` | Model registry |
| `GET /api/regime?symbol=` | Current regime + history |
| `GET /api/risk` | Risk metrics |
| `WS /ws/live` | Real-time equity, position, signal stream |

All API calls log access. Authentication via the same Basic Auth + IP allowlist or Tailscale.

#### 19.3.5 Performance targets

- Page load under 1 second on 4G mobile
- Trade list pagination at 50 per page (no infinite scroll)
- Charts use canvas (Chart.js), not SVG, for performance with > 1000 data points
- API responses under 200ms p99
- WebSocket reconnects automatically on disconnect

#### 19.3.6 Mobile responsiveness

The dashboard must work on mobile screens. Critical for emergency access during travel. Specifically:

- Overview page must be fully readable and equity curve interactable on a 375px wide screen
- Tables collapse to card view on narrow screens
- All commands accessible via Telegram on mobile — dashboard is investigation-only on small screens

---

### 19.4 Operator workflow — how you actually use these

A typical week:

**Monday morning** — Check Telegram weekly review on phone. ~30 seconds. If anything flagged, open dashboard for details.

**During the week** — Telegram daily summaries arrive at 00:00 UTC. Glance at phone. ~10 seconds.

**Anytime warnings/errors arrive** — Read notification. If actionable, open dashboard link in notification for context. Decide whether to intervene or let bot handle it.

**Sunday afternoon** — 30-minute deep dive: open dashboard, review week's trades, check strategy drift, review any auto-suspended strategies, approve any pending strategy promotions.

**Travel/away** — Telegram remains primary. If `/flatten` or `/shutdown` needed, do it via Telegram. Dashboard via Tailscale if you need investigation.

**Emergency** — Always Telegram first (`/pause` or `/flatten`). Investigate via dashboard after the bot is in a safe state.

---

### 19.5 Failure modes and degraded operation

| Failure | Impact | Recovery |
|---|---|---|
| Telegram API down | No notifications, no commands | Bot continues trading. Dashboard still works. Notifications buffer for 1 hour. |
| Dashboard down | No web UI | Bot continues trading. Telegram still works. |
| Both down | No observability | Bot continues trading using internal logic. SSH access to the instance is the manual fallback. |
| Bot down, observability up | Cannot trade | Last-known state visible in dashboard. Telegram receives "bot offline" alert. |
| Network to instance down | All interfaces unreachable | Bot continues trading (internal logic) until exchange disconnect breaker trips. |

The system is designed to fail loud — anything that prevents safe operation triggers a halt before it triggers degraded trading.

---

## 20. Testing strategy

### 20.1 Test types

| Type | What | When run |
|---|---|---|
| Unit | Functions, classes in isolation | Every commit |
| Integration | Multi-module flows with stub broker | Every commit |
| Property | Hypothesis-generated risk scenarios | Every commit |
| Backtest | Strategies against historical data | Every PR + nightly |
| Smoke | Full system, paper mode, 1 hour | Every PR |
| Soak | Full system, paper mode, 7 days | Pre-deploy |

### 20.2 Required coverage

- Risk engine: 100% line coverage, property tests must pass
- Position sizer: 100% line coverage, property tests must pass
- Trade approver: 100% line coverage
- Broker adapter: 90% (some retry paths are hard to test)
- Models: 70% (mostly correctness of preprocessing, postprocessing)
- Strategies: 80%

### 20.3 Property tests for risk

Hypothesis must verify:

- For all valid signals × all valid portfolio states: position size ≤ hard cap
- For all valid market states: stop loss is always set
- For any sequence of P&L: cumulative drawdown calculation is correct
- For all valid signals: at most one trade per symbol per minute

---

## 21. Coding standards

### 21.1 Style

- `ruff` for formatting and linting (config in `pyproject.toml`)
- `mypy --strict` for type checking — no `Any`, no unchecked generics
- Docstrings on all public functions (Google style)
- Comments explain *why*, not *what*

### 21.2 Error handling

- Never use bare `except:`. Always specific exception types.
- Network failures → exponential backoff with jitter, max 5 retries
- Data errors → raise, log, halt trading
- Model errors → reject signal, log, continue
- Unrecoverable → graceful shutdown with state persisted

### 21.3 Logging

- All logs are structured JSON via structlog
- Every log entry has: timestamp, level, module, action, context
- No PII, no API secrets in logs ever
- Trade decisions log full context (signal, features, decision, reason)

### 21.4 Determinism

- All randomness goes through a seeded RNG, seed stored in run metadata
- Time always read via `common.time.now()` — never `datetime.now()` directly (so backtests can mock)
- Floating point comparisons use `math.isclose()` with explicit tolerance

### 21.5 No

- No global mutable state
- No `time.sleep()` outside of explicit retry logic
- No hardcoded paths — everything configurable
- No print statements — only structured logs
- No commented-out code in commits
- No TODOs without an issue number

---

## 22. Deployment

No containers. The system runs directly on the droplet, managed by systemd. This is simpler, lighter, and avoids the Docker failure surface entirely.

### 22.1 Stack components (as systemd services)

| Service | Unit | Description |
|---|---|---|
| TimescaleDB | `postgresql.service` | System PostgreSQL with TimescaleDB extension |
| Trading bot | `tradingbot.service` | Main bot process; restart-on-crash |
| Dashboard | `tradingbot-dashboard.service` | FastAPI dashboard, bound to Tailscale interface |
| Retraining | `tradingbot-retrain.timer` → `.service` | Scheduled model retraining (oneshot) |
| Backups | `tradingbot-backup.timer` → `.service` | Nightly pg_dump + artifacts to DigitalOcean Spaces |
| Tailscale | `tailscaled.service` | Private network for dashboard access |

Prometheus and Grafana, if used, also run as native systemd services (or are deferred to a lightweight alternative — the dashboard already provides core metrics).

systemd provides: automatic restart on crash (`Restart=on-failure`), start-on-boot (`WantedBy=multi-user.target`), and centralized logging to journald (queryable via `journalctl -u tradingbot`).

### 22.2 One-time server bootstrap

Run `deploy/setup_server.sh` on a fresh DigitalOcean Ubuntu 24.04 droplet. It:

1. Updates the system and installs Python 3.11+, build tools, and `git`
2. Installs PostgreSQL + TimescaleDB extension, creates the database and user
3. Installs Tailscale and brings the instance onto the tailnet
4. Creates a dedicated non-root `tradingbot` system user to run the services
5. Clones the repo into `/opt/tradingbot`, creates the virtual environment, installs dependencies
6. Configures the DigitalOcean firewall (no inbound ports except SSH; dashboard reachable via Tailscale only)
7. Installs systemd units via `deploy/install_services.sh`

### 22.3 Environment

Production env file (`.env`) lives only on the instance at `/opt/tradingbot/.env`, never in git. Owned by the `tradingbot` user, permissions `600`. Contains all secrets. systemd units load it via `EnvironmentFile=`.

### 22.4 Deploy / update procedure

1. Run full test suite locally (or over SSH on the instance): `make test`
2. Push to main (CI must pass)
3. SSH to the instance
4. **Manual stop check:** is the bot in a safe state? Any open positions? Acknowledge before proceeding.
5. Run `deploy/update.sh`, which:
   - `git pull` the latest code
   - Activates the venv and `pip install -e .` for any new dependencies
   - Runs any database migrations
   - `systemctl restart tradingbot tradingbot-dashboard`
6. Verify dashboard reachable over Tailscale
7. `journalctl -u tradingbot -f` for 5 minutes, check for errors

### 22.5 Rollback

State lives in the database, not in the code, so rolling back code is safe:

1. `git checkout <previous-tag>`
2. `pip install -e .` (in case dependencies changed)
3. `systemctl restart tradingbot tradingbot-dashboard`

### 22.6 Backups

- **Database:** nightly `pg_dump` (via `tradingbot-backup.timer`), encrypted, uploaded to **DigitalOcean Spaces**, 30-day retention
- **Models:** every trained model artifact archived to DigitalOcean Spaces
- **Config:** in git
- **Code:** in git
- **Optional second copy:** the operator can periodically pull the latest backup to a local machine for off-site safety

Restoring is documented in `docs/runbook.md`: provision a fresh droplet, run `setup_server.sh`, restore the latest `pg_dump`, redeploy code, restart services.

### 22.7 Droplet sizing and scaling

The Basic Droplet at 2 vCPU / 4 GB RAM / 80 GB SSD is right-sized for v1's compute needs: model training, TimescaleDB, dashboard, and the bot running concurrently.

**When to consider upgrading:**

- Model retraining exceeds ~30 minutes on the 4 GB droplet
- The universe expands beyond 2 symbols (Phase 2 in Section 5)
- Multiple strategies training in parallel become a bottleneck
- Data volume grows past ~30 GB (well beyond v1 expectations)

DigitalOcean allows in-place droplet resizing with minutes of downtime. The upgrade path from Basic to the 4 vCPU / 8 GB tier (~$48/month) is a single control-panel action followed by a droplet reboot. State on the droplet's block storage is preserved.

**Region selection.** Singapore is the recommended region for lowest latency to Bybit's matching engine (~30ms round-trip). Other regions work but add latency: Tokyo ~50ms, London ~200ms, US East ~250ms+. For a non-HFT bot, up to ~100ms is fine; beyond that, slippage models may drift.

**Bandwidth.** The 4 TB monthly outbound allowance in the Basic Droplet is orders of magnitude more than the bot will use. Realistic v1 outbound is under 50 GB/month (dashboard access, DB backups to Spaces, log exports).

---

## 23. Operational procedures

### 23.1 Startup checklist (manual restart after shutdown)

1. Verify exchange API keys still valid
2. Check exchange status page
3. Verify clock sync (`chronyc tracking`)
4. Verify database is up and reachable
5. Run health check: `make healthcheck` (validates feeds, models, broker connection)
6. Start in paper mode for 1 hour, observe
7. Switch to live mode

### 23.2 Daily operator review (5 min)

Even though autonomous, check daily:

- Telegram daily summary received?
- Equity within expected range?
- Any open warnings?
- Any strategy auto-suspended?

### 23.3 Weekly review (30 min)

- Review weekly performance report
- Compare live vs backtest performance
- Review any circuit breaker events
- Approve/reject auto-promoted strategies (if any)

### 23.4 Incident response

If something goes wrong:

1. Issue `/pause` via Telegram
2. Investigate via dashboard + logs
3. If unsafe: `/flatten` to close positions
4. If broken: `/shutdown` and debug
5. Document incident in `docs/incidents/YYYY-MM-DD.md`
6. Post-mortem before resuming

---

## 24. Glossary

- **ATR** — Average True Range, a volatility measure
- **Backtest** — simulation of a strategy on historical data
- **Drawdown** — peak-to-trough decline in equity, typically expressed as percentage
- **HMM** — Hidden Markov Model, used for regime detection
- **Hit rate** — fraction of trades that are profitable
- **Kelly criterion** — formula for optimal position sizing given edge and odds
- **Limit order** — order to buy/sell at a specified price or better
- **Market order** — order to buy/sell immediately at the best available price
- **OHLCV** — Open, High, Low, Close, Volume — the standard candle data format
- **Profit factor** — gross profits / gross losses
- **Regime** — a classification of current market behavior (trending, ranging, etc.)
- **Reinforcement learning (RL)** — ML where an agent learns by interacting with an environment and receiving rewards
- **Sharpe ratio** — risk-adjusted return: (return - risk-free) / std deviation of returns
- **Shadow mode** — strategy runs but does not place real trades
- **Slippage** — difference between expected execution price and actual execution price
- **Sortino ratio** — like Sharpe but only penalizes downside volatility
- **Stop loss** — order that closes a position when price reaches a specified level, limiting loss
- **Walk-forward** — model validation where training window rolls forward through time, never using future data

---

## 25. Open questions and future work

These are deferred from v1 but should be considered. Each has explicit conditions for when it becomes reasonable to revisit.

### 25.1 Leverage and derivatives

**Status in v1: explicitly forbidden.** See Section 4.1 (Hard Constraints) and Section 16.4.4 (spot-only enforcement).

**Conditions for revisiting:**
- Minimum 12 months of live operation with sustained Sharpe > 1.5
- Maximum drawdown observed < 15% across all 12 months
- At least 500 closed trades providing statistical significance
- Live performance matched backtest within tolerance for at least 6 months
- Multiple regimes successfully traded

**If reintroduced, conditions on use:**
- Modest leverage only (≤ 2×, never 5-10×)
- Per-strategy authorization (not blanket account-level leverage)
- New HARD CONSTRAINTS for funding fee handling, liquidation buffers, position size caps
- Funding fees factored into cost-vs-edge check
- Continued 1.0× leverage on at least 50% of capital as the safe baseline

The slow growth of unleveraged trading is the price of survival during the learning phase. Leverage is a capital efficiency tool for proven systems, not a growth tool for unproven ones.

### 25.2 News and sentiment pipeline

**Status in v1: deferred.** See Sections 8.5 and 15.1 for reasoning.

**Conditions for revisiting:**
- Phase 7's feature importance analyzer indicates current features explain < 70% of model variance, suggesting missing context
- v1 system has been profitable for 90+ days, meaning we have budget for engineering effort that may not pay off
- A specific market event occurs that the bot demonstrably mishandles in a way news-awareness would have prevented (rare but possible — e.g., a major exchange hack)

**If implemented, scope:**
- Batch processing only (every 5-15 minutes, never per-trade)
- Sentiment as a feature among many, never as standalone signal
- Source diversity required (multiple news APIs, not single source)
- Ablation study to prove additive value before deployment

### 25.3 On-chain analytics

**Status in v1: deferred.** Most promising of the v2 candidates.

**Conditions for revisiting:**
- v1 system profitable
- Capital ≥ $5,000 (so $30-100/month subscription is reasonable cost)
- Specific on-chain features identified that have published academic predictive power for our timeframes

**Specific data sources to evaluate:**
- Glassnode (~$30-300/month)
- CryptoQuant (~$30/month for basic tier)
- Free Bybit and exchange-published flow data (no cost, lower quality)

**Specific features of interest:**
- Exchange net inflows/outflows (1-hour to 1-day signal)
- Stablecoin supply changes (precedes buying pressure)
- Miner reserve changes (correlates with local tops)
- Long-term holder behavior (cycle position indicator)

### 25.4 Multi-exchange execution

**Status in v1: deferred.** Bybit only.

**Reasons to expand:**
- Best execution on tight spreads (cross-exchange arbitrage opportunities)
- Counterparty risk diversification
- Access to assets not listed on Bybit

**Conditions for revisiting:**
- Capital ≥ $25,000 (operational complexity becomes worthwhile)
- v1 stable for 12+ months
- Specific arbitrage strategy validated in backtest

### 25.5 Universe expansion

**Status in v1: BTC and ETH only.** See Section 5.2 for the staged expansion plan.

**Phase 1 → Phase 2 expansion criteria** (after 90 days of stable operation):
- Top-10 by market cap
- Daily volume ≥ $1B average over 30 days
- Listed on Bybit spot for ≥ 1 year
- No active exchange warning labels

### 25.6 Distributed training

**Status in v1: single-node.** Single instance handles training comfortably for v1 model sizes.

**Conditions for revisiting:**
- Training time exceeds 6 hours (becomes operational bottleneck)
- Model architectures grow beyond what 4GB RAM can handle
- Multi-asset universe demands per-symbol model training in parallel

### 25.7 A/B testing framework

**Status in v1: implicit via shadow mode.** New strategies run in shadow before promotion.

**Conditions for explicit framework:**
- 5+ live strategies running simultaneously
- Need to compare strategy variants with controlled capital allocation
- v1 stable enough that experimentation is the bottleneck, not stability

### 25.8 Adversarial and stress testing

**Status in v1: implicit via property tests and circuit breakers.**

**Future enhancements:**
- Deliberately injecting flash crash data into backtests
- Testing against historical manipulation patterns (May 2021 crypto flash crash, March 2020 COVID crash)
- Latency injection testing (what happens when broker API responds slowly?)
- API failure mode testing (Bybit returns garbage data)

### 25.9 Operator briefing

**Status in v1: not implemented.** See Section 8.6.

A simple offline batch job that generates a daily Telegram message summarizing overnight market action and upcoming calendar events for the operator (you) to read. Not consumed by the bot. Helps keep the human's mental model aligned with what the bot is doing.

Could be implemented in 1-2 days using Claude API for summarization. Not a priority but a low-effort, high-value addition once v1 is running.

---

## 26. Document changelog

| Version | Date | Changes |
|---|---|---|
| 1.0 | Initial | Initial specification |
| 1.1 | Revision | Added Section 7 (AI and external service dependencies) clarifying no LLM API in trade hot path. Expanded former Section 16 into new comprehensive Section 17 (Operator interface — Telegram and dashboard) covering setup, authorization, notification levels, command reference, message formatting, dashboard architecture, all pages, API endpoints, mobile responsiveness, operator workflows, and degraded operation. Renumbered subsequent sections. |
| 1.2 | Revision | Added Section 7 (Costs and economics) with full breakdown of fixed costs, Bybit fees, and corrected capital scaling analysis. Added Section 18 (End-to-end trade decision walkthrough) with concrete 12-stage trade narrative. Expanded Section 15 (ML pipeline) feature engineering to include cross-asset regime features (VIX, DXY, S&P, gold) and calendar event features as v1 inclusions, with explicit "not in v1" deferrals for news/sentiment, Twitter, on-chain. Updated Section 8 (AI deps) to defer News API entirely; news rationale now lives in 8.5. Significantly expanded Section 16 (Execution layer) with instrument precision rules (basePrecision, tickSize, qtyStep, rounding behavior), broker minimum order requirements, Bybit rejection code handling, overnight fee policy (spot-only HARD CONSTRAINT, no funding fees), and capital scaling guidance. Expanded Section 25 (Open questions) with explicit conditions for each v2 candidate including leverage policy, news/sentiment, on-chain analytics, multi-exchange, universe expansion, and operator briefing. Renumbered subsequent sections accordingly. |
| 1.3 | Revision | Removed Docker entirely. System now runs directly on host via Python venv + systemd services. Migrated hosting from DigitalOcean ($30/month) to Oracle Cloud Infrastructure Always Free tier ($0/month) — ARM Ampere A1, up to 4 cores / 24 GB RAM, no expiry, no sleep. Rewrote Section 6.3 (Infrastructure) for OCI + systemd, added Section 6.4 (Local development without Docker) covering VS Code Remote-SSH and local venv workflows. Updated all of Section 7 (Costs) to reflect $0 fixed hosting cost; required gross monthly return at $1k drops from ~13% to ~10%. Replaced Caddy reverse proxy with Tailscale-first dashboard access (no public exposure, no TLS setup); optional nginx + domain path documented for public access. Rewrote Section 22 (Deployment) for systemd units, OCI bootstrap scripts, DigitalOcean Spaces backups, and host migration guidance for the live-money phase. Updated repository structure: removed docker-compose.yml and Dockerfile, added deploy/ directory with setup_server.sh, install_services.sh, update.sh, and systemd units; added execution/instrument_rules.py and data/ingestion/crossasset.py. Updated secrets block (removed NEWS_API_KEY, added OCI backup keys and Telegram auth vars). Added DigitalOcean as an explicit optional paid fallback for live trading reliability (Phase 9 judgment call). Renumbered backtester subsection to 6.5. |
| 1.4 | Revision | Reverted hosting from Oracle Cloud back to DigitalOcean based on operator's poor experience with OCI Free Tier. Restored $24/month DigitalOcean droplet (Singapore) + $5/month DigitalOcean Spaces backup. Kept the v1.3 Docker removal — system still runs directly on host via Python venv + systemd. Rewrote Section 6.3 with DigitalOcean specifics and justification for paid hosting over free tiers. Added Section 6.4 covering three local development workflows for Windows 10: WSL2 (recommended), VS Code Remote-SSH on the droplet, and native Windows (not recommended). Restored cost structure in Section 7 to $29/month fixed; required gross monthly return at $1k back to ~13%. Added Section 0.1 (Environment ground rules) at the top of the document to give Claude Code explicit instructions: no Docker, no OCI/AWS/GCP/Azure, DigitalOcean only, Windows 10 host with WSL2, Bybit only. Added Section 5.4 (Broker portability) explicitly documenting which brokers are compatible now (Bybit spot), compatible with modest work (other crypto spot exchanges), incompatible without spec changes (equities, forex, futures), and explicitly incompatible (prop firms — with detailed reasoning). Updated all secret var names, deployment scripts, and repo comments from OCI back to DigitalOcean. Updated Phase 0 DoD to reference WSL2 setup explicitly. |
| 1.5 | Revision | Switched local development environment from Windows 10 + WSL2 to a native Ubuntu Linux workstation. WSL2 caused system crashes; the operator now has Ubuntu installed on a dedicated development machine. Rewrote Section 0.1 (Environment ground rules) to reflect Ubuntu everywhere — local dev and droplet both run Ubuntu, giving real dev-prod parity. Rewrote Section 6.4 as "Local development on Ubuntu" with concrete `apt install` commands, TimescaleDB extension setup, database creation, venv workflow, and an environment parity checklist covering Python version, PostgreSQL version, and NTP. Removed all WSL2, Windows Terminal, and Windows-native Python content. Updated Phase 0 to reference `docs/dev-setup-ubuntu.md` and to require `make test` passing on the local Ubuntu machine as the Definition of Done. Kept Remote-SSH to the droplet as an optional secondary workflow. |

---

**End of specification.** Any code or design decision not covered here should be raised as a question before implementation, and this document should be updated to reflect the resolution.
