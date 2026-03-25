"""Unit tests for voice agent tool registry and function calling."""
from __future__ import annotations

import asyncio
import pytest
from app.tools import (
    TOOL_DEFINITIONS,
    check_order_status,
    execute_tool,
    schedule_callback,
    search_products,
)


# ---------------------------------------------------------------------------
# Tool definitions schema
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_has_three_tools(self):
        assert len(TOOL_DEFINITIONS) == 3

    def test_all_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert names == {"check_order_status", "search_products", "schedule_callback"}


# ---------------------------------------------------------------------------
# check_order_status
# ---------------------------------------------------------------------------

class TestCheckOrderStatus:
    @pytest.mark.asyncio
    async def test_shipped_order(self):
        result = await check_order_status("TN-10001")
        assert "Shipped" in result
        assert "TN-10001" in result

    @pytest.mark.asyncio
    async def test_processing_order(self):
        result = await check_order_status("TN-10030")
        assert "Processing" in result

    @pytest.mark.asyncio
    async def test_not_found_order(self):
        result = await check_order_status("TN-99999")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        result = await check_order_status("tn-10001")
        assert "Shipped" in result


# ---------------------------------------------------------------------------
# search_products
# ---------------------------------------------------------------------------

class TestSearchProducts:
    @pytest.mark.asyncio
    async def test_search_by_keyword(self):
        result = await search_products("headphones")
        assert "Headphones" in result
        assert "Found" in result

    @pytest.mark.asyncio
    async def test_search_with_category(self):
        result = await search_products("pro", category="laptops")
        assert "UltraBook" in result

    @pytest.mark.asyncio
    async def test_no_results(self):
        result = await search_products("quantum_computer_xyz")
        assert "No products found" in result

    @pytest.mark.asyncio
    async def test_results_include_price(self):
        result = await search_products("headphones")
        assert "$" in result


# ---------------------------------------------------------------------------
# schedule_callback
# ---------------------------------------------------------------------------

class TestScheduleCallback:
    @pytest.mark.asyncio
    async def test_callback_scheduled(self):
        result = await schedule_callback("John Doe", "555-0100", "tomorrow morning")
        assert "CB-" in result
        assert "John Doe" in result
        assert "555-0100" in result

    @pytest.mark.asyncio
    async def test_confirmation_id_generated(self):
        result = await schedule_callback("Jane", "555-0200", "3pm today")
        assert "Confirmation" in result


# ---------------------------------------------------------------------------
# execute_tool (registry)
# ---------------------------------------------------------------------------

class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_execute_known_tool(self):
        result = await execute_tool("check_order_status", {"order_id": "TN-10005"})
        assert "Shipped" in result

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        result = await execute_tool("nonexistent_tool", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_execute_with_invalid_inputs(self):
        result = await execute_tool("check_order_status", {"wrong_param": "x"})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_execute_search_with_category(self):
        result = await execute_tool("search_products", {"query": "phone", "category": "phones"})
        assert "Pixel" in result

    @pytest.mark.asyncio
    async def test_execute_schedule(self):
        result = await execute_tool(
            "schedule_callback",
            {"customer_name": "Test", "phone": "555", "preferred_time": "now"},
        )
        assert "scheduled" in result
