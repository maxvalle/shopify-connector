"""GraphQL query definitions for Shopify Admin API.

Contains the order fetching query with all fields required for
Everstox fulfillment integration.
"""

from datetime import datetime, timedelta, timezone

# GraphQL query for fetching orders with all required fields for Everstox transformation
ORDERS_QUERY = """
query FetchOrders($cursor: String, $query: String!) {
  orders(first: 50, after: $cursor, query: $query) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        createdAt
        displayFinancialStatus
        displayFulfillmentStatus
        tags
        email
        currencyCode
        totalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        totalTaxSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        shippingLine {
          title
          originalPriceSet {
            shopMoney {
              amount
              currencyCode
            }
          }
          taxLines {
            rate
            priceSet {
              shopMoney {
                amount
              }
            }
          }
        }
        shippingAddress {
          firstName
          lastName
          company
          address1
          address2
          city
          province
          provinceCode
          country
          countryCodeV2
          zip
          phone
        }
        billingAddress {
          firstName
          lastName
          company
          address1
          address2
          city
          province
          provinceCode
          country
          countryCodeV2
          zip
          phone
        }
        lineItems(first: 100) {
          edges {
            node {
              id
              sku
              name
              quantity
              fulfillableQuantity
              originalUnitPriceSet {
                shopMoney {
                  amount
                  currencyCode
                }
              }
              discountedUnitPriceSet {
                shopMoney {
                  amount
                  currencyCode
                }
              }
              taxLines {
                rate
                priceSet {
                  shopMoney {
                    amount
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def build_orders_query_filter(days_lookback: int = 14) -> str:
    """Build the query filter string for fetching unfulfilled/partially fulfilled orders.

    Args:
        days_lookback: Number of days to look back for orders. Defaults to 14.

    Returns:
        A Shopify search query string that filters for:
        - Orders created within the lookback period
        - Paid orders only
        - Unfulfilled or partially fulfilled orders

    Example:
        >>> filter_str = build_orders_query_filter(14)
        >>> # Returns something like:
        >>> # "created_at:>=2024-01-01 AND financial_status:paid AND (fulfillment_status:unfulfilled OR fulfillment_status:partial)"
    """
    # Calculate the cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_lookback)
    date_str = cutoff_date.strftime("%Y-%m-%d")

    # Build the query filter
    # Note: Shopify query syntax for orders
    query_parts = [
        f"created_at:>={date_str}",
        "financial_status:paid",
        "(fulfillment_status:unfulfilled OR fulfillment_status:partial)",
    ]

    return " AND ".join(query_parts)
