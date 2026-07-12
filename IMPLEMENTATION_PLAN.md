# Implementation Plan — Autonomous Self-Learning Trading Bot

**Companion to:** [CLAUDE.md](CLAUDE.md) v1.5 (the specification — always the source of truth)
**Created:** 2026-07-12
**Current state:** Phase 0 complete (local DoD met). Phase 1 — gate open.

---

## How this document works

Phases and Definitions of Done come from spec §10 and are built strictly in order. Every phase has three parts:

1. **Claude builds** — the code and artifacts Claude implements.
2. **YOU (operator) must do** — tasks Claude *cannot* do: accounts, KYC, money, sudo installs, phone-based setup, judgment calls. These are the gate.
3. **Definition of Done** — the spec's exit criteria, demonstrated with test output or run logs before the phase is closed.

### Gate protocol

1. **Before starting phase N**, Claude presents that phase's "YOU must do" checklist and asks for explicit confirmation.
2. Claude then **independently verifies** whatever it can from the machine (e.g. `psql` connects, `python3.11 --version` works, `.env` contains the required keys — checked by key *name* only, values never printed).
3. Implementation proceeds only after confirmation **and** verification. If verification contradicts the confirmation, Claude reports the discrepancy and waits.
4. Phase N is closed only when its Definition of Done is met and demonstrated. Status is recorded in this file.
5. **Live-money actions are never taken on standing approval** — the Phase 6 go-live and every Phase 9 capital increase require a fresh, explicit "go" from the operator.

### Status legend

⬜ Not started · 🔶 Gate open (checklist presented, awaiting operator) · 🔨 In progress (gate passed) · ✅ Done (DoD demonstrated)

## Progress tracker

| Phase | Status | Gate confirmed | DoD met |
|---|---|---|---|
| 0 — Project foundation | ✅ Done | 2026-07-12 | 2026-07-12 (local `make test`) |
| 1 — Data pipeline | 🔶 Gate open | — | — |
| 2 — Risk engine & sizing | ⬜ | — | — |
| 3 — Backtesting engine | ⬜ | — | — |
| 4 — Strategies & models | ⬜ | — | — |
| 5 — Paper trading | ⬜ | — | — |
| 6 — Live execution ($100) | ⬜ | — | — |
| 7 — Learning loop | ⬜ | — | — |
| 8 — Monitoring & ops | ⬜ | — | — |
| 9 — Full deployment & ramp | ⬜ | — | — |

## Environment audit (2026-07-12, operator's Ubuntu workstation)

Re-verified at each gate; this snapshot drove the Phase 0 checklist.

| Item | Status | Consequence |
|---|---|---|
| Project dir | Only `CLAUDE.md`, not a git repo | Claude runs `git init` in Phase 0 |
| Python | 3.12.3 only; **no 3.11** | Spec pins 3.11 → install via deadsnakes PPA (Phase 0) |
| PostgreSQL | **Not installed**, service inactive | Install PG16 + TimescaleDB (Phase 0) |
| ta-lib C library | **Not installed** | Needed before `pip install TA-Lib` → Phase 0 step |
| git | 2.43.0 ✓ | OK |
| gh CLI | **Not installed / not authed** | Needed for GitHub repo + CI activation (Phase 0) |
| Disk | 30 GB free | Sufficient for 5y of 1m data (2 symbols) |

---

## Phase 0 — Project foundation (est. 1–2 days)

**Status:** ✅ Done (2026-07-12)
**Gate record:** Operator installed Python 3.11, PostgreSQL 16 + TimescaleDB, ta-lib, and `gh` — all verified from the machine. DoD met: fresh clone from GitHub → `make install` → `make test` = **24 passed**; `mypy --strict` and `ruff` clean; bot runs in paper mode emitting structured JSON logs. Committed and pushed to github.com/yomite/trade.

