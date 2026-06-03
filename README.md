# Binance OpenRouter Trader

OpenRouter-powered six-slot Binance USDT-M futures trading bot.

This project runs a 1x-leverage portfolio loop across four fixed passive markets and two dynamically screened active markets. Each slot is evaluated one symbol at a time by OpenRouter using `deepseek/deepseek-v4-flash` with high reasoning effort, then managed with market entries/exits, rebalancing, stop-loss synchronization, and Telegram reporting.

> This software is for research and automation experiments. It is not financial advice. Futures trading can lose money quickly, and live mode sends real Binance Futures orders.

## 한국어

### 주요 기능

- OpenRouter 기반 LLM 판단
  - 기본 모델: `deepseek/deepseek-v4-flash`
  - reasoning effort: `xhigh`
  - 응답은 `LONG` 또는 `SHORT`만 허용
- 6개 슬롯 포트폴리오
  - Passive: `CLUSDT`, `XAUUSDT`, `QQQUSDT`, `BTCUSDT`
  - Active 1: 24시간 변동률 절대값이 4%에 가까운 USDT-M perpetual 후보 10개 중 거래대금 최대 심볼
  - Active 2: 24시간 변동률 절대값이 8%에 가까운 USDT-M perpetual 후보 10개 중 거래대금 최대 심볼
- 자산 배분
  - Passive 각 12.5%
  - Active 각 25%
  - 기본 총 투입률 99%, 레버리지 1x
- 리스크 관리
  - 각 포지션 진입가 기준 4% stop loss 동기화
  - 마지막 LLM 판단 기준가에서 ±1% 이동 시 재판단
  - 목표 비중에서 벗어나면 리밸런싱
  - 자동화 계좌 전용 전제: 관리되지 않는 수동 포지션은 자동 청산 대상
- 알림
  - Telegram 메시지
  - 긴 LLM reasoning 자동 분할 전송
  - 1시간봉 가격 차트 이미지 전송
- 검증
  - 실제 주문 없이 Binance 공개 데이터, OpenRouter, Telegram까지 통과하는 live-data dry-run 스크립트 제공

### 실제 구동해도 되나?

기술적으로는 live-data dry-run에서 전체 6슬롯 사이클, OpenRouter 판단, Telegram 전송, active screener, 주문 수량 계산까지 확인했습니다. 다만 실제 구동 전에는 아래 체크리스트를 반드시 확인하세요.

- Binance 계좌를 자동화 전용으로 분리했는지 확인
- 기존 수동 포지션이 있어도 자동 청산되어도 괜찮은 계좌인지 확인
- Binance Futures API key에 필요한 futures trading 권한이 있는지 확인
- `.env`가 절대 Git에 올라가지 않는지 확인
- `python scripts/dry_run_live_cycle.py`가 다시 성공하는지 확인
- 첫 live run은 아주 작은 자금으로 `python main.py --once`부터 실행
- Telegram에서 각 슬롯 판단, 주문 결과, stop sync 메시지를 확인한 뒤 scheduler 상시 실행

### 설치

```bash
git clone https://github.com/YOUR_NAME/binance-openrouter-trader.git
cd binance-openrouter-trader

python -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

`.env`를 채웁니다.

```bash
BINANCE_API_KEY="..."
BINANCE_API_SECRET="..."
OPENROUTER_API_KEY="..."
TELEGRAM_BOT_TOKEN="..."
TELEGRAM_CHAT_ID="..."
```

### 설정

런타임 설정은 [setting.yaml](./setting.yaml)에 있습니다.

```yaml
cycle_interval_seconds: 60
trigger_pct_usdt: 1.0
ai_prompt_timeframe: 1h
ai_prompt_candle_count: 100
openrouter_model: deepseek/deepseek-v4-flash
openrouter_reasoning_effort: xhigh
fixed_leverage: 1
capital_usage_ratio: 0.99
rebalance_threshold_pct: 0.03
stop_loss_pct: 0.04
passive_symbols:
  - CLUSDT
  - XAUUSDT
  - QQQUSDT
  - BTCUSDT
