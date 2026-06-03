import unittest
from unittest.mock import Mock, patch

from src.ai import openrouter_trader


class OpenRouterTraderTests(unittest.TestCase):
    def test_direction_model_uses_deepseek_v4_flash(self):
        self.assertEqual(openrouter_trader.OPENROUTER_DIRECTION_MODEL, "deepseek/deepseek-v4-flash")
        self.assertEqual(openrouter_trader.OPENROUTER_DEFAULT_REASONING_EFFORT, "high")
        self.assertEqual(openrouter_trader.OPENROUTER_MAX_REASONING_EFFORT, "xhigh")
        self.assertEqual(openrouter_trader.OPENROUTER_DEFAULT_TIMEOUT_SECONDS, 300.0)

    def test_structured_call_sends_high_reasoning_and_parses_decision(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"decision":"LONG"}',
                        "reasoning": "full reasoning text",
                    }
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }

        with patch("src.ai.openrouter_trader.get_openrouter_api_key", return_value="key"), patch(
            "src.ai.openrouter_trader.requests.post", return_value=response
        ) as mocked_post:
            result = openrouter_trader._call_openrouter_structured_decision(
                prompt="prompt",
                reasoning_effort="high",
                response_model=openrouter_trader.TradeDirectionDecision,
                max_tokens=1234,
                timeout_seconds=345.0,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.decision.decision, "LONG")
        payload = mocked_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek/deepseek-v4-flash")
        self.assertEqual(
            payload["messages"][0]["content"],
            "You are a world-class USDT perpetual futures crypto trader. "
            "Analyze all 100 close prices in balance(not just the latest few) to judge whether a LONG or SHORT position offers a higher expected value. "
            "Return exactly one JSON decision.",
        )
        self.assertEqual(payload["messages"][1]["content"], "prompt")
        self.assertEqual(payload["reasoning"]["effort"], "high")
        self.assertFalse(payload["reasoning"]["exclude"])
        self.assertEqual(payload["max_tokens"], 1234)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(mocked_post.call_args.kwargs["timeout"], (10.0, 345.0))

    def test_max_reasoning_alias_still_maps_to_xhigh(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": '{"decision":"SHORT"}'}}],
            "usage": {},
        }

        with patch("src.ai.openrouter_trader.get_openrouter_api_key", return_value="key"), patch(
            "src.ai.openrouter_trader.requests.post", return_value=response
        ) as mocked_post:
            result = openrouter_trader._call_openrouter_structured_decision(
                prompt="prompt",
                reasoning_effort="max",
                response_model=openrouter_trader.TradeDirectionDecision,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.decision.decision, "SHORT")
        payload = mocked_post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning"]["effort"], "xhigh")

    def test_empty_openrouter_content_retries_cleanly(self):
        empty_response = Mock()
        empty_response.status_code = 200
        empty_response.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": ""}}],
            "usage": {},
        }
        valid_response = Mock()
        valid_response.status_code = 200
        valid_response.json.return_value = {
            "choices": [{"message": {"content": '{"decision":"LONG"}'}}],
            "usage": {},
        }

        with patch("src.ai.openrouter_trader.get_openrouter_api_key", return_value="key"), patch(
            "src.ai.openrouter_trader.requests.post", side_effect=[empty_response, valid_response]
        ) as mocked_post, patch("src.ai.openrouter_trader.time.sleep") as mocked_sleep:
            result = openrouter_trader._call_openrouter_structured_decision(
                prompt="prompt",
                reasoning_effort="high",
                response_model=openrouter_trader.TradeDirectionDecision,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.decision.decision, "LONG")
        self.assertEqual(mocked_post.call_count, 2)
        mocked_sleep.assert_called_once()

    def test_invalid_prompt_payload_fails_before_openrouter_call(self):
        with patch("src.ai.openrouter_trader._call_openrouter_structured_decision") as mocked_call, patch(
            "src.ai.openrouter_trader.logger"
        ):
            decision = openrouter_trader.evaluate_trade_direction(
                cycle_dir="/tmp/openrouter-test",
                symbol="BTCUSDT",
                reference_price=100.0,
                timeframe_ohlcv={"1h": []},
                reasoning_effort="high",
            )

        self.assertIsNone(decision)
        mocked_call.assert_not_called()

    def test_direction_prompt_contract_uses_symbol_reference_and_close_prices_only(self):
        prompt = openrouter_trader._build_direction_prompt(
            symbol="btcusdt",
            reference_price=100.0,
            timeframe_ohlcv={"1h": [98.0, 99.0, 100.0]},
        )

        self.assertEqual(
            prompt,
            'You are a world-class BTCUSDT trader.\n'
            'Use your best judgment to decide whether LONG or SHORT position offers the higher expected value in the future.\n'
            'Consider all 100 supplied close prices in balance, not only the most recent few, when judging the overall setup.\n'
            'Use only the supplied 1h close prices and current_price.\n'
            'Return JSON only: {"decision":"LONG"} or {"decision":"SHORT"}.\n'
            'Market payload:\n{"symbol":"BTCUSDT","reference_price":100.0,"timeframes":{"1h":[98.0,99.0,100.0]}}',
        )


if __name__ == "__main__":
    unittest.main()