> **CI note (resolved 2026-07-12):** CI is **green** — all steps pass (checkout, Python 3.11, install, ruff, mypy --strict, tests). The earlier failures were an account-level GitHub billing lock ("The job was not started because your account is locked due to a billing issue"), confirmed via the run's check-run annotation and ruled in after eliminating the workflow file (valid), repo visibility (made public), and email (verified). The operator updated billing and CI now runs on every push. Repo is public; a Netlify app is also installed (unrelated to CI).

**Claude builds:** full repo tree per §9; `git init` + initial commit; `pyproject.toml` (all §6.2 deps, ruff + mypy --strict config, Python pinned 3.11); `src/constants.py` encoding every §4 HARD CONSTRAINT; `config/{base,paper,live,backtest}.yaml` per §12; `.env.example` documenting every env var; `Makefile` (install/test/lint/run-paper/backtest); pre-commit hooks; GitHub Actions CI (venv-based, no containers); `README.md`; `docs/dev-setup-ubuntu.md`.

**YOU must do (Claude confirms before starting):**
- [x] **Install system packages** (sudo — exact commands in Appendix A; run them yourself or have Claude run them if passwordless sudo is available):
  - Python 3.11 + venv + dev headers via deadsnakes PPA (Ubuntu 24.04 ships 3.12; spec §6.4.4 pins 3.11)
  - `build-essential`, `git`, `curl`
  - PostgreSQL 16 + `postgresql-server-dev-16`, then the TimescaleDB apt repo + extension (§6.4.1)
  - ta-lib C library (required before the `TA-Lib` Python package will install)
- [x] **Create the dev database** (needs postgres superuser): role `tradingbot`, database `tradingbot_dev`, `CREATE EXTENSION timescaledb` — done (role verified from the machine).
- [x] **GitHub**: repo `yomite/trade` exists, `gh` authed as `yomite`, Phase 0 pushed. CI *activation* still pending — see CI note above (private-repo Actions billing).
- [x] **Confirm machine availability**: operator confirmed the workstation can stay on for the 24 h (Phase 1) and 7-day (Phase 5) soak tests.

**Definition of Done (spec):** `make test` passes on a fresh clone after `make install` on this machine.

---

## Phase 1 — Data pipeline (est. 3–5 days)

**Status:** 🔨 In progress (gate passed 2026-07-12)
**Gate record:** Operator set `DATABASE_URL` in `.env`. Verified from the machine (secret never printed): connected to `tradingbot_dev` as `tradingbot`, PostgreSQL 16.14, TimescaleDB extension **2.28.2** present. Bybit reachable via `api.bytick.com` (see below). Cleared to implement.

**Progress (2026-07-12):**
- ✅ Schema (`schema.sql`) applied; storage writers (`timescale.py`) integration-tested (Decimal-exact, idempotent, dedup).
- ✅ REST loader (`bybit_rest.py`) with `bytick` host fallback + resumable deep/recent backfill (`backfill.py`); live-verified.
- ✅ WS feed (`bybit_ws.py`): confirmed 1m bars + trades + order book; 80s live capture wrote 182 trades / 75 books / closed bars.
- ✅ Validation (`validation.py`) + deterministic feature transforms (`features/*`, versioned `v1`, 31 features); determinism + correctness unit-tested. 51 tests green, mypy/ruff clean.
- ✅ Cross-asset (`crossasset.py`, yfinance) + macro stub (`macro.py`).
- ✅ **Historical backfill complete**: BTC/USDT + ETH/USDT, **2,628,000 bars each (5,256,000 total)**, 2021-07-13 → 2026-07-12, **0.0000% gap rate** (DoD <0.1% PASS). Bybit spot lists both from 2021-07, so this is the full available history.
- ✅ **Full-history features materialized**: 5,256,000 rows (2.628M/symbol), 31 features each, feature_set `v1`, 2021-07→2026-07. Features hypertable 6.2 GB, bars 1.2 GB.
- ⏳ **Pending — operator/long-running:** 24h live-feed soak (`make live-feed`, or `nohup systemd-inhibit … run_live_feed.py`) to confirm no missed candles. Run when convenient; leave the machine on. Can also run later on the droplet.

