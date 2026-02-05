"""Shopify API integration module."""

from .client import ShopifyClient
from .queries import ORDERS_QUERY

__all__ = ["ShopifyClient", "ORDERS_QUERY"]
