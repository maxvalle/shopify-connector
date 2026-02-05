"""Shopify GraphQL API client with pagination, throttling, and backoff.

Implements a robust client for the Shopify Admin GraphQL API that:
- Handles cursor-based pagination automatically
- Monitors rate limit (throttling) via extensions.cost
- Implements proactive throttling when points are low
- Uses exponential backoff on 429 errors
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Generator

import requests

from src.config import Settings, get_settings
from src.logging_config import get_logger

from .queries import ORDERS_QUERY, build_orders_query_filter

logger = get_logger(__name__)


@dataclass
class ThrottleStatus:
    """Tracks the current state of Shopify's rate limiting.

    Shopify GraphQL API uses a cost-based throttling system where each query
    consumes points from a bucket that refills over time.

    Attributes:
        requested_cost: The cost that was requested for the query.
        actual_cost: The actual cost charged for the query (may differ).
        currently_available: Points currently available in the bucket.
        restore_rate: Points restored per second.
        maximum_available: Maximum bucket capacity.
    """

    requested_cost: float
    actual_cost: float
    currently_available: float
    restore_rate: float
    maximum_available: float

    @classmethod
    def from_extensions(cls, extensions: dict[str, Any]) -> "ThrottleStatus":
        """Parse throttle status from GraphQL response extensions.

        Args:
            extensions: The 'extensions' field from GraphQL response.

        Returns:
            ThrottleStatus instance with parsed values.
        """
        cost = extensions.get("cost", {})
        throttle = cost.get("throttleStatus", {})

        return cls(
            requested_cost=cost.get("requestedQueryCost", 0),
            actual_cost=cost.get("actualQueryCost", 0),
            currently_available=throttle.get("currentlyAvailable", 1000),
            restore_rate=throttle.get("restoreRate", 50),
            maximum_available=throttle.get("maximumAvailable", 1000),
        )

    def should_wait(self, next_query_cost: float = 100) -> bool:
        """Check if we should wait before the next query.

        Args:
            next_query_cost: Estimated cost of the next query. Defaults to 100
                as a safe estimate for the orders query.

        Returns:
            True if available points are below the next query cost.
        """
        return self.currently_available < next_query_cost

    def wait_time_seconds(self, next_query_cost: float = 100) -> float:
        """Calculate how long to wait for sufficient points to restore.

        Args:
            next_query_cost: Estimated cost of the next query.

        Returns:
            Number of seconds to wait, or 0 if no wait needed.
        """
        if not self.should_wait(next_query_cost):
            return 0

        points_needed = next_query_cost - self.currently_available
        # Add a small buffer (10%) to avoid edge cases
        wait_time = (points_needed / self.restore_rate) * 1.1
        return max(0, wait_time)


class ShopifyClientError(Exception):
    """Base exception for Shopify client errors."""

    pass


class ShopifyThrottledError(ShopifyClientError):
    """Raised when the API is throttled and max retries exceeded."""

    pass


class ShopifyAPIError(ShopifyClientError):
    """Raised when the Shopify API returns an error response."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


