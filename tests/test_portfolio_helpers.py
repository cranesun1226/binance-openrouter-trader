import unittest

from src.strategy import portfolio_strategy


class PortfolioHelperTests(unittest.TestCase):
    def test_default_config_builds_six_slots_in_priority_order(self):
        config = {
            "passive_symbols": ["CLUSDT", "XAUUSDT", "QQQUSDT", "BTCUSDT"],
            "active_targets": [4.0, 8.0],
        }

        slots = portfolio_strategy._build_portfolio_slots(config)

        self.assertEqual([slot.slot_id for slot in slots], [
            "passive_cl",
            "passive_xau",
            "passive_qqq",
            "passive_btc",
            "active_1",
            "active_2",
        ])
        self.assertEqual([slot.symbol for slot in slots[:4]], ["CLUSDT", "XAUUSDT", "QQQUSDT", "BTCUSDT"])
        self.assertEqual([slot.target_margin_ratio for slot in slots], [0.125, 0.125, 0.125, 0.125, 0.25, 0.25])

    def test_target_notional_uses_capital_usage_ratio_and_leverage(self):
        slot = portfolio_strategy.PortfolioSlot(
            slot_id="active_1",
            label="active1",
            kind="active",
            target_margin_ratio=0.25,
            active_target_abs_change_pct=4.0,
        )

        target = portfolio_strategy._target_notional_usdt(
            account_equity=1000.0,
            slot=slot,
            capital_usage_ratio=0.99,
            leverage=1,
        )

        self.assertEqual(target, 247.5)

    def test_fixed_stop_loss_is_entry_price_four_percent(self):
        self.assertEqual(
            portfolio_strategy._resolve_fixed_stop_loss_price(
                direction="long",
                entry_price=100.0,
                stop_loss_pct=0.04,
            ),
            96.0,
        )
        self.assertEqual(
            portfolio_strategy._resolve_fixed_stop_loss_price(
                direction="short",
                entry_price=100.0,
                stop_loss_pct=0.04,
            ),
            104.0,
        )

    def test_trigger_is_per_slot_last_llm_anchor(self):
        slot_state = {
            "last_ai_trigger_price": 100.0,
            "next_trigger_down": 99.0,
            "next_trigger_up": 101.0,
        }

        waiting = portfolio_strategy._determine_ai_trigger(
            has_position=True,
            current_price=100.5,
            slot_state=slot_state,
            trigger_pct_usdt=1.0,
        )
        triggered = portfolio_strategy._determine_ai_trigger(
            has_position=True,
            current_price=101.01,
            slot_state=slot_state,
            trigger_pct_usdt=1.0,
        )

        self.assertFalse(waiting["should_trigger"])
        self.assertTrue(triggered["should_trigger"])
        self.assertEqual(triggered["reason"], "price_distance_reached")

    def test_trigger_levels_keep_precision_for_low_priced_symbols(self):
        levels = portfolio_strategy._build_trigger_levels(0.093455, 1.0)

        self.assertEqual(levels["trigger_price"], 0.093455)
        self.assertLess(levels["next_trigger_down"], levels["trigger_price"])
        self.assertGreater(levels["next_trigger_up"], levels["trigger_price"])

    def test_duplicate_active_state_symbol_is_cleared_for_later_slot(self):
        config = {
            "passive_symbols": ["CLUSDT", "XAUUSDT", "QQQUSDT", "BTCUSDT"],
            "active_targets": [4.0, 8.0],
        }
        slots = portfolio_strategy._build_portfolio_slots(config)
        state = portfolio_strategy._normalize_portfolio_state(
            {
                "version": portfolio_strategy.STATE_VERSION,
                "slots": {
                    "active_1": {"symbol": "ETHUSDT", "last_ai_decision": "LONG"},
                    "active_2": {"symbol": "ETHUSDT", "last_ai_decision": "SHORT"},
                },
            },
            slots,
        )

        self.assertEqual(state["slots"]["active_1"]["symbol"], "ETHUSDT")
        self.assertIsNone(state["slots"]["active_2"]["symbol"])


if __name__ == "__main__":
    unittest.main()
