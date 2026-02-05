"""Everstox API client for order creation.

Provides a client for the Everstox API with support for:
- Dry-run mode (simulation without actual API calls)
- Order creation with prepared request introspection
- Batch processing with validation summaries
- Error handling and logging
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import requests

from src.config import Settings, get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)


class RequestStatus(str, Enum):
    """Status of a prepared request."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    SENT = "sent"
    FAILED = "failed"


class EverstoxClientError(Exception):
    """Base exception for Everstox client errors."""

    pass


class EverstoxAPIError(EverstoxClientError):
    """Raised when the Everstox API returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


@dataclass
class PreparedRequest:
    """Represents a prepared POST request for Everstox API.

    Stores all details needed to execute the request, allowing
    inspection and validation before sending (dry-run mode).

    Attributes:
        order_number: Shopify order number (e.g., "#1001")
        method: HTTP method (always "POST" for order creation)
        url: Full API endpoint URL
        headers: Request headers (excluding auth for security)
        payload: The order payload to be sent
        status: Current status of the prepared request
        validation_errors: List of validation issues found
        created_at: Timestamp when the request was prepared
        response: API response after execution (if sent)
    """

    order_number: str
    method: str
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]
    status: RequestStatus = RequestStatus.PENDING
    validation_errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response: dict[str, Any] | None = None

    def validate(self) -> bool:
        """Validate the request payload.

        Checks for required fields and data integrity.

        Returns:
            True if valid, False otherwise.
        """
        self.validation_errors.clear()

        # Required top-level fields
        required_fields = ["shop_instance_id", "order_number", "order_date"]
        for field_name in required_fields:
            if not self.payload.get(field_name):
                self.validation_errors.append(f"Missing required field: {field_name}")

        # Validate order items
        order_items = self.payload.get("order_items", [])
        if not order_items:
            self.validation_errors.append("No order items in payload")
        else:
            for i, item in enumerate(order_items):
                if not item.get("product", {}).get("sku"):
                    self.validation_errors.append(f"Item {i+1}: Missing SKU")
                if item.get("quantity", 0) <= 0:
                    self.validation_errors.append(f"Item {i+1}: Invalid quantity")

        # Validate addresses (at minimum, shipping address should exist)
        if not self.payload.get("shipping_address"):
            self.validation_errors.append("Missing shipping address")

        # Check for placeholder values that need to be replaced
        shop_id = self.payload.get("shop_instance_id", "")
        if shop_id == "PLACEHOLDER_SHOP_INSTANCE_ID":
            self.validation_errors.append(
                "shop_instance_id contains placeholder value - configure EVERSTOX_SHOP_ID"
            )

        self.status = RequestStatus.VALID if not self.validation_errors else RequestStatus.INVALID
        return not self.validation_errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all request details.
        """
        return {
            "order_number": self.order_number,
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "payload": self.payload,
            "status": self.status.value,
            "validation_errors": self.validation_errors,
            "created_at": self.created_at.isoformat(),
            "response": self.response,
        }

    def to_curl(self) -> str:
        """Generate equivalent curl command for debugging.

        Returns:
            curl command string that would execute this request.
        """
        headers_str = " ".join(f'-H "{k}: {v}"' for k, v in self.headers.items())
        payload_str = json.dumps(self.payload, indent=None, default=str)
        return f"curl -X {self.method} {headers_str} -d '{payload_str}' '{self.url}'"


@dataclass
class BatchSummary:
    """Summary of a batch of prepared requests.

    Provides statistics and validation results for multiple orders.
    """

    total_orders: int = 0
    valid_orders: int = 0
    invalid_orders: int = 0
    total_items: int = 0
    total_value: float = 0.0
    currencies: set[str] = field(default_factory=set)
    validation_issues: list[tuple[str, list[str]]] = field(default_factory=list)
    prepared_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_orders": self.total_orders,
            "valid_orders": self.valid_orders,
            "invalid_orders": self.invalid_orders,
            "total_items": self.total_items,
            "total_value": self.total_value,
            "currencies": list(self.currencies),
            "validation_issues": [
                {"order": order, "issues": issues}
                for order, issues in self.validation_issues
            ],
            "prepared_at": self.prepared_at.isoformat(),
        }