active_targets:
  - 4.0
  - 8.0
```

### Dry Run

실제 Binance 주문 없이 다음 항목을 실제로 검증합니다.

- Binance public market data
- Active symbol screening
- OpenRouter LLM 판단
- Telegram 메시지와 차트 전송
- 주문 수량 계산
- stop-loss sync 경로

```bash
python scripts/dry_run_live_cycle.py
```

Telegram 없이 검증하려면:

```bash
python scripts/dry_run_live_cycle.py --no-telegram
```

### 실제 실행

한 번만 실행:

```bash
python main.py --once
```

상시 실행:

```bash
python main.py
```

Linode/Ubuntu systemd 설치:

```bash
sudo bash setup_linode_systemd.sh --no-start
sudo systemctl start binance-openrouter-trader
sudo systemctl status binance-openrouter-trader
```

로그 확인:

```bash
journalctl -u binance-openrouter-trader -f
```

### 테스트

```bash
python -m unittest discover
python -m py_compile main.py src/ai/openrouter_trader.py src/strategy/portfolio_strategy.py src/strategy/active_screener.py src/strategy/scheduler.py src/binance/trade_position.py src/infra/env_loader.py src/infra/telegram.py scripts/dry_run_live_cycle.py
```

### 프로젝트 구조

```text
.
├── main.py                         # CLI entrypoint
├── setting.yaml                    # Runtime portfolio and model config
├── scripts/
│   └── dry_run_live_cycle.py       # Live-data dry-run without Binance orders
├── src/
│   ├── ai/
│   │   └── openrouter_trader.py    # OpenRouter structured LONG/SHORT decisions
│   ├── binance/
│   │   ├── common.py
│   │   ├── market_data.py
│   │   └── trade_position.py       # Binance Futures position/order helpers
│   ├── infra/
│   │   ├── env_loader.py
│   │   ├── logger.py
│   │   ├── price_chart.py
│   │   └── telegram.py
│   └── strategy/
│       ├── active_screener.py      # 4%/8% active market screening
│       ├── portfolio_strategy.py   # Six-slot portfolio state machine
│       ├── runtime_config.py
│       └── scheduler.py
└── tests/
```

### 공개 저장소 주의사항

- `.env`, `log/`, `db/`, `scheduler_state.json`은 `.gitignore`에 포함되어 있습니다.
- API key, Telegram token, 실제 계좌 정보, live cycle output은 절대 커밋하지 마세요.
- `db/`에는 LLM 입출력과 차트 산출물이 저장됩니다. 공개 이슈나 PR에 첨부하기 전에 내용을 확인하세요.

## English

### Features

- OpenRouter-based LLM decisions
  - Default model: `deepseek/deepseek-v4-flash`
  - Reasoning effort: `xhigh`
  - The bot accepts only `LONG` or `SHORT`
- Six-slot portfolio
  - Passive: `CLUSDT`, `XAUUSDT`, `QQQUSDT`, `BTCUSDT`
  - Active 1: top-volume symbol among the 10 USDT-M perpetual candidates closest to a 4% absolute 24h move
  - Active 2: top-volume symbol among the 10 USDT-M perpetual candidates closest to an 8% absolute 24h move
- Allocation
  - 12.5% per passive slot
  - 25% per active slot
  - 99% default capital usage, 1x leverage
- Risk management
  - Native stop loss synchronized at 4% from entry price
  - Re-evaluates a slot after a ±1% move from the last LLM decision anchor
  - Rebalances toward target slot weights
  - Designed for a dedicated automation account: unmanaged manual positions may be closed automatically
- Notifications
  - Telegram messages
  - Long LLM reasoning split into multiple Telegram chunks
  - 1h price chart images
- Validation
  - Includes a live-data dry-run script that calls Binance public data, OpenRouter, and Telegram without submitting Binance orders

### Can I Run It Live?

The project has passed a full live-data dry run for all six slots, including OpenRouter decisions, Telegram delivery, active screening, and order quantity planning. Before running live, complete this checklist:

- Use a dedicated Binance Futures automation account
- Confirm unmanaged/manual positions may be closed automatically
- Confirm your Binance API key has the required Futures permissions
- Confirm `.env` is never committed
- Re-run `python scripts/dry_run_live_cycle.py`
- Start live trading with a very small balance and `python main.py --once`
- Review Telegram messages for each slot before running the scheduler continuously

### Installation

```bash
git clone https://github.com/YOUR_NAME/binance-openrouter-trader.git
cd binance-openrouter-trader