class ShopifyClient:
    """GraphQL client for Shopify Admin API with automatic throttling and pagination.

    This client provides:
    - Automatic cursor-based pagination for large result sets
    - Proactive throttling based on available query cost points
    - Exponential backoff with jitter on 429 (rate limit) errors
    - Comprehensive logging of API interactions

    Example:
        >>> client = ShopifyClient()
        >>> for order in client.fetch_orders():
        ...     print(order['name'])

        >>> # Or fetch all at once
        >>> orders = list(client.fetch_orders())
    """

    # Backoff configuration
    INITIAL_BACKOFF_SECONDS = 1.0
    MAX_BACKOFF_SECONDS = 60.0
    MAX_RETRIES = 5

    # Estimated query cost for orders query (conservative estimate)
    ESTIMATED_QUERY_COST = 100

    def __init__(self, settings: Settings | None = None):
        """Initialize the Shopify client.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.settings.shopify_api_token,
            }
        )
        self._last_throttle_status: ThrottleStatus | None = None

    def _execute_query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query with throttling and backoff handling.

        Args:
            query: The GraphQL query string.
            variables: Optional variables for the query.

        Returns:
            The 'data' field from the GraphQL response.

        Raises:
            ShopifyThrottledError: If max retries exceeded due to throttling.
            ShopifyAPIError: If the API returns errors.
            ShopifyClientError: For other request failures.
        """
        url = self.settings.shopify_graphql_url
        payload = {"query": query, "variables": variables or {}}

        retry_count = 0

        while retry_count <= self.MAX_RETRIES:
            # Proactive throttling: wait if we know points are low
            self._apply_proactive_throttle()

            try:
                logger.debug(
                    "Executing GraphQL query",
                    extra={
                        "url": url,
                        "variables": variables,
                        "retry_count": retry_count,
                    },
                )

                response = self._session.post(url, json=payload, timeout=30)

                # Handle rate limiting (429)
                if response.status_code == 429:
                    retry_count += 1
                    if retry_count > self.MAX_RETRIES:
                        raise ShopifyThrottledError(
                            f"Max retries ({self.MAX_RETRIES}) exceeded due to rate limiting"
                        )

                    backoff_time = self._calculate_backoff(retry_count)
                    logger.warning(
                        "Rate limited by Shopify API, backing off",
                        extra={
                            "retry_count": retry_count,
                            "backoff_seconds": backoff_time,
                        },
                    )
                    time.sleep(backoff_time)
                    continue

                # Raise for other HTTP errors
                response.raise_for_status()

                data = response.json()

                # Parse and store throttle status for proactive throttling
                if "extensions" in data:
                    self._last_throttle_status = ThrottleStatus.from_extensions(
                        data["extensions"]
                    )
                    logger.debug(
                        "Throttle status updated",
                        extra={
                            "available_points": self._last_throttle_status.currently_available,
                            "restore_rate": self._last_throttle_status.restore_rate,
                            "actual_cost": self._last_throttle_status.actual_cost,
                        },
                    )

                # Check for GraphQL errors in response
                if "errors" in data and data["errors"]:
                    error_messages = [
                        e.get("message", "Unknown error") for e in data["errors"]
                    ]
                    logger.error(
                        "GraphQL errors in response",
                        extra={"errors": error_messages},
                    )
                    raise ShopifyAPIError(
                        f"GraphQL errors: {'; '.join(error_messages)}",
                        errors=data["errors"],
                    )

                return data.get("data", {})

            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count > self.MAX_RETRIES:
                    raise ShopifyClientError(
                        f"Request timeout after {self.MAX_RETRIES} retries"
                    )

                backoff_time = self._calculate_backoff(retry_count)
                logger.warning(
                    "Request timeout, retrying",
                    extra={
                        "retry_count": retry_count,
                        "backoff_seconds": backoff_time,
                    },
                )
                time.sleep(backoff_time)

            except requests.exceptions.RequestException as e:
                raise ShopifyClientError(f"Request failed: {e}") from e

        # Should not reach here, but just in case
        raise ShopifyThrottledError("Unexpected exit from retry loop")

    def _calculate_backoff(self, retry_count: int) -> float:
        """Calculate exponential backoff time with jitter.

        Uses the formula: min(MAX_BACKOFF, (2^retry_count) + random(0, 1))

        Args:
            retry_count: Current retry attempt number (1-based).

        Returns:
            Number of seconds to wait before next retry.
        """
        exponential_wait = 2**retry_count
        jitter = random.uniform(0, 1)
        return min(self.MAX_BACKOFF_SECONDS, exponential_wait + jitter)

    def _apply_proactive_throttle(self) -> None:
        """Apply proactive throttling if available points are low.

        Checks the last known throttle status and waits if the available
        points are below the estimated query cost.
        """
        if self._last_throttle_status is None:
            return

        wait_time = self._last_throttle_status.wait_time_seconds(
            self.ESTIMATED_QUERY_COST
        )

        if wait_time > 0:
            logger.info(
                "Proactive throttling: waiting for rate limit points to restore",
                extra={
                    "wait_seconds": round(wait_time, 2),
                    "available_points": self._last_throttle_status.currently_available,
                    "needed_points": self.ESTIMATED_QUERY_COST,
                },
            )
            time.sleep(wait_time)

    def fetch_orders(
        self,
        days_lookback: int = 14,
    ) -> Generator[dict[str, Any], None, None]:
        """Fetch orders from Shopify with automatic pagination.

        Yields orders one at a time, handling pagination automatically.
        Only fetches paid orders that are unfulfilled or partially fulfilled.

        Args:
            days_lookback: Number of days to look back for orders. Defaults to 14.

        Yields:
            Order data dictionaries from the GraphQL response.

        Raises:
            ShopifyThrottledError: If max retries exceeded due to throttling.
            ShopifyAPIError: If the API returns errors.
            ShopifyClientError: For other request failures.

        Example:
            >>> client = ShopifyClient()
            >>> for order in client.fetch_orders(days_lookback=7):
            ...     print(f"Order {order['name']}: {order['displayFulfillmentStatus']}")
        """
        query_filter = build_orders_query_filter(days_lookback)
        cursor: str | None = None
        page_count = 0
        total_orders = 0

        logger.info(
            "Starting order fetch from Shopify",
            extra={
                "days_lookback": days_lookback,
                "query_filter": query_filter,
            },
        )

        while True:
            page_count += 1
            variables = {"cursor": cursor, "query": query_filter}

            logger.debug(
                "Fetching orders page",
                extra={"page": page_count, "cursor": cursor},
            )

            data = self._execute_query(ORDERS_QUERY, variables)
            orders_data = data.get("orders", {})

            # Process edges (orders)
            edges = orders_data.get("edges", [])
            for edge in edges:
                total_orders += 1
                yield edge.get("node", {})

            # Check pagination
            page_info = orders_data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)

            if not has_next_page:
                logger.info(
                    "Order fetch complete",
                    extra={
                        "total_pages": page_count,
                        "total_orders": total_orders,
                    },
                )
                break

            cursor = page_info.get("endCursor")
            logger.debug(
                "Moving to next page",
                extra={"next_cursor": cursor, "orders_so_far": total_orders},
            )

    def fetch_all_orders(self, days_lookback: int = 14) -> list[dict[str, Any]]:
        """Fetch all orders as a list.

        Convenience method that collects all orders from the generator
        into a list.

        Args:
            days_lookback: Number of days to look back for orders. Defaults to 14.

        Returns:
            List of all order dictionaries.
        """
        return list(self.fetch_orders(days_lookback=days_lookback))

    def close(self) -> None:
        """Close the HTTP session.

        Should be called when done using the client to free resources.
        """
        self._session.close()

    def __enter__(self) -> "ShopifyClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - closes the session."""
        self.close()
