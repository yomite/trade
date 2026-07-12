# Local development setup — Ubuntu

The operator's workstation is native Ubuntu (Section 6.4). These steps mirror
the DigitalOcean droplet so code that works locally works in production. **No
Docker, no WSL** (Section 0.1).

Tested on Ubuntu 24.04. Run the blocks in order.

## 1. System packages

Ubuntu 24.04 ships Python 3.12; the project pins **3.11** for dev-prod parity
(Section 6.4.4), installed from the deadsnakes PPA.

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
                    build-essential git curl
```

## 2. PostgreSQL 16 + TimescaleDB

```bash
sudo apt install -y postgresql-16 postgresql-client-16 postgresql-server-dev-16

# TimescaleDB apt repo + extension
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" \
  | sudo tee /etc/apt/sources.list.d/timescaledb.list
wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey \
  | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
sudo apt update
sudo apt install -y timescaledb-2-postgresql-16
sudo timescaledb-tune --quiet --yes    # sets shared_preload_libraries
sudo systemctl restart postgresql
```

## 3. ta-lib C library

Required before the Python `TA-Lib` wheel (installed with `make install-all`)
will build.

```bash
wget -O /tmp/ta-lib.deb \
  https://github.com/ta-lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_amd64.deb
sudo dpkg -i /tmp/ta-lib.deb || sudo apt-get install -f -y
```

If the `.deb` is ever unavailable, build from source per <https://ta-lib.org>.

## 4. Development database

Pick your own password for the `tradingbot` role at the prompt; put the same
password into `DATABASE_URL` in `.env` (step 6).

```bash
sudo -u postgres createuser -P tradingbot
sudo -u postgres createdb -O tradingbot tradingbot_dev
sudo -u postgres psql -d tradingbot_dev -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

Verify:

```bash
psql "postgresql://tradingbot:YOUR_PASSWORD@localhost:5432/tradingbot_dev" \
  -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
```

## 5. Clone + virtual environment

```bash
git clone https://github.com/yomite/trade.git ~/tradingbot
cd ~/tradingbot
make install        # creates .venv with Python 3.11 and installs core + dev deps
```

## 6. Configure `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` and set at least:

```
DATABASE_URL=postgresql://tradingbot:YOUR_PASSWORD@localhost:5432/tradingbot_dev
```

Bybit **testnet** keys and Telegram credentials are added when their phases
arrive (Phase 5); they are not needed for Phase 0.

## 7. Run the tests

```bash
make test
```

This is the Phase 0 Definition of Done. When it passes on a fresh clone, Phase 0
is complete.

## Environment parity checklist (Section 6.4.4)

- **Python** — 3.11 in both places (`python3.11 --version`).
- **PostgreSQL** — 16 in both places.
- **TimescaleDB** — same release locally and on the droplet.
- **System time** — enable NTP so the risk engine's clock-drift check does not
  fire spuriously:
  ```bash
  sudo timedatectl set-ntp true
  ```

## Optional: GitHub CLI (for CI)

```bash
sudo apt install -y gh
gh auth login
```

CI (`.github/workflows/ci.yml`) runs automatically on push once the repo has a
remote on GitHub.
