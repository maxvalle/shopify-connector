# Shopify-Everstox Connector

A Python CLI tool that syncs unfulfilled orders from Shopify to Everstox fulfillment platform. Designed with robust error handling, intelligent rate limiting, and comprehensive dry-run capabilities for safe testing.

## Features

- **GraphQL API Integration**: Fetches orders using Shopify's Admin GraphQL API with automatic pagination
- **Smart Rate Limiting**: Proactive throttling based on query cost points + exponential backoff on 429 errors
- **Flexible Tag Filtering**: Whitelist/blacklist system with multiple matching modes (exact, contains, regex)
- **Partial Fulfillment Support**: Only syncs remaining unfulfilled quantities per line item
- **Priority Parsing**: Extracts order priority from tags with keyword mapping (urgent, high, normal, low)
- **Dry-Run Mode**: Prepares and validates requests without sending, with full payload inspection
- **Rich CLI Output**: Progress bars, colored tables, and detailed summaries

## Quick Start

```bash
# Clone and setup
git clone <repository-url>
cd shopify-connector
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run (dry-run mode by default)
python -m src.main
```

## Installation

### Prerequisites

- Python 3.10 or higher
- A Shopify store with Admin API access
- An Everstox account (for live mode)

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd shopify-connector
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your Shopify and Everstox credentials
   ```

## Configuration

All configuration is done through environment variables. Copy `.env.example` to `.env` and configure:

### Shopify Settings

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `SHOPIFY_SHOP_URL` | Yes | Your Shopify store URL | `mystore.myshopify.com` |
| `SHOPIFY_API_TOKEN` | Yes | Admin API access token | `shpat_xxxxx` |
| `SHOPIFY_API_VERSION` | No | API version (default: 2024-01) | `2024-01` |

### Everstox Settings

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `EVERSTOX_API_URL` | No | Everstox API base URL | `https://api.demo.everstox.com` |
| `EVERSTOX_SHOP_ID` | Yes | Your shop instance ID | `your-shop-id` |

### Tag Filtering

| Variable | Description | Example |
|----------|-------------|---------|
| `TAG_WHITELIST` | Comma-separated tags to include (empty = include all) | `vip,express,priority` |
| `TAG_BLACKLIST` | Comma-separated tags to exclude | `hold,do-not-ship,test` |
| `TAG_MATCH_MODE` | Matching mode: `exact`, `contains`, `regex` | `exact` |

### Logging

| Variable | Options | Default |
|----------|---------|---------|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `LOG_FORMAT` | `console` (colored), `json` (structured) | `console` |

### Example `.env` File

```env
# Shopify
SHOPIFY_SHOP_URL=everstox-coding-challenge.myshopify.com
SHOPIFY_API_TOKEN=shpat_your_token_here
SHOPIFY_API_VERSION=2024-01

# Everstox
EVERSTOX_API_URL=https://api.demo.everstox.com
EVERSTOX_SHOP_ID=your-shop-instance-id

# Filtering
TAG_WHITELIST=
TAG_BLACKLIST=hold,do-not-ship,test
TAG_MATCH_MODE=exact

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=console
```

## Usage

### Basic Usage (Dry-Run Mode)

```bash
python -m src.main
```

This fetches orders, filters them, transforms to Everstox format, and shows what would be sent—without actually sending anything.

### CLI Options

| Option | Short | Description |
|--------|-------|-------------|
| `--dry-run` | | Simulate without sending (default) |
| `--no-dry-run` | | Actually send orders to Everstox |
| `--verbose` | `-v` | Enable DEBUG logging |
| `--output` | `-o` | Save payloads to JSON file |
| `--days` | | Days to look back (default: 14) |
| `--show-payloads` | | Display full payload JSON |

### Examples

```bash
# Verbose mode with debug logging
python -m src.main --verbose

# Only last 7 days of orders
python -m src.main --days 7

# Save output to file for inspection
python -m src.main --output results.json

# Show full payload details
python -m src.main --show-payloads

# Actually send to Everstox (use with caution!)
python -m src.main --no-dry-run
```

### Output Format

When using `--output`, the JSON file contains:

