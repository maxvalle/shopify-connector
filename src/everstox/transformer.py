"""Shopify to Everstox order transformation.

Transforms Shopify order data into the Everstox API payload format,
handling:
- Partial fulfillment (only remaining quantities)
- Address mapping
- Price and tax calculations
- Priority parsing from tags
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from src.config import Settings, get_settings
from src.filters import PriorityParser
from src.logging_config import get_logger

logger = get_logger(__name__)


class EverstoxTransformer:
    """Transforms Shopify orders to Everstox payload format.

    Handles the mapping of Shopify GraphQL order data to the Everstox
    order creation API format, including:
    - Order metadata (number, date, status)
    - Customer shipping and billing addresses
    - Line items with remaining fulfillable quantities
    - Price calculations (gross, net, tax)
    - Priority extraction from tags

    Example:
        >>> transformer = EverstoxTransformer()
        >>> payload = transformer.transform(shopify_order)
        >>> # payload is ready for Everstox API
    """

    def __init__(self, settings: Settings | None = None):
        """Initialize the transformer.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()

    def transform(self, order: dict[str, Any]) -> dict[str, Any]:
        """Transform a Shopify order to Everstox payload format.

        Args:
            order: Shopify order data from GraphQL API.

        Returns:
            Everstox-formatted order payload ready for API submission.
        """
        order_name = order.get("name", "unknown")
        logger.debug(
            "Transforming order",
            extra={"order_name": order_name},
        )

        # Parse priority from tags
        tags = order.get("tags", [])
        priority = PriorityParser.parse(tags)

        # Transform line items (only fulfillable quantities)
        order_items, fulfillment_stats = self._transform_line_items(order)

        # Log partial fulfillment details
        if fulfillment_stats["skipped"] > 0:
            logger.info(
                "Partial fulfillment detected for order %s: %d items to fulfill, %d already fulfilled",
                order_name,
                fulfillment_stats["included"],
                fulfillment_stats["skipped"],
                extra={
                    "order_name": order_name,
                    "items_to_fulfill": fulfillment_stats["included"],
                    "items_skipped": fulfillment_stats["skipped"],
                    "total_quantity": fulfillment_stats["total_quantity"],
                },
            )

        # Build the Everstox payload
        payload = {
            "shop_instance_id": self.settings.everstox_shop_id,
            "order_number": order_name,
            "order_date": order.get("createdAt", datetime.now(timezone.utc).isoformat()),
            "financial_status": self._map_financial_status(
                order.get("displayFinancialStatus")
            ),
            "order_priority": priority,
            "currency": order.get("currencyCode", "EUR"),
            "customer_email": order.get("email"),
            "shipping_address": self._transform_address(order.get("shippingAddress")),
            "billing_address": self._transform_address(order.get("billingAddress")),
            "shipping": self._transform_shipping(order.get("shippingLine")),
            "order_items": order_items,
            "order_totals": self._calculate_totals(order),
            # Optional fields - placeholders
            "payment_method_id": None,
            "requested_warehouse_id": None,
            # Metadata
            "external_id": order.get("id"),
            "tags": tags,
        }

        logger.debug(
            "Order transformed",
            extra={
                "order_name": order_name,
                "items_count": len(order_items),
                "priority": priority,
            },
        )

        return payload

    def transform_batch(
        self, orders: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Transform multiple Shopify orders to Everstox payloads.

        Args:
            orders: List of Shopify order data from GraphQL API.

        Returns:
            List of Everstox-formatted order payloads.
        """
        payloads = []
        for order in orders:
            payload = self.transform(order)
            # Only include orders that have items to fulfill
            if payload["order_items"]:
                payloads.append(payload)
            else:
                logger.info(
                    "Skipping fully fulfilled order: %s",
                    order.get("name", "unknown"),
                    extra={"order_name": order.get("name")},
                )
        return payloads

    def has_fulfillable_items(self, order: dict[str, Any]) -> bool:
        """Check if an order has any items remaining to fulfill.

        Args:
            order: Shopify order data.

        Returns:
            True if the order has at least one item with fulfillableQuantity > 0.
        """
        line_items = order.get("lineItems", {}).get("edges", [])
        for edge in line_items:
            node = edge.get("node", {})
            if node.get("fulfillableQuantity", 0) > 0:
                return True
        return False

    def get_fulfillment_summary(
        self, order: dict[str, Any]
    ) -> dict[str, Any]:
        """Get a summary of the fulfillment status for an order.

        Args:
            order: Shopify order data.

        Returns:
            Dictionary with fulfillment statistics.
        """
        line_items = order.get("lineItems", {}).get("edges", [])
        total_ordered = 0
        total_fulfillable = 0
        fully_fulfilled_count = 0
        partially_fulfilled_count = 0

        for edge in line_items:
            node = edge.get("node", {})
            ordered_qty = node.get("quantity", 0)
            fulfillable_qty = node.get("fulfillableQuantity", 0)

            total_ordered += ordered_qty
            total_fulfillable += fulfillable_qty

            if fulfillable_qty == 0:
                fully_fulfilled_count += 1
            elif fulfillable_qty < ordered_qty:
                partially_fulfilled_count += 1

        return {
            "total_line_items": len(line_items),
            "total_ordered_quantity": total_ordered,
            "total_fulfillable_quantity": total_fulfillable,
            "fully_fulfilled_items": fully_fulfilled_count,
            "partially_fulfilled_items": partially_fulfilled_count,
            "is_fully_fulfilled": total_fulfillable == 0,
            "is_partially_fulfilled": 0 < total_fulfillable < total_ordered,
        }

    def _transform_line_items(
        self, order: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Transform line items, including only fulfillable quantities.

        Implements partial fulfillment by only syncing the remaining
        unfulfilled quantity for each line item. Skips items where
        fulfillableQuantity <= 0.

        Args:
            order: Shopify order data.

        Returns:
            Tuple of (transformed_items, fulfillment_stats).
            fulfillment_stats contains: included, skipped, total_quantity.
        """
        items = []
        line_items = order.get("lineItems", {}).get("edges", [])
        stats = {"included": 0, "skipped": 0, "total_quantity": 0}
        order_name = order.get("name", "unknown")

        for edge in line_items:
            node = edge.get("node", {})
            fulfillable_qty = node.get("fulfillableQuantity", 0)
            sku = node.get("sku") or ""

            # Skip fully fulfilled items
            if fulfillable_qty <= 0:
                stats["skipped"] += 1
                logger.debug(
                    "Skipping fully fulfilled line item",
                    extra={
                        "sku": sku,
                        "order_name": order_name,
                    },
                )
                continue

            stats["included"] += 1
            stats["total_quantity"] += fulfillable_qty

            # Get pricing - prefer discounted price, fall back to original
            unit_price = self._get_shop_money_amount(
                node.get("discountedUnitPriceSet")
            ) or self._get_shop_money_amount(node.get("originalUnitPriceSet"))

            # Calculate tax rate from tax lines
            tax_rate = Decimal("0")
            tax_lines = node.get("taxLines", [])
            if tax_lines:
                # Use the first tax line rate (convert from decimal to percentage)
                tax_rate = Decimal(str(tax_lines[0].get("rate", 0))) * 100

            # Calculate net price (price without tax)
            # Formula: price_net = price_gross / (1 + tax_rate/100)
            if unit_price and tax_rate > 0:
                price_net = unit_price / (1 + tax_rate / 100)
            else:
                price_net = unit_price or Decimal("0")

            item = {
                "product": {
                    "sku": sku,
                    "name": node.get("name") or "",
                },
                "quantity": fulfillable_qty,
                "price_gross": float(unit_price) if unit_price else 0,
                "price_net": float(price_net),
                "tax_rate": float(tax_rate),
                "external_id": node.get("id"),
            }

            items.append(item)

        return items, stats

    def _transform_address(
        self, address: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Transform a Shopify address to Everstox format.

        Args:
            address: Shopify address data.

        Returns:
            Everstox-formatted address or None if input is None.
        """
        if not address:
            return None

        return {
            "first_name": address.get("firstName") or "",
            "last_name": address.get("lastName") or "",
            "company": address.get("company") or "",
            "street": address.get("address1") or "",
            "street_2": address.get("address2") or "",
            "city": address.get("city") or "",
            "state": address.get("provinceCode") or address.get("province") or "",
            "country_code": address.get("countryCodeV2") or "",
            "postal_code": address.get("zip") or "",
            "phone": address.get("phone") or "",
        }

    def _transform_shipping(
        self, shipping_line: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Transform shipping information.

        Args:
            shipping_line: Shopify shipping line data.

        Returns:
            Everstox-formatted shipping info or None.
        """
        if not shipping_line:
            return None

        price = self._get_shop_money_amount(shipping_line.get("originalPriceSet"))

        # Get tax rate from shipping tax lines
        tax_rate = Decimal("0")
        tax_lines = shipping_line.get("taxLines", [])
        if tax_lines:
            tax_rate = Decimal(str(tax_lines[0].get("rate", 0))) * 100

        return {
            "method": shipping_line.get("title") or "Standard",
            "price_gross": float(price) if price else 0,
            "tax_rate": float(tax_rate),
        }

    def _calculate_totals(self, order: dict[str, Any]) -> dict[str, Any]:
        """Calculate order totals.

        Args:
            order: Shopify order data.

        Returns:
            Order totals including gross, net, and tax amounts.
        """
        total_price = self._get_shop_money_amount(order.get("totalPriceSet"))
        total_tax = self._get_shop_money_amount(order.get("totalTaxSet"))

        total_price = total_price or Decimal("0")
        total_tax = total_tax or Decimal("0")
        total_net = total_price - total_tax

        return {
            "total_gross": float(total_price),
            "total_net": float(total_net),
            "total_tax": float(total_tax),
        }

    def _get_shop_money_amount(
        self, price_set: dict[str, Any] | None
    ) -> Decimal | None:
        """Extract the shop money amount from a price set.

        Args:
            price_set: Shopify price set with shopMoney/presentmentMoney.

        Returns:
            Decimal amount from shopMoney, or None if not available.
        """
        if not price_set:
            return None

        shop_money = price_set.get("shopMoney", {})
        amount_str = shop_money.get("amount")

        if amount_str is None:
            return None

        try:
            return Decimal(str(amount_str))
        except (ValueError, TypeError):
            return None

    def _map_financial_status(self, status: str | None) -> str:
        """Map Shopify financial status to a normalized value.

        Args:
            status: Shopify displayFinancialStatus value.

        Returns:
            Normalized status string.
        """
        if not status:
            return "unknown"

        # Shopify statuses: PENDING, AUTHORIZED, PARTIALLY_PAID, PAID,
        # PARTIALLY_REFUNDED, REFUNDED, VOIDED
        status_map = {
            "PAID": "paid",
            "PARTIALLY_PAID": "partially_paid",
            "PENDING": "pending",
            "AUTHORIZED": "authorized",
            "PARTIALLY_REFUNDED": "partially_refunded",
            "REFUNDED": "refunded",
            "VOIDED": "voided",
        }

        return status_map.get(status.upper(), status.lower())
