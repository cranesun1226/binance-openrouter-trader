import tempfile
import unittest
from unittest.mock import patch

from src.strategy import portfolio_strategy


def _config():
    return {
        "cycle_interval_seconds": 60,
        "trigger_pct_usdt": 1.0,
        "fixed_leverage": 1,
        "stop_loss_pct": 0.04,
        "capital_usage_ratio": 0.99,
        "rebalance_threshold_pct": 0.03,
        "ai_prompt_timeframe": "1h",
        "ai_prompt_candle_count": 100,
        "openrouter_model": "deepseek/deepseek-v4-flash",
        "openrouter_reasoning_effort": "xhigh",
        "openrouter_max_tokens": 8192,
        "passive_symbols": ["CLUSDT", "XAUUSDT", "QQQUSDT", "BTCUSDT"],
        "active_targets": [4.0, 8.0],
        "active_candidate_pool_size": 10,
        "screener_quote": "USDT",
        "screener_timeout": 30.0,
        "screener_retries": 3,
        "screener_request_sleep": 0.1,
    }


def _active_slot():
    return portfolio_strategy.PortfolioSlot(
        slot_id="active_1",
        label="active1",
        kind="active",
        target_margin_ratio=0.25,
        active_target_abs_change_pct=4.0,
    )


def _long_position(symbol="ETHUSDT"):
    return {
        "symbol": symbol,
        "positionAmt": "2",
        "side": "Buy",
        "entryPrice": "100",
        "markPrice": "100.5",
        "leverage": "1",
        "positionValue": "201",
    }


class PortfolioFlowTests(unittest.TestCase):
    def test_active_existing_same_direction_does_not_rescreen(self):
        slot = _active_slot()
        slot_state = {
            "slot_id": "active_1",
            "kind": "active",
            "symbol": "ETHUSDT",
            "last_ai_trigger_price": 100.0,
            "next_trigger_down": 99.0,
            "next_trigger_up": 101.0,
            "last_ai_decision": "LONG",
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.strategy.portfolio_strategy._reference_price", return_value=101.5
        ), patch(
            "src.strategy.portfolio_strategy._evaluate_slot_direction",
            return_value=("LONG", {"reasoning": "keep"}, {}),
        ) as mocked_ai, patch(
            "src.strategy.portfolio_strategy._rebalance_existing_position",
            return_value={"success": True, "action": "kept_position_size", "position": {"symbol": "ETHUSDT"}},
        ) as mocked_rebalance, patch(
            "src.strategy.portfolio_strategy._screen_active_candidate"
        ) as mocked_screen:
            result, updated_state, active_symbol = portfolio_strategy._run_active_slot(
                slot=slot,
                slot_state=slot_state,
                config=_config(),
                api_key="key",
                api_secret="secret",
                account_overview={"equity": 1000.0, "available_balance": 500.0},
                open_positions=[_long_position()],
                reserved_symbols=set(),
                as_of_ms=1,
                cycle_dir=temp_dir,
                notification_callback=None,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "kept_position_by_ai")
        self.assertEqual(active_symbol, "ETHUSDT")
        self.assertEqual(updated_state["symbol"], "ETHUSDT")
        mocked_ai.assert_called_once()
        mocked_rebalance.assert_called_once()
        mocked_screen.assert_not_called()

    def test_active_opposite_direction_closes_then_screens_new_candidate(self):
        slot = _active_slot()
        slot_state = {
            "slot_id": "active_1",
            "kind": "active",
            "symbol": "ETHUSDT",
            "last_ai_trigger_price": 100.0,
            "next_trigger_down": 99.0,
            "next_trigger_up": 101.0,
            "last_ai_decision": "LONG",
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.strategy.portfolio_strategy._reference_price",
            side_effect=[101.5, 55.0],
        ), patch(
            "src.strategy.portfolio_strategy._evaluate_slot_direction",
            side_effect=[("SHORT", {"reasoning": "exit"}, {}), ("LONG", {"reasoning": "enter"}, {})],
        ), patch(
            "src.strategy.portfolio_strategy._close_existing_position",
            return_value={"success": True, "action": "closed_position", "symbol": "ETHUSDT"},
        ) as mocked_close, patch(
            "src.strategy.portfolio_strategy._screen_active_candidate",
            return_value={"symbol": "SOLUSDT", "selection": {}, "metadata": {}},
        ) as mocked_screen, patch(
            "src.strategy.portfolio_strategy.get_account_overview",
            return_value={"equity": 1000.0, "available_balance": 500.0},
        ), patch(
            "src.strategy.portfolio_strategy._place_direction_position",
            return_value={"success": True, "action": "opened_new_position", "position": {"symbol": "SOLUSDT"}},
        ) as mocked_place, patch(
            "src.strategy.portfolio_strategy._sync_position_after_trade",
            return_value={"position": {"symbol": "SOLUSDT"}, "stop_sync": {"success": True}},
        ):
            result, updated_state, active_symbol = portfolio_strategy._run_active_slot(
                slot=slot,
                slot_state=slot_state,
                config=_config(),
                api_key="key",
                api_secret="secret",
                account_overview={"equity": 1000.0, "available_balance": 500.0},
                open_positions=[_long_position()],
                reserved_symbols={"CLUSDT"},
                as_of_ms=1,
                cycle_dir=temp_dir,
                notification_callback=None,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["symbol"], "SOLUSDT")
        self.assertEqual(updated_state["symbol"], "SOLUSDT")
        self.assertEqual(active_symbol, "SOLUSDT")
        mocked_close.assert_called_once()
        mocked_screen.assert_called_once()
        self.assertIn("ETHUSDT", mocked_screen.call_args.kwargs["excluded_symbols"])
        mocked_place.assert_called_once()


if __name__ == "__main__":
    unittest.main()