```json
{
  "summary": {
    "total_orders": 10,
    "valid_orders": 9,
    "invalid_orders": 1,
    "total_items": 25,
    "total_value": 1234.56,
    "currencies": ["EUR"],
    "validation_issues": [...]
  },
  "payloads": [...],
  "prepared_requests": [...]
}
```

## Architecture

```
src/
├── main.py              # CLI entry point with Rich output
├── config.py            # Environment configuration (pydantic-settings)
├── logging_config.py    # Structured logging (console/JSON)
├── shopify/
│   ├── client.py        # GraphQL client with throttling
│   └── queries.py       # GraphQL query definitions
├── everstox/
│   ├── transformer.py   # Shopify → Everstox transformation
│   └── client.py        # Everstox API client (dry-run support)
└── filters/
    ├── tags.py          # Whitelist/blacklist filtering
    └── priority.py      # Priority tag parsing
```

## Design Decisions

### 1. Partial Fulfillment Strategy

**Decision**: Sync only the remaining unfulfilled quantity for each line item.

- Uses Shopify's `fulfillableQuantity` field (not calculated manually)
- Skips line items where `fulfillableQuantity <= 0`
- Skips entire orders if all line items are fully fulfilled
- Logs partial fulfillment details for transparency

**Rationale**: Everstox only needs to fulfill what hasn't been shipped yet. This prevents duplicate fulfillments and is the standard approach for fulfillment integrations.

### 2. Blacklist vs Whitelist Semantics

**Decision**: Blacklist takes precedence (deny-first model).

| Whitelist | Blacklist | Has WL Tag | Has BL Tag | Result |
|-----------|-----------|------------|------------|--------|
| Empty | Empty | - | - | **INCLUDE** |
| Empty | Configured | - | No | **INCLUDE** |
| Empty | Configured | - | Yes | **EXCLUDE** |
| Configured | Empty | Yes | - | **INCLUDE** |
| Configured | Empty | No | - | **EXCLUDE** |
| Configured | Configured | Yes | No | **INCLUDE** |
| Configured | Configured | Yes | Yes | **EXCLUDE** (BL wins) |
| Configured | Configured | No | No | **EXCLUDE** (no WL match) |

**Matching rules**:
- **Case-insensitive** comparison (Shopify tags are often inconsistent)
- Configurable via `TAG_MATCH_MODE`: `exact`, `contains`, or `regex`

### 3. Priority Tag Parsing

**Strategy**: Multi-pattern parsing with fallbacks.

1. **Numeric patterns** (case-insensitive):
   - `priority:N`, `priority-N`, `priority_N` where N is 1-99
   - `prio:N`, `prio-N`, `prio_N`

2. **Keyword mapping** if no numeric priority found:
   - `urgent`, `critical`, `asap` → 90
   - `high`, `important` → 75
   - `normal`, `standard` → 50
   - `low` → 25

3. **Default**: 50 (middle priority) if no priority tag found
4. Values are clamped to 1-99 range with warnings for out-of-range

### 4. Tax and Currency Handling

**Assumptions**:
- Uses `totalPriceSet.shopMoney` (shop currency) as the authoritative price
- Net prices calculated as: `price_net = price_gross / (1 + tax_rate/100)`
- Tax rate derived from `taxLines[0].rate`
- If tax lines are empty, assumes 0% tax rate

**Multi-currency note**: To support presentment currency, add a config flag to switch between `shopMoney` and `presentmentMoney` in the transformer.

### 5. Rate Limiting and Backoff

**Implementation**:
- Parses `extensions.cost` from each GraphQL response
- Tracks `currentlyAvailable` and `restoreRate` points
- **Proactive throttling**: Waits if available points are below query cost
- **Reactive backoff**: On 429 errors, exponential backoff with jitter

```python
# Backoff formula
sleep_time = min(60, (2 ** retry_count) + random.uniform(0, 1))
```

- Maximum 5 retries before failing
- Timeout of 30 seconds per request

### 6. Dry-Run Architecture

**Decision**: Full request preparation without execution.

The dry-run mode doesn't just skip the HTTP call—it:
- Builds complete `PreparedRequest` objects with all headers and payload
- Validates each request for required fields and data integrity
- Generates batch statistics (valid/invalid counts, total values)
- Provides `to_curl()` method for debugging

