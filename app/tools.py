"""Voice agent tool registry for function calling during conversations.

Defines tools that Claude can invoke mid-conversation via the tool_use API.
Each tool is an async function returning a string result that gets fed back
to Claude as a tool_result for the final response.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "check_order_status",
        "description": "Look up the shipping status and estimated delivery date for a TechNova order by order ID (e.g., TN-10015).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The TechNova order ID (e.g., TN-10015)",
                },
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "search_products",
        "description": "Search the TechNova product catalog by keyword and optional category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword (e.g., 'wireless headphones')",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter (e.g., 'headphones', 'laptops', 'phones')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "schedule_callback",
        "description": "Schedule a callback from a TechNova support agent at the customer's preferred time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Customer's name",
                },
                "phone": {
                    "type": "string",
                    "description": "Customer's phone number",
                },
                "preferred_time": {
                    "type": "string",
                    "description": "Preferred callback time (e.g., 'tomorrow morning', '3pm today')",
                },
            },
            "required": ["customer_name", "phone", "preferred_time"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

# Simulated order database
_ORDERS = {
    **{f"TN-{10001 + i}": {"status": "Shipped", "shipped_date": "2 days ago", "eta": "3-5 business days"} for i in range(25)},
    **{f"TN-{10026 + i}": {"status": "Processing", "eta": "1-2 business days to ship"} for i in range(25)},
}

# Simulated product catalog
_PRODUCTS = [
    {"name": "TechNova Pro Wireless Headphones", "price": 79.99, "category": "headphones", "rating": 4.5},
    {"name": "TechNova Studio Monitor Headphones", "price": 149.99, "category": "headphones", "rating": 4.8},
    {"name": "TechNova UltraBook Pro 15", "price": 1299.99, "category": "laptops", "rating": 4.6},
    {"name": "TechNova SlimBook Air 13", "price": 899.99, "category": "laptops", "rating": 4.4},
    {"name": "TechNova Pixel X Phone", "price": 699.99, "category": "phones", "rating": 4.3},
    {"name": "TechNova Pixel X Pro Phone", "price": 999.99, "category": "phones", "rating": 4.7},
    {"name": "TechNova 4K Smart TV 55-inch", "price": 549.99, "category": "tvs", "rating": 4.5},
    {"name": "TechNova TabletPro 11", "price": 449.99, "category": "tablets", "rating": 4.2},
]


async def check_order_status(order_id: str) -> str:
    order = _ORDERS.get(order_id.upper())
    if not order:
        return f"Order {order_id} not found. Please verify the order ID and try again."
    if order["status"] == "Shipped":
        return f"Order {order_id}: Shipped {order['shipped_date']}. Expected delivery: {order['eta']}."
    return f"Order {order_id}: {order['status']}. {order['eta']}."


async def search_products(query: str, category: str | None = None) -> str:
    query_lower = query.lower()
    results = [
        p for p in _PRODUCTS
        if query_lower in p["name"].lower()
        and (not category or p["category"] == category.lower())
    ]
    if not results:
        return f"No products found matching '{query}'" + (f" in category '{category}'" if category else "") + "."
    lines = [f"- {p['name']}: ${p['price']:.2f} (rated {p['rating']}/5)" for p in results[:5]]
    return f"Found {len(results)} product(s):\n" + "\n".join(lines)


async def schedule_callback(customer_name: str, phone: str, preferred_time: str) -> str:
    # Simulate booking with a confirmation ID
    now = datetime.now(timezone.utc)
    conf_id = f"CB-{now.strftime('%H%M%S')}"
    return (
        f"Callback scheduled! Confirmation: {conf_id}. "
        f"Agent will call {customer_name} at {phone} during {preferred_time}."
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOL_MAP: dict[str, Callable[..., Awaitable[str]]] = {
    "check_order_status": check_order_status,
    "search_products": search_products,
    "schedule_callback": schedule_callback,
}

TOOL_TIMEOUT_SEC = 5.0


async def execute_tool(name: str, inputs: dict[str, Any]) -> str:
    """Execute a tool by name with the given inputs. Returns result string."""
    func = _TOOL_MAP.get(name)
    if not func:
        return f"Error: Unknown tool '{name}'. Available: {list(_TOOL_MAP.keys())}"
    try:
        result = await asyncio.wait_for(func(**inputs), timeout=TOOL_TIMEOUT_SEC)
        logger.info("tool_executed", tool=name, inputs=inputs)
        return result
    except asyncio.TimeoutError:
        logger.warning("tool_timeout", tool=name)
        return f"Error: Tool '{name}' timed out after {TOOL_TIMEOUT_SEC}s."
    except TypeError as e:
        logger.warning("tool_input_error", tool=name, error=str(e))
        return f"Error: Invalid inputs for tool '{name}': {e}"
