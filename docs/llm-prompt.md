# LLM Prompt Contract

This document describes the exact OpenRouter request shape used by Binance OpenRouter Trader for every slot decision.

이 문서는 Binance OpenRouter Trader가 각 슬롯을 판단할 때 OpenRouter에 보내는 정확한 요청 구조를 설명합니다.

## Summary

- One OpenRouter call is made for one symbol at a time.
- The model is `deepseek/deepseek-v4-flash`.
- The maximum reasoning setting is represented as `xhigh`; if `max` is provided, the runtime normalizes it to `xhigh`.
- The model receives only the supplied symbol, live reference price, and close-price arrays.
- The prompt explicitly tells the model to consider all 100 supplied close prices in balance instead of focusing only on the most recent few candles.
- The accepted final answer is strictly one JSON object: `{"decision":"LONG"}` or `{"decision":"SHORT"}`.
- Reasoning is requested from OpenRouter with `exclude: false` and is stored/sent to Telegram when returned.

## Request Body

```json
{
  "model": "deepseek/deepseek-v4-flash",
  "messages": [
    {
      "role": "system",
      "content": "You are a world-class USDT perpetual futures crypto trader. Analyze all 100 close prices in balance(not just the latest few) to judge whether a LONG or SHORT position offers a higher expected value. Return exactly one JSON decision."
    },
    {
      "role": "user",
      "content": "You are a world-class BTCUSDT trader.\nUse your best judgment to decide whether LONG or SHORT position offers the higher expected value in the future.\nConsider all 100 supplied close prices in balance, not only the most recent few, when judging the overall setup.\nUse only the supplied 1h close prices and current_price.\nReturn JSON only: {\"decision\":\"LONG\"} or {\"decision\":\"SHORT\"}.\nMarket payload:\n{\"symbol\":\"BTCUSDT\",\"reference_price\":100000.0,\"timeframes\":{\"1h\":[99100.0,99500.0,100000.0]}}"
    }
  ],
  "reasoning": {
    "effort": "xhigh",
    "exclude": false
  },
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "trade_direction_decision",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "decision": {
            "type": "string",
            "enum": ["LONG", "SHORT"]
          }
        },
        "required": ["decision"],
        "additionalProperties": false
      }
    }
  },
  "max_tokens": 8192
}
```

## User Prompt Template

The user message is generated exactly as:

```text
You are a world-class {SYMBOL} trader.
Use your best judgment to decide whether LONG or SHORT position offers the higher expected value in the future.
Consider all 100 supplied close prices in balance, not only the most recent few, when judging the overall setup.
Use only the supplied 1h close prices and current_price.
Return JSON only: {"decision":"LONG"} or {"decision":"SHORT"}.
Market payload:
{COMPACT_JSON_PAYLOAD}
```

The compact JSON payload has this shape:

```json
{
  "symbol": "BTCUSDT",
  "reference_price": 100000.0,
  "timeframes": {
    "1h": [99100.0, 99500.0, 100000.0]
  }
}
```

## Market Data Included

By default, each prompt includes `100` recent `1h` close prices for the evaluated symbol. The newest close value is aligned to the live reference price fetched at decision time, so the prompt reflects the current lookup moment as closely as the Binance API allows. The prompt text refers to this current value as `current_price`, while the serialized payload field is named `reference_price`.

The prompt does not include account balance, open positions, order history, order book data, funding rates, news, indicators, or other symbols. Portfolio state determines whether a slot needs a fresh decision, but the LLM direction decision itself is intentionally isolated to the symbol and close-price payload.

## Stored Artifacts

For every OpenRouter decision, the runtime stores:

- `openrouter_ai_<mode>_input.json`: model, reasoning effort, prompt, and payload.
- `openrouter_ai_<mode>_output.json`: parsed decision, raw response, reasoning, usage, estimated cost, and full response payload.

These files are written under `db/` and may contain live trading context. Review them before sharing logs in a public issue or pull request.

## 한국어 요약

- 한 번의 LLM 호출은 반드시 한 종목만 판단합니다.
- 기본 모델은 `deepseek/deepseek-v4-flash`입니다.
- 최대 사고 설정은 런타임에서 `xhigh`로 사용합니다. 설정값에 `max`를 넣어도 `xhigh`로 정규화됩니다.
- LLM에는 종목명, 현재 기준가, 1시간봉 종가 배열만 전달됩니다.
- 프롬프트는 최신 몇 개 봉만 보지 말고 100개 종가 전체를 균형 있게 보라고 명시합니다.
- 최종 응답은 strict JSON schema로 `LONG` 또는 `SHORT`만 허용합니다.
- OpenRouter reasoning은 `exclude: false`로 요청되며, 반환되면 저장되고 Telegram으로 분할 전송됩니다.
