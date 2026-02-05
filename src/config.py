"""Configuration module for Shopify-Everstox connector.

Uses pydantic-settings for environment variable loading and validation.
"""

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TagMatchMode(str, Enum):
    """Tag matching strategy for whitelist/blacklist filtering."""

    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class LogFormat(str, Enum):
    """Log output format."""

    CONSOLE = "console"
    JSON = "json"


def _parse_comma_list(value: str) -> list[str]:
    """Parse comma-separated string into list, filtering empty values."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Environment variables can be set directly or via a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Shopify configuration
    shopify_shop_url: str = Field(
        ...,
        description="Shopify shop URL (e.g., myshop.myshopify.com)",
    )
    shopify_api_token: str = Field(
        ...,
        description="Shopify Admin API access token",
    )
    shopify_api_version: str = Field(
        default="2024-01",
        description="Shopify API version",
    )

    # Everstox configuration
    everstox_api_url: str = Field(
        default="https://api.demo.everstox.com",
        description="Everstox API base URL",
    )
    everstox_shop_id: str = Field(
        default="PLACEHOLDER_SHOP_INSTANCE_ID",
        description="Everstox shop instance ID",
    )

    # Tag filtering configuration (stored as comma-separated strings)
    tag_whitelist_raw: str = Field(
        default="",
        alias="tag_whitelist",
        description="Comma-separated list of tags to include (empty = include all)",
    )
    tag_blacklist_raw: str = Field(
        default="",
        alias="tag_blacklist",
        description="Comma-separated list of tags to exclude",
    )
    tag_match_mode: TagMatchMode = Field(
        default=TagMatchMode.EXACT,
        description="Tag matching mode: exact, contains, or regex",
    )

    # Logging configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_format: LogFormat = Field(
        default=LogFormat.CONSOLE,
        description="Log output format: console or json",
    )

    @computed_field
    @property
    def tag_whitelist(self) -> list[str]:
        """Parse whitelist as list of tags."""
        return _parse_comma_list(self.tag_whitelist_raw)

    @computed_field
    @property
    def tag_blacklist(self) -> list[str]:
        """Parse blacklist as list of tags."""
        return _parse_comma_list(self.tag_blacklist_raw)

    @field_validator("shopify_shop_url", mode="after")
    @classmethod
    def normalize_shop_url(cls, v: str) -> str:
        """Normalize shop URL by removing protocol prefix if present."""
        v = v.strip()
        for prefix in ("https://", "http://"):
            if v.startswith(prefix):
                v = v[len(prefix) :]
        return v.rstrip("/")

    @property
    def shopify_graphql_url(self) -> str:
        """Construct the full Shopify GraphQL API endpoint URL."""
        return f"https://{self.shopify_shop_url}/admin/api/{self.shopify_api_version}/graphql.json"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Uses lru_cache to ensure settings are only loaded once.
    Call get_settings.cache_clear() to reload settings if needed.
    """
    return Settings()