**DoD status:** feature-determinism ✅; 5y-load ✅ (0.0000% gaps); features stored ✅ (5.26M rows); **24h-soak ⏳ pending operator — the only item left to close Phase 1.**

**Phase 2 is NOT started** (operator asked to hold). Its gate = operator sign-off on freezing the §4 hard-constraint values into `constants.py`.

**Claude builds:** `schema.sql` (§11) + `timescale.py` writers; `bybit_rest.py` backfill of 5 years of 1m candles for BTC/USDT + ETH/USDT; `bybit_ws.py` live trades/candles/order book; `validation.py` (gaps, late data, duplicates); deterministic feature transforms (`features/*` per §15.1 incl. cross-asset via yfinance, macro stubbed); `scripts/load_history.py`.

**YOU must do:**
- [x] **Bybit reachability confirmed** — `api.bybit.com` is DNS-blocked on this network, but Bybit's official mirror `api.bytick.com` responds (HTTP 200, valid data). The Phase 1 data layer must use the `bytick.com` REST + WS endpoints on this machine (both `ccxt` and `pybit` allow overriding the base host). No operator action needed.
- [ ] **Start Bybit account creation + KYC now** — approval can take days and Phase 6 needs a fully verified account. Testnet API keys are enough until Phase 5.
- [ ] **Create `.env` from `.env.example`** and fill `DATABASE_URL` yourself (secrets are yours to type; Claude never needs to see values, only that keys exist).
- [ ] **Leave the machine running 24 h** for the live-feed DoD test.

**DoD (spec):** 5 years of 1m history at < 0.1% gap rate; 24 h live feed with no missed candles; feature determinism unit-tested.

---

## Phase 2 — Risk engine & position sizing (est. 2–3 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** `risk_engine.py` (every §4 check), `position_sizer.py` (1% risk, Kelly cap 0.25, vol scaling, broker-minimum rejection §16.3.3), `portfolio_manager.py`, `trade_approver.py` (single gate, cost-vs-edge ≥ 1.2×), Hypothesis property suites (10,000 scenarios), 100% coverage on all four modules.

**YOU must do:**
- [ ] **Final review of the §4 constraint values** (1% risk/trade, 25% max position, 3 concurrent, 3%/8%/15% breakers, etc.). These get frozen into `constants.py`; changing them later means editing the spec + committing with justification. This is a judgment call only you can make.

**DoD (spec):** 100% risk-engine coverage; 10k Hypothesis scenarios pass; every §4 constraint has a test that fails when the constraint is violated.

---

## Phase 3 — Backtesting engine (est. 4–6 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** event-driven `backtest/engine.py` **sharing the live risk/sizing/approval code paths** (§13.1); `slippage.py` (order size / volatility / book depth dependent); Bybit fee model; `walk_forward.py`; `reports.py` (HTML + JSON: equity, drawdown, trades, regime overlay, Monte Carlo).

**YOU must do:**
- [ ] Nothing external — the gate here re-verifies Phase 1 data is loaded and Phase 2 tests pass.
- [ ] Optional: sanity-check the buy-and-hold 2020–2024 benchmark report against your own market knowledge.

**DoD (spec):** BTC buy-and-hold 2020–2024 within 2% of actual market performance; SMA-crossover walk-forward runs end-to-end.

---

## Phase 4 — First strategies & models (est. 5–7 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** `strategies/` (Donchian trend, Bollinger mean-reversion, volatility breakout, base ABC + registry, lifecycle §14.2); `models/` (XGBoost, LSTM, ensemble, registry §15.2); HMM regime detector; `selector.py`.

**YOU must do:**
- [ ] **Accept CPU training times on this machine** — Claude reports actual LSTM/XGB training durations after first runs; if unacceptable, the decision to provision the droplet early (billing) is yours.

**DoD (spec):** each strategy OOS Sharpe > 0.5; ensemble beats any individual model on validation; regime detector ≥ 70% accuracy on labeled trending/ranging periods.

---