This allows complete verification of what would be sent before enabling live mode.

## Data Flow

```
┌─────────────────┐
│   Start CLI     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Load .env      │
│  Configuration  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│        SHOPIFY API LAYER            │
│  ┌─────────────────────────────┐    │
│  │ Fetch Orders (GraphQL)      │    │
│  └──────────────┬──────────────┘    │
│                 │                    │
│        ┌────────▼────────┐          │
│        │  More Pages?    │          │
│        └────────┬────────┘          │
│          Yes │  │ No                │
│              │  │                   │
│      ┌───────▼──┴───────┐          │
│      │ Check Rate Limit │          │
│      └────────┬─────────┘          │
│               │                     │
│      ┌────────▼─────────┐          │
│      │  Throttled?      │          │
│      └────────┬─────────┘          │
│        Yes │  │ No                 │
│            │  │                    │
│    ┌───────▼──┘                    │
│    │ Wait with                     │
│    │ Backoff                       │
│    └───────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ Apply Blacklist │
│ / Whitelist     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Filter Fully    │
│ Fulfilled       │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│     TRANSFORMATION LAYER            │
│  • Calculate remaining quantities   │
│  • Parse priority tags              │
│  • Map addresses                    │
│  • Calculate net prices & tax       │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ Prepare POST    │
│ Requests        │
│ (Dry-Run)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Display Results │
│ & Summary       │
└─────────────────┘
```

## GraphQL Query Structure

The connector fetches orders using this query:

```graphql
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
        totalPriceSet { shopMoney { amount currencyCode } }
        totalTaxSet { shopMoney { amount currencyCode } }
        shippingLine { 
          title
          originalPriceSet { shopMoney { amount currencyCode } }
          taxLines { rate priceSet { shopMoney { amount } } }
        }
        shippingAddress { ... }
        billingAddress { ... }
        lineItems(first: 100) {
          edges {
            node {
              sku
              quantity
              fulfillableQuantity  # Key field for partial fulfillment
              originalUnitPriceSet { shopMoney { amount currencyCode } }
              discountedUnitPriceSet { shopMoney { amount currencyCode } }
              taxLines { rate priceSet { shopMoney { amount } } }
            }
          }
        }
      }
    }
  }
}
```

**Query filter**: `created_at:>={14_days_ago} AND financial_status:paid AND (fulfillment_status:unfulfilled OR fulfillment_status:partial)`

## Development

### Running Tests

```bash
pytest
```

### Running Tests with Coverage

```bash
pytest --cov=src --cov-report=html
```

### Code Formatting

```bash
# Format code
black src/

# Check linting
ruff check src/

# Type checking
mypy src/
```

### Adding New Filters

To add a new filter type:

1. Create a new module in `src/filters/`
2. Implement the filter with a `should_include(order) -> (bool, str)` interface
3. Add it to the filter chain in `main.py`

## Troubleshooting

### Common Issues

**"Authentication failed"**
- Verify `SHOPIFY_API_TOKEN` is correct
- Ensure the token has `read_orders` scope

**"Rate limited" errors**
- The client handles this automatically with backoff
- If persistent, reduce `--days` to fetch fewer orders

**"No orders found"**
- Check the date range with `--days`
- Verify orders exist with `financial_status:paid`
- Check `TAG_WHITELIST` isn't filtering everything

**Validation errors in dry-run**
- Ensure `EVERSTOX_SHOP_ID` is configured (not placeholder)
- Verify orders have valid shipping addresses

### Debug Mode

Run with verbose logging to see detailed information:

```bash
python -m src.main --verbose
```

For JSON-formatted logs (useful for log aggregation):

```bash
LOG_FORMAT=json python -m src.main
```

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `requests` | >=2.31.0 | HTTP client |
| `python-dotenv` | >=1.0.0 | Environment loading |
| `rich` | >=13.0.0 | CLI output formatting |
| `pydantic` | >=2.0.0 | Data validation |
| `pydantic-settings` | >=2.0.0 | Settings management |
| `pytest` | >=8.0.0 | Testing (dev) |

## License

MIT
