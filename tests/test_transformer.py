"""Tests for Everstox transformer.

Tests cover:
- Partial fulfillment quantity calculation
- Address transformation
- Price and tax calculations
- Priority parsing integration
- Edge cases and error handling
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from src.everstox.transformer import EverstoxTransformer


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.everstox_shop_id = "test-shop-123"
    return settings


@pytest.fixture
def transformer(mock_settings):
    """Create transformer instance with mock settings."""
    return EverstoxTransformer(settings=mock_settings)


@pytest.fixture
def sample_order():
    """Create a sample Shopify order for testing."""
    return {
        "id": "gid://shopify/Order/123456",
        "name": "#1001",
        "createdAt": "2024-01-15T10:30:00Z",
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "currencyCode": "EUR",
        "email": "customer@example.com",
        "tags": ["vip", "priority:80"],
        "shippingAddress": {
            "firstName": "John",
            "lastName": "Doe",
            "company": "ACME Inc",
            "address1": "123 Main St",
            "address2": "Apt 4",
            "city": "Berlin",
            "provinceCode": "BE",
            "countryCodeV2": "DE",
            "zip": "10115",
            "phone": "+49123456789",
        },
        "billingAddress": {
            "firstName": "John",
            "lastName": "Doe",
            "company": "ACME Inc",
            "address1": "123 Main St",
            "address2": "",
            "city": "Berlin",
            "provinceCode": "BE",
            "countryCodeV2": "DE",
            "zip": "10115",
            "phone": "+49123456789",
        },
        "shippingLine": {
            "title": "Express Shipping",
            "originalPriceSet": {
                "shopMoney": {"amount": "9.99", "currencyCode": "EUR"}
            },
            "taxLines": [{"rate": 0.19, "priceSet": {"shopMoney": {"amount": "1.60"}}}],
        },
        "totalPriceSet": {"shopMoney": {"amount": "109.99", "currencyCode": "EUR"}},
        "totalTaxSet": {"shopMoney": {"amount": "17.56", "currencyCode": "EUR"}},
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/LineItem/1",
                        "sku": "SKU-001",
                        "name": "Product One",
                        "quantity": 2,
                        "fulfillableQuantity": 2,
                        "originalUnitPriceSet": {
                            "shopMoney": {"amount": "25.00", "currencyCode": "EUR"}
                        },
                        "discountedUnitPriceSet": {
                            "shopMoney": {"amount": "20.00", "currencyCode": "EUR"}
                        },
                        "taxLines": [
                            {"rate": 0.19, "priceSet": {"shopMoney": {"amount": "3.80"}}}
                        ],
                    }
                },
                {
                    "node": {
                        "id": "gid://shopify/LineItem/2",
                        "sku": "SKU-002",
                        "name": "Product Two",
                        "quantity": 1,
                        "fulfillableQuantity": 1,
                        "originalUnitPriceSet": {
                            "shopMoney": {"amount": "50.00", "currencyCode": "EUR"}
                        },
                        "discountedUnitPriceSet": None,
                        "taxLines": [
                            {"rate": 0.19, "priceSet": {"shopMoney": {"amount": "9.50"}}}
                        ],
                    }
                },
            ]
        },
    }


class TestEverstoxTransformerBasics:
    """Basic transformation tests."""

    def test_transform_order_number(self, transformer, sample_order):
        """Order number should be mapped from order.name."""
        payload = transformer.transform(sample_order)
        assert payload["order_number"] == "#1001"

    def test_transform_order_date(self, transformer, sample_order):
        """Order date should be mapped from order.createdAt."""
        payload = transformer.transform(sample_order)
        assert payload["order_date"] == "2024-01-15T10:30:00Z"

    def test_transform_financial_status(self, transformer, sample_order):
        """Financial status should be normalized to lowercase."""
        payload = transformer.transform(sample_order)
        assert payload["financial_status"] == "paid"

    def test_transform_currency(self, transformer, sample_order):
        """Currency should be mapped from order.currencyCode."""
        payload = transformer.transform(sample_order)
        assert payload["currency"] == "EUR"

    def test_transform_customer_email(self, transformer, sample_order):
        """Customer email should be mapped from order.email."""
        payload = transformer.transform(sample_order)
        assert payload["customer_email"] == "customer@example.com"

    def test_transform_external_id(self, transformer, sample_order):
        """External ID should be mapped from order.id."""
        payload = transformer.transform(sample_order)
        assert payload["external_id"] == "gid://shopify/Order/123456"

    def test_transform_shop_instance_id(self, transformer, sample_order):
        """Shop instance ID should come from settings."""
        payload = transformer.transform(sample_order)
        assert payload["shop_instance_id"] == "test-shop-123"


class TestEverstoxTransformerPriority:
    """Priority parsing integration tests."""

    def test_numeric_priority_parsed(self, transformer, sample_order):
        """Numeric priority tag should be parsed correctly."""
        sample_order["tags"] = ["vip", "priority:80"]
        payload = transformer.transform(sample_order)
        assert payload["order_priority"] == 80

    def test_keyword_priority_parsed(self, transformer, sample_order):
        """Keyword priority tag should be parsed correctly."""
        sample_order["tags"] = ["urgent"]
        payload = transformer.transform(sample_order)
        assert payload["order_priority"] == 90

    def test_default_priority_when_no_tag(self, transformer, sample_order):
        """Default priority should be used when no priority tag."""
        sample_order["tags"] = ["vip", "express"]
        payload = transformer.transform(sample_order)
        assert payload["order_priority"] == 50

    def test_tags_preserved_in_payload(self, transformer, sample_order):
        """Original tags should be preserved in payload."""
        sample_order["tags"] = ["vip", "priority:80", "express"]
        payload = transformer.transform(sample_order)
        assert payload["tags"] == ["vip", "priority:80", "express"]


class TestEverstoxTransformerPartialFulfillment:
    """Partial fulfillment tests."""

    def test_fulfillable_quantity_used(self, transformer, sample_order):
        """Only fulfillable quantity should be included."""
        payload = transformer.transform(sample_order)
        assert len(payload["order_items"]) == 2
        assert payload["order_items"][0]["quantity"] == 2
        assert payload["order_items"][1]["quantity"] == 1

    def test_fully_fulfilled_items_skipped(self, transformer, sample_order):
        """Items with fulfillableQuantity=0 should be skipped."""
        sample_order["lineItems"]["edges"][0]["node"]["fulfillableQuantity"] = 0
        payload = transformer.transform(sample_order)
        assert len(payload["order_items"]) == 1
        assert payload["order_items"][0]["product"]["sku"] == "SKU-002"

    def test_partially_fulfilled_order(self, transformer, sample_order):
        """Partially fulfilled orders should only include remaining quantities."""
        # First item partially fulfilled (1 of 2 remaining)
        sample_order["lineItems"]["edges"][0]["node"]["fulfillableQuantity"] = 1
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["quantity"] == 1

    def test_all_items_fulfilled_returns_empty_items(self, transformer, sample_order):
        """When all items are fulfilled, order_items should be empty."""
        for edge in sample_order["lineItems"]["edges"]:
            edge["node"]["fulfillableQuantity"] = 0
        payload = transformer.transform(sample_order)
        assert payload["order_items"] == []

    def test_has_fulfillable_items_true(self, transformer, sample_order):
        """has_fulfillable_items should return True when items remain."""
        assert transformer.has_fulfillable_items(sample_order) is True

    def test_has_fulfillable_items_false(self, transformer, sample_order):
        """has_fulfillable_items should return False when all fulfilled."""
        for edge in sample_order["lineItems"]["edges"]:
            edge["node"]["fulfillableQuantity"] = 0
        assert transformer.has_fulfillable_items(sample_order) is False


class TestEverstoxTransformerLineItems:
    """Line item transformation tests."""

    def test_sku_mapped(self, transformer, sample_order):
        """SKU should be mapped correctly."""
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["product"]["sku"] == "SKU-001"
        assert payload["order_items"][1]["product"]["sku"] == "SKU-002"

    def test_product_name_mapped(self, transformer, sample_order):
        """Product name should be mapped correctly."""
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["product"]["name"] == "Product One"
        assert payload["order_items"][1]["product"]["name"] == "Product Two"

    def test_external_id_mapped(self, transformer, sample_order):
        """External ID should be mapped from lineItem.id."""
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["external_id"] == "gid://shopify/LineItem/1"

    def test_discounted_price_preferred(self, transformer, sample_order):
        """Discounted price should be used when available."""
        payload = transformer.transform(sample_order)
        # First item has discounted price of 20.00
        assert payload["order_items"][0]["price_gross"] == 20.0

    def test_original_price_fallback(self, transformer, sample_order):
        """Original price should be used when no discount."""
        payload = transformer.transform(sample_order)
        # Second item has no discounted price, uses original 50.00
        assert payload["order_items"][1]["price_gross"] == 50.0

    def test_missing_sku_empty_string(self, transformer, sample_order):
        """Missing SKU should result in empty string."""
        sample_order["lineItems"]["edges"][0]["node"]["sku"] = None
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["product"]["sku"] == ""


class TestEverstoxTransformerPriceCalculations:
    """Price and tax calculation tests."""

    def test_tax_rate_from_tax_lines(self, transformer, sample_order):
        """Tax rate should be calculated from taxLines."""
        payload = transformer.transform(sample_order)
        # 0.19 * 100 = 19%
        assert payload["order_items"][0]["tax_rate"] == 19.0

    def test_net_price_calculated(self, transformer, sample_order):
        """Net price should be calculated from gross and tax."""
        payload = transformer.transform(sample_order)
        # price_net = price_gross / (1 + tax_rate/100)
        # price_net = 20.00 / 1.19 ≈ 16.81
        assert abs(payload["order_items"][0]["price_net"] - 16.81) < 0.01

    def test_zero_tax_rate_when_no_tax_lines(self, transformer, sample_order):
        """Tax rate should be 0 when no tax lines."""
        sample_order["lineItems"]["edges"][0]["node"]["taxLines"] = []
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["tax_rate"] == 0.0

    def test_net_equals_gross_when_no_tax(self, transformer, sample_order):
        """Net price should equal gross when no tax."""
        sample_order["lineItems"]["edges"][0]["node"]["taxLines"] = []
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["price_net"] == payload["order_items"][0]["price_gross"]


class TestEverstoxTransformerTotals:
    """Order totals calculation tests."""

    def test_total_gross(self, transformer, sample_order):
        """Total gross should be calculated from totalPriceSet."""
        payload = transformer.transform(sample_order)
        assert payload["order_totals"]["total_gross"] == 109.99

    def test_total_tax(self, transformer, sample_order):
        """Total tax should be calculated from totalTaxSet."""
        payload = transformer.transform(sample_order)
        assert payload["order_totals"]["total_tax"] == 17.56

    def test_total_net(self, transformer, sample_order):
        """Total net should be gross minus tax."""
        payload = transformer.transform(sample_order)
        expected_net = 109.99 - 17.56
        assert abs(payload["order_totals"]["total_net"] - expected_net) < 0.01


class TestEverstoxTransformerAddresses:
    """Address transformation tests."""

    def test_shipping_address_mapped(self, transformer, sample_order):
        """Shipping address should be fully mapped."""
        payload = transformer.transform(sample_order)
        addr = payload["shipping_address"]
        assert addr["first_name"] == "John"
        assert addr["last_name"] == "Doe"
        assert addr["company"] == "ACME Inc"
        assert addr["street"] == "123 Main St"
        assert addr["street_2"] == "Apt 4"
        assert addr["city"] == "Berlin"
        assert addr["state"] == "BE"
        assert addr["country_code"] == "DE"
        assert addr["postal_code"] == "10115"
        assert addr["phone"] == "+49123456789"

    def test_billing_address_mapped(self, transformer, sample_order):
        """Billing address should be fully mapped."""
        payload = transformer.transform(sample_order)
        addr = payload["billing_address"]
        assert addr["first_name"] == "John"
        assert addr["last_name"] == "Doe"

    def test_missing_address_returns_none(self, transformer, sample_order):
        """Missing address should return None."""
        sample_order["shippingAddress"] = None
        payload = transformer.transform(sample_order)
        assert payload["shipping_address"] is None

    def test_missing_address_fields_empty_string(self, transformer, sample_order):
        """Missing address fields should be empty strings."""
        sample_order["shippingAddress"]["company"] = None
        sample_order["shippingAddress"]["address2"] = None
        payload = transformer.transform(sample_order)
        assert payload["shipping_address"]["company"] == ""
        assert payload["shipping_address"]["street_2"] == ""


class TestEverstoxTransformerShipping:
    """Shipping transformation tests."""

    def test_shipping_method_mapped(self, transformer, sample_order):
        """Shipping method should be mapped from title."""
        payload = transformer.transform(sample_order)
        assert payload["shipping"]["method"] == "Express Shipping"

    def test_shipping_price_mapped(self, transformer, sample_order):
        """Shipping price should be mapped."""
        payload = transformer.transform(sample_order)
        assert payload["shipping"]["price_gross"] == 9.99

    def test_shipping_tax_rate_mapped(self, transformer, sample_order):
        """Shipping tax rate should be mapped."""
        payload = transformer.transform(sample_order)
        assert payload["shipping"]["tax_rate"] == 19.0

    def test_missing_shipping_returns_none(self, transformer, sample_order):
        """Missing shipping should return None."""
        sample_order["shippingLine"] = None
        payload = transformer.transform(sample_order)
        assert payload["shipping"] is None


class TestEverstoxTransformerFinancialStatus:
    """Financial status mapping tests."""

    @pytest.mark.parametrize(
        "shopify_status,expected",
        [
            ("PAID", "paid"),
            ("PARTIALLY_PAID", "partially_paid"),
            ("PENDING", "pending"),
            ("AUTHORIZED", "authorized"),
            ("PARTIALLY_REFUNDED", "partially_refunded"),
            ("REFUNDED", "refunded"),
            ("VOIDED", "voided"),
        ],
    )
    def test_financial_status_mapping(
        self, transformer, sample_order, shopify_status, expected
    ):
        """Financial status should be mapped to lowercase."""
        sample_order["displayFinancialStatus"] = shopify_status
        payload = transformer.transform(sample_order)
        assert payload["financial_status"] == expected

    def test_unknown_status_lowercase(self, transformer, sample_order):
        """Unknown status should be lowercased."""
        sample_order["displayFinancialStatus"] = "CUSTOM_STATUS"
        payload = transformer.transform(sample_order)
        assert payload["financial_status"] == "custom_status"

    def test_missing_status_unknown(self, transformer, sample_order):
        """Missing status should return 'unknown'."""
        sample_order["displayFinancialStatus"] = None
        payload = transformer.transform(sample_order)
        assert payload["financial_status"] == "unknown"


class TestEverstoxTransformerBatch:
    """Batch transformation tests."""

    def test_batch_transform_multiple_orders(self, transformer, sample_order):
        """Batch transform should handle multiple orders."""
        order2 = dict(sample_order)
        order2["name"] = "#1002"
        payloads = transformer.transform_batch([sample_order, order2])
        assert len(payloads) == 2
        assert payloads[0]["order_number"] == "#1001"
        assert payloads[1]["order_number"] == "#1002"

    def test_batch_transform_skips_fully_fulfilled(self, transformer, sample_order):
        """Batch transform should skip fully fulfilled orders."""
        order2 = dict(sample_order)
        order2["name"] = "#1002"
        # Make second order fully fulfilled
        order2["lineItems"] = {
            "edges": [
                {"node": {"fulfillableQuantity": 0, "sku": "SKU-003"}}
            ]
        }
        payloads = transformer.transform_batch([sample_order, order2])
        assert len(payloads) == 1
        assert payloads[0]["order_number"] == "#1001"


class TestEverstoxTransformerFulfillmentSummary:
    """Fulfillment summary tests."""

    def test_fulfillment_summary(self, transformer, sample_order):
        """Fulfillment summary should calculate correctly."""
        summary = transformer.get_fulfillment_summary(sample_order)
        assert summary["total_line_items"] == 2
        assert summary["total_ordered_quantity"] == 3  # 2 + 1
        assert summary["total_fulfillable_quantity"] == 3
        assert summary["fully_fulfilled_items"] == 0
        assert summary["is_fully_fulfilled"] is False
        assert summary["is_partially_fulfilled"] is False

    def test_fulfillment_summary_partial(self, transformer, sample_order):
        """Summary should detect partial fulfillment."""
        # First item partially fulfilled
        sample_order["lineItems"]["edges"][0]["node"]["fulfillableQuantity"] = 1
        summary = transformer.get_fulfillment_summary(sample_order)
        assert summary["total_fulfillable_quantity"] == 2  # 1 + 1
        assert summary["partially_fulfilled_items"] == 1
        assert summary["is_partially_fulfilled"] is True

    def test_fulfillment_summary_fully_fulfilled(self, transformer, sample_order):
        """Summary should detect fully fulfilled order."""
        for edge in sample_order["lineItems"]["edges"]:
            edge["node"]["fulfillableQuantity"] = 0
        summary = transformer.get_fulfillment_summary(sample_order)
        assert summary["total_fulfillable_quantity"] == 0
        assert summary["fully_fulfilled_items"] == 2
        assert summary["is_fully_fulfilled"] is True


class TestEverstoxTransformerEdgeCases:
    """Edge case tests."""

    def test_empty_line_items(self, transformer, sample_order):
        """Order with no line items should transform correctly."""
        sample_order["lineItems"] = {"edges": []}
        payload = transformer.transform(sample_order)
        assert payload["order_items"] == []

    def test_missing_line_items_key(self, transformer, sample_order):
        """Order without lineItems key should handle gracefully."""
        del sample_order["lineItems"]
        payload = transformer.transform(sample_order)
        assert payload["order_items"] == []

    def test_missing_price_sets(self, transformer, sample_order):
        """Items with missing price sets should handle gracefully."""
        sample_order["lineItems"]["edges"][0]["node"]["originalUnitPriceSet"] = None
        sample_order["lineItems"]["edges"][0]["node"]["discountedUnitPriceSet"] = None
        payload = transformer.transform(sample_order)
        assert payload["order_items"][0]["price_gross"] == 0
        assert payload["order_items"][0]["price_net"] == 0.0

    def test_empty_tags(self, transformer, sample_order):
        """Order with empty tags should use default priority."""
        sample_order["tags"] = []
        payload = transformer.transform(sample_order)
        assert payload["order_priority"] == 50
        assert payload["tags"] == []

    def test_placeholders_set(self, transformer, sample_order):
        """Placeholder fields should be set correctly."""
        payload = transformer.transform(sample_order)
        assert payload["payment_method_id"] is None
        assert payload["requested_warehouse_id"] is None