python -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Fill `.env`.

```bash
BINANCE_API_KEY="..."
BINANCE_API_SECRET="..."
OPENROUTER_API_KEY="..."
TELEGRAM_BOT_TOKEN="..."
TELEGRAM_CHAT_ID="..."
```

### Configuration

Runtime settings live in [setting.yaml](./setting.yaml).

```yaml
cycle_interval_seconds: 60
trigger_pct_usdt: 1.0
ai_prompt_timeframe: 1h
ai_prompt_candle_count: 100
openrouter_model: deepseek/deepseek-v4-flash
openrouter_reasoning_effort: xhigh
fixed_leverage: 1
capital_usage_ratio: 0.99
rebalance_threshold_pct: 0.03
stop_loss_pct: 0.04
passive_symbols:
  - CLUSDT
  - XAUUSDT
  - QQQUSDT
  - BTCUSDT
active_targets:
  - 4.0
  - 8.0
```

### Dry Run

This validates the live external integrations without Binance order submission:

- Binance public market data
- Active symbol screening
- OpenRouter LLM decisions
- Telegram messages and chart images
- Order quantity planning
- Stop-loss sync path

```bash
python scripts/dry_run_live_cycle.py
```

Without Telegram:

```bash
python scripts/dry_run_live_cycle.py --no-telegram
```

### Live Run

Run one cycle:

```bash
python main.py --once
```

Run the scheduler:

```bash
python main.py
```

Install as a systemd service on Linode/Ubuntu:

```bash
sudo bash setup_linode_systemd.sh --no-start
sudo systemctl start binance-openrouter-trader
sudo systemctl status binance-openrouter-trader
```

Follow logs:

```bash
journalctl -u binance-openrouter-trader -f
```

### Tests

```bash
python -m unittest discover
python -m py_compile main.py src/ai/openrouter_trader.py src/strategy/portfolio_strategy.py src/strategy/active_screener.py src/strategy/scheduler.py src/binance/trade_position.py src/infra/env_loader.py src/infra/telegram.py scripts/dry_run_live_cycle.py
```

### Repository Layout

```text
.
├── main.py                         # CLI entrypoint
├── setting.yaml                    # Runtime portfolio and model config
├── scripts/
│   └── dry_run_live_cycle.py       # Live-data dry-run without Binance orders
├── src/
│   ├── ai/
│   │   └── openrouter_trader.py    # OpenRouter structured LONG/SHORT decisions
│   ├── binance/
│   │   ├── common.py
│   │   ├── market_data.py
│   │   └── trade_position.py       # Binance Futures position/order helpers
│   ├── infra/
│   │   ├── env_loader.py
│   │   ├── logger.py
│   │   ├── price_chart.py
│   │   └── telegram.py
│   └── strategy/
│       ├── active_screener.py      # 4%/8% active market screening
│       ├── portfolio_strategy.py   # Six-slot portfolio state machine
│       ├── runtime_config.py
│       └── scheduler.py
└── tests/
```

### Open Source Safety

- `.env`, `log/`, `db/`, and `scheduler_state.json` are ignored by Git.
- Never commit API keys, Telegram tokens, account data, or live cycle outputs.
- `db/` stores LLM inputs/outputs and chart artifacts. Review files before sharing them in issues or pull requests.

## License

MIT. See [LICENSE](./LICENSE).
