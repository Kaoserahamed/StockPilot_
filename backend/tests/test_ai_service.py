"""Tests for deterministic AI answer-building (ai_service._rule_answer, _business_snapshot)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import ai_service


class TestBusinessSnapshot:
    @patch.object(ai_service.f, "resolve_range")
    @patch.object(ai_service.f, "profit_summary")
    @patch.object(ai_service.f, "sales_trend")
    @patch.object(ai_service.f, "top_products")
    @patch.object(ai_service.f, "customer_stats")
    @patch.object(ai_service.f, "supplier_stats")
    @patch.object(ai_service.f, "inventory_value")
    def test_snapshot_assembles_all_sections(
        self, mock_inv, mock_supp, mock_cust, mock_top, mock_trend, mock_profit, mock_range
    ) -> None:
        mock_range.return_value = ("s", "e")
        mock_profit.return_value = {"gross_profit": 100, "net_profit": 50}
        mock_trend.return_value = [{"period": "d1", "revenue": 10}]
        mock_top.return_value = [{"product_name": "Widget", "quantity": 5}]
        mock_cust.return_value = [{"customer_name": "A", "spent": 10}]
        mock_supp.return_value = [{"supplier_name": "S", "purchased": 20}]
        mock_inv.return_value = {"units": 100, "skus": 5, "cost_value": 50, "retail_value": 100}

        snap = ai_service._business_snapshot(MagicMock(), 1, preset="week")

        assert snap["preset"] == "week"
        assert snap["profit"]["gross_profit"] == 100
        assert snap["trend"][0]["period"] == "d1"
        assert snap["top_products"][0]["product_name"] == "Widget"
        assert snap["customers"][0]["customer_name"] == "A"
        assert snap["suppliers"][0]["supplier_name"] == "S"
        assert snap["inventory"]["units"] == 100

    @patch.object(ai_service.f, "resolve_range")
    def test_snapshot_unknown_preset_defaults_to_month(self, mock_range) -> None:
        mock_range.return_value = ("s", "e")
        with (
            patch.object(ai_service.f, "profit_summary", return_value={}),
            patch.object(ai_service.f, "sales_trend", return_value=[]),
            patch.object(ai_service.f, "top_products", return_value=[]),
            patch.object(ai_service.f, "customer_stats", return_value=[]),
            patch.object(ai_service.f, "supplier_stats", return_value=[]),
            patch.object(ai_service.f, "inventory_value", return_value={}),
        ):
            snap = ai_service._business_snapshot(MagicMock(), 1, preset="bogus")
            mock_range.assert_called_with("month")
            assert snap["preset"] == "bogus"


def _snapshot(**overrides) -> dict:
    """A complete snapshot, so ``_rule_answer`` can read every section it keys on."""
    snap = {
        "preset": "month",
        "profit": {
            "orders": 12,
            "gross_revenue": 1000.0,
            "refunded": 100.0,
            "net_revenue": 900.0,
            "cogs": 400.0,
            "total_expenses": 200.0,
            "gross_profit": 500.0,
            "net_profit": 300.0,
        },
        "trend": [],
        "top_products": [
            {"product_name": "Widget", "quantity": 5, "revenue": 250.0, "profit": 50.0}
        ],
        "customers": [{"customer_name": "Acme", "spent": 150.0, "orders": 3}],
        "suppliers": [
            {"supplier_name": "Globex", "purchased": 40.0, "orders": 2, "outstanding": 10.0}
        ],
        "inventory": {"units": 100, "skus": 5, "cost_value": 400.0, "retail_value": 900.0},
    }
    snap.update(overrides)
    return snap


class TestRuleAnswer:
    """The rule engine is the deterministic fallback behind every AI answer.

    It is what users see when no Gemini key is configured, so each branch is a
    user-visible sentence and each deserves an assertion on its own.
    """

    def test_inventory_question_reports_units_and_fastest_mover(self) -> None:
        answer = ai_service._rule_answer("which items are low stock?", _snapshot())

        assert "Inventory: 100 units across 5 SKUs" in answer
        assert "cost value 400.0, retail 900.0" in answer
        assert "Fastest mover: Widget (5 sold)" in answer

    def test_inventory_question_without_sales_omits_fastest_mover(self) -> None:
        answer = ai_service._rule_answer("how is my inventory?", _snapshot(top_products=[]))

        assert "Inventory: 100 units across 5 SKUs" in answer
        assert "Fastest mover" not in answer

    def test_customer_question_reports_top_customer(self) -> None:
        answer = ai_service._rule_answer("who is my best customer?", _snapshot())

        assert "Top customer: Acme spent 150.0 across 3 order(s)" in answer

    def test_customer_question_without_customer_tagged_sales(self) -> None:
        answer = ai_service._rule_answer("who is my best customer?", _snapshot(customers=[]))

        assert answer == "No customer-tagged sales in this period."

    def test_supplier_question_reports_top_supplier(self) -> None:
        answer = ai_service._rule_answer("which supplier do I buy from most?", _snapshot())

        assert "Top supplier: Globex supplied 40.0 (2 order(s), outstanding 10.0)" in answer

    def test_supplier_question_without_purchases(self) -> None:
        answer = ai_service._rule_answer("any purchases?", _snapshot(suppliers=[]))

        assert answer == "No purchases recorded in this period."

    def test_expense_question_reports_expenses_and_profit(self) -> None:
        answer = ai_service._rule_answer("what is my largest expense?", _snapshot())

        assert "Total expenses: 200.0" in answer
        assert "Gross profit 500.0" in answer
        assert "net profit 300.0" in answer

    def test_best_seller_question_reports_top_product(self) -> None:
        answer = ai_service._rule_answer("which product sold the most?", _snapshot())

        assert "Best seller: Widget - 5 unit(s)" in answer
        assert "revenue 250.0" in answer
        assert "est. profit 50.0" in answer

    def test_best_seller_question_without_sales(self) -> None:
        answer = ai_service._rule_answer("what sold the most?", _snapshot(top_products=[]))

        assert answer == "No product sales in this period."

    def test_profit_question_explains_the_breakdown(self) -> None:
        answer = ai_service._rule_answer("why did my profit fall?", _snapshot())

        assert "Revenue (net) 900.0 from 12 order(s)" in answer
        assert "COGS 400.0" in answer
        assert "gross 500.0, net 300.0" in answer

    def test_unrecognised_question_falls_back_to_sales_summary(self) -> None:
        answer = ai_service._rule_answer("hello there", _snapshot())

        assert "Sales: 12 order(s)" in answer
        assert "gross revenue 1000.0" in answer
        assert "refunded 100.0" in answer
        assert "net revenue 900.0" in answer

    def test_matching_is_case_insensitive(self) -> None:
        answer = ai_service._rule_answer("WHICH ITEMS ARE LOW STOCK?", _snapshot())

        assert "Inventory: 100 units across 5 SKUs" in answer