## Phase 5 — Paper trading (est. 3–5 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** `broker.py` abstraction; `paper_adapter.py` (next-bar fills + slippage model); `fill_tracker.py`, `pnl_tracker.py`; trade journal wiring (every decision logged, incl. rejections); full loop live data → features → models → risk → simulated execution; `make run-paper`.

**YOU must do:**
- [ ] **Create the Telegram bot via @BotFather** (§19.2.1 — only you can do this from your Telegram account): `/newbot` → token into `.env` as `TELEGRAM_BOT_TOKEN`; message the bot once; extract your chat id → `TELEGRAM_CHAT_ID` + `TELEGRAM_AUTHORIZED_CHAT_IDS`; `/setcommands`. Spec requires this before Phase 6; doing it now lets paper mode exercise alerts.
- [ ] **Bybit testnet API keys** into `.env`.
- [ ] **Keep the machine running 7 consecutive days** for the paper soak — or opt to provision the droplet now and run the soak there (then also complete the Phase 6 droplet items early).

**DoD (spec):** 7 days paper without crashing; journal captures every decision with full context; P&L matches manual recalculation from logs.

---

## Phase 6 — Live execution, $100 (est. 3–5 days + 14-day validation)

**Status:** ⬜
**Gate record:** —

**Claude builds:** `bybit_adapter.py` (orders, native TP/SL, idempotent `orderLinkId` §16.6); `instrument_rules.py` (fetch/refresh/round/validate §16.3, rejection-code handling §16.3.4); 60 s reconciliation (§16.5); `deploy/setup_server.sh`, `install_services.sh`, `update.sh`, all systemd units (§22); `scripts/healthcheck.py`.

**YOU must do (the heaviest operator phase — all of it is yours):**
- [ ] **DigitalOcean**: create account + billing; create droplet — Basic 2 vCPU / 4 GB / 80 GB, **Singapore**, Ubuntu 24.04 (~$24/mo); add your SSH key.
- [ ] **DO Spaces** bucket + access keys for backups (~$5/mo) → droplet `.env`.
- [ ] **Tailscale**: create account; install on your laptop + phone; approve the droplet onto your tailnet when the bootstrap script runs.
- [ ] **Run `deploy/setup_server.sh` on the droplet** — yourself over SSH, or grant Claude SSH access from this machine and approve its commands.
- [ ] **Bybit**: KYC complete; deposit **$100 USDT** to spot; create a **live API key with trade-only permission (NO withdraw — spec HARD CONSTRAINT), IP-restricted to the droplet**; put it in the droplet's `/opt/tradingbot/.env` yourself (never paste secrets into chat).
- [ ] **Explicit go-live authorization** — Claude will ask "start live trading with $100?" and will not proceed on anything less than a direct yes.
- [ ] **Stay reachable on Telegram** during the 14-day validation window.

**DoD (spec):** 14 consecutive live days at $100; reconciliation never disagrees with the exchange; zero circuit-breaker trips; real slippage within 50% of model.

---

## Phase 7 — Learning loop (est. 5–7 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** `performance.py` (Sharpe/Sortino/Calmar per strategy/regime/window §17.1); `retrainer.py` (walk-forward, shadow-then-promote §15.3); `evolver.py` (weekly Bayesian optimization, kill-switch §14.3); `journal.py`; `memory.py` (regime → outcome store); retrain systemd timer.

**YOU must do:**
- [ ] **Confirm retrain cadence & droplet load** — Claude reports retrain durations; if > 30 min, the §22.7 upgrade to the $48/mo tier is your billing decision.

**DoD (spec):** retraining runs end-to-end unattended; a deliberately degraded strategy is auto-suspended; new models deploy only when beating the incumbent in walk-forward.

---

## Phase 8 — Monitoring & operations (est. 3–4 days)

**Status:** ⬜
**Gate record:** —

**Claude builds:** FastAPI dashboard bound to Tailscale (all §19.3.4 pages + REST/WS API); Telegram notification levels + full command set incl. confirmations (§19.2); Prometheus metrics; `scripts/backup.py` + nightly timer → DO Spaces; `docs/runbook.md`.