class EverstoxClient:
    """Client for Everstox order management API.

    Supports dry-run mode for testing and validation without making
    actual API calls to Everstox. In dry-run mode, requests are prepared
    and validated but not sent, allowing inspection of what would be sent.

    Example:
        >>> # Dry-run mode (default) - prepare without sending
        >>> client = EverstoxClient(dry_run=True)
        >>> prepared = client.prepare_order(payload)
        >>> print(prepared.to_curl())  # See what would be sent

        >>> # Batch preparation with validation
        >>> requests, summary = client.prepare_batch(payloads)
        >>> print(f"Valid: {summary.valid_orders}/{summary.total_orders}")

        >>> # Live mode
        >>> client = EverstoxClient(dry_run=False)
        >>> response = client.create_order(payload)  # Actually sends to API
    """

    # API endpoints
    ORDERS_ENDPOINT = "/orders"

    def __init__(
        self,
        settings: Settings | None = None,
        dry_run: bool = True,
    ):
        """Initialize the Everstox client.

        Args:
            settings: Application settings. If None, loads from environment.
            dry_run: If True, simulate API calls without sending requests.
        """
        self.settings = settings or get_settings()
        self.dry_run = dry_run
        self._session = requests.Session()
        self._prepared_requests: list[PreparedRequest] = []

        # Set up headers (auth token would be set in production)
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            # In production: "Authorization": f"Bearer {self.settings.everstox_api_token}",
        })

    def prepare_order(self, payload: dict[str, Any]) -> PreparedRequest:
        """Prepare an order creation request without sending it.

        Creates a PreparedRequest object with all details needed to
        execute the request. Validates the payload and reports any issues.

        Args:
            payload: The Everstox order payload (from transformer).

        Returns:
            PreparedRequest with request details and validation status.
        """
        order_number = payload.get("order_number", "unknown")
        url = f"{self.settings.everstox_api_url}{self.ORDERS_ENDPOINT}"

        # Create prepared request with all details
        prepared = PreparedRequest(
            order_number=order_number,
            method="POST",
            url=url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload=payload,
        )

        # Validate the request
        prepared.validate()

        logger.debug(
            "Prepared order request",
            extra={
                "order_number": order_number,
                "status": prepared.status.value,
                "validation_errors": prepared.validation_errors,
            },
        )

        self._prepared_requests.append(prepared)
        return prepared

    def prepare_batch(
        self, payloads: list[dict[str, Any]]
    ) -> tuple[list[PreparedRequest], BatchSummary]:
        """Prepare multiple order creation requests with summary.

        Prepares all payloads and generates a summary with validation
        statistics. Useful for dry-run mode to see what would be sent.

        Args:
            payloads: List of Everstox order payloads.

        Returns:
            Tuple of (prepared_requests, batch_summary).
        """
        prepared_requests: list[PreparedRequest] = []
        summary = BatchSummary()

        for payload in payloads:
            prepared = self.prepare_order(payload)
            prepared_requests.append(prepared)

            summary.total_orders += 1
            summary.total_items += len(payload.get("order_items", []))

            # Track order totals
            totals = payload.get("order_totals", {})
            summary.total_value += totals.get("total_gross", 0)
            if payload.get("currency"):
                summary.currencies.add(payload["currency"])

            if prepared.status == RequestStatus.VALID:
                summary.valid_orders += 1
            else:
                summary.invalid_orders += 1
                summary.validation_issues.append(
                    (prepared.order_number, prepared.validation_errors)
                )

        logger.info(
            "Prepared batch of orders",
            extra={
                "total": summary.total_orders,
                "valid": summary.valid_orders,
                "invalid": summary.invalid_orders,
            },
        )

        return prepared_requests, summary

    def get_prepared_requests(self) -> list[PreparedRequest]:
        """Get all prepared requests from this session.

        Returns:
            List of PreparedRequest objects.
        """
        return self._prepared_requests.copy()

    def clear_prepared_requests(self) -> None:
        """Clear all prepared requests."""
        self._prepared_requests.clear()

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an order in Everstox.

        In dry-run mode, prepares the request and returns a simulated response.
        In live mode, sends the request to the Everstox API.

        Args:
            payload: The Everstox order payload (from transformer).

        Returns:
            API response dict, or simulated response in dry-run mode.

        Raises:
            EverstoxAPIError: If the API returns an error (live mode only).
            EverstoxClientError: For network or other errors.
        """
        order_number = payload.get("order_number", "unknown")

        if self.dry_run:
            # Prepare and validate the request
            prepared = self.prepare_order(payload)

            logger.info(
                "DRY RUN: Would create order in Everstox",
                extra={
                    "order_number": order_number,
                    "items_count": len(payload.get("order_items", [])),
                    "shop_instance_id": payload.get("shop_instance_id"),
                    "status": prepared.status.value,
                    "validation_errors": prepared.validation_errors,
                },
            )

            # Return simulated response with validation info
            return {
                "success": prepared.status == RequestStatus.VALID,
                "dry_run": True,
                "order_number": order_number,
                "status": prepared.status.value,
                "validation_errors": prepared.validation_errors,
                "message": (
                    "Order would be created (dry-run mode)"
                    if prepared.status == RequestStatus.VALID
                    else f"Order has validation errors: {', '.join(prepared.validation_errors)}"
                ),
                "request_url": prepared.url,
                "items_count": len(payload.get("order_items", [])),
            }

        # Live mode - actual API call
        url = f"{self.settings.everstox_api_url}{self.ORDERS_ENDPOINT}"

        try:
            logger.info(
                "Creating order in Everstox",
                extra={"order_number": order_number, "url": url},
            )

            response = self._session.post(url, json=payload, timeout=30)

            if response.status_code >= 400:
                error_body = {}
                try:
                    error_body = response.json()
                except ValueError:
                    pass

                logger.error(
                    "Everstox API error",
                    extra={
                        "order_number": order_number,
                        "status_code": response.status_code,
                        "error": error_body,
                    },
                )

                raise EverstoxAPIError(
                    f"Failed to create order {order_number}: {response.status_code}",
                    status_code=response.status_code,
                    response_body=error_body,
                )

            response_data = response.json()

            logger.info(
                "Order created in Everstox",
                extra={
                    "order_number": order_number,
                    "everstox_id": response_data.get("id"),
                },
            )

            return response_data

        except requests.exceptions.Timeout:
            logger.error(
                "Timeout creating order in Everstox",
                extra={"order_number": order_number},
            )
            raise EverstoxClientError(f"Timeout creating order {order_number}")

        except requests.exceptions.RequestException as e:
            logger.error(
                "Request error creating order in Everstox",
                extra={"order_number": order_number, "error": str(e)},
            )
            raise EverstoxClientError(f"Request failed: {e}") from e

    def execute_prepared(self, prepared: PreparedRequest) -> dict[str, Any]:
        """Execute a previously prepared request.

        Sends the prepared request to the Everstox API.
        Only works in live mode (not dry-run).

        Args:
            prepared: A PreparedRequest to execute.

        Returns:
            API response dict.

        Raises:
            EverstoxClientError: If in dry-run mode or request fails.
            EverstoxAPIError: If the API returns an error.
        """
        if self.dry_run:
            raise EverstoxClientError(
                "Cannot execute prepared request in dry-run mode"
            )

        if prepared.status == RequestStatus.INVALID:
            raise EverstoxClientError(
                f"Cannot execute invalid request for {prepared.order_number}: "
                f"{', '.join(prepared.validation_errors)}"
            )

        try:
            response = self._session.post(
                prepared.url,
                json=prepared.payload,
                timeout=30,
            )

            if response.status_code >= 400:
                error_body = {}
                try:
                    error_body = response.json()
                except ValueError:
                    pass

                prepared.status = RequestStatus.FAILED
                prepared.response = error_body

                raise EverstoxAPIError(
                    f"Failed to create order {prepared.order_number}: {response.status_code}",
                    status_code=response.status_code,
                    response_body=error_body,
                )

            response_data = response.json()
            prepared.status = RequestStatus.SENT
            prepared.response = response_data

            return response_data

        except requests.exceptions.RequestException as e:
            prepared.status = RequestStatus.FAILED
            raise EverstoxClientError(f"Request failed: {e}") from e

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> "EverstoxClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - closes the session."""
        self.close()