**YOU must do:**
- [ ] **Verify dashboard reachable from your laptop AND phone** over Tailscale (only you hold those devices).
- [ ] **Confirm test alerts arrive** — Claude triggers one per level; you confirm receipt on your phone.
- [ ] Optional but recommended for live: **enable TOTP** for `/flatten` & `/shutdown` (add `TELEGRAM_TOTP_SECRET` to your authenticator app).
- [ ] **Participate in the cold-restart runbook test** (~30 min: stop bot, recover per runbook).

**DoD (spec, adapted):** dashboard accessible over Tailscale (encrypted transport per §19.3.2 — spec's "HTTPS" line predates the Tailscale-first design); Telegram alerts fire for every breaker type; recovery runbook tested from cold.

---

## Phase 9 — Full live deployment & capital ramp (ongoing)

**Status:** ⬜
**Gate record:** —

**Claude does:** weekly automated Telegram review reports; monthly live-vs-backtest drift analysis; ongoing retraining oversight and fixes.

**YOU must do (this phase is mostly yours):**
- [ ] **Fund each ramp step** $100 → $250 → $500 → $1,000 over ≥ 30 days — every increase is a fresh explicit "go", gated on the previous step being clean.
- [ ] **Daily 5-min check** (§23.2) and **Sunday 30-min review** (§23.3); approve/reject strategy promotions.
- [ ] **Manual restarts** after weekly-loss or total-drawdown breakers — required by design, never automated.
- [ ] **Accept the economics**: at $1k, ~13% gross monthly is break-even (§7.6). This phase validates the system; it is not a profit phase.

**DoD:** ongoing; after 90 stable days, universe expansion per §5.2 becomes discussable.

---

## Cross-cutting rules (all phases)

- Secrets live only in `.env` (mode 600), typed by the operator, never in chat, git, or logs.
- `CLAUDE.md` is the source of truth; any deviation discovered during implementation is raised first and written back into the spec (§0).
- Safety code (breakers, risk gates, slippage guards) is never disabled without explicit operator approval (§0.5).
- Explicit failure over silent recovery, everywhere (§0.6).
- No Docker, no clouds other than DigitalOcean, Bybit spot only (§0.1).

## Realistic calendar

~30–44 working days of build effort (spec estimates) **plus** mandated elapsed time: 24 h Phase 1 soak, 7-day Phase 5 soak, 14-day Phase 6 live validation, ≥ 30-day Phase 9 ramp → roughly **3–4 months** to a fully autonomous $1,000 deployment, before the 90-day validation period begins.

---

## Appendix A — Phase 0 local setup commands (Ubuntu 24.04)

These will also be enshrined in `docs/dev-setup-ubuntu.md` during Phase 0. Run in order.

```bash
# 1. Python 3.11 (24.04 ships 3.12; spec pins 3.11 → deadsnakes PPA)
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
                    build-essential git curl

# 2. PostgreSQL 16 (default on 24.04) + dev headers
sudo apt install -y postgresql-16 postgresql-client-16 postgresql-server-dev-16

# 3. TimescaleDB extension (official packagecloud repo)
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" \
  | sudo tee /etc/apt/sources.list.d/timescaledb.list
wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey \
  | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
sudo apt update
sudo apt install -y timescaledb-2-postgresql-16
sudo timescaledb-tune --quiet --yes        # sets shared_preload_libraries
sudo systemctl restart postgresql

# 4. ta-lib C library (official .deb from ta-lib releases; needed by pip TA-Lib)
wget -O /tmp/ta-lib.deb \
  https://github.com/ta-lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_amd64.deb
sudo dpkg -i /tmp/ta-lib.deb || sudo apt-get install -f -y
# (fallback if the .deb ever disappears: build from source per ta-lib.org)

# 5. Dev database — pick your own password at the prompt
sudo -u postgres createuser -P tradingbot
sudo -u postgres createdb -O tradingbot tradingbot_dev
sudo -u postgres psql -d tradingbot_dev -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

# 6. (Optional, for CI activation) GitHub CLI
sudo apt install -y gh
gh auth login
```
