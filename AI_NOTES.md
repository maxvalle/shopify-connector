# NOTES on AI use and used prompts

Created using Cursor with claude Opus 4.5

No particular problems found except some slowness sometimes.


## Base Plan
Build a small Python app that simulates a connector for Shopify:

- Fetch orders from the last 14 days via Shopify GraphQL API
- Filter to paid and not yet fully fulfilled orders
- Transform to the everstox order payload shape (JSON spec provided below).
- Prepare the POST request to `https://api.demo.everstox.com/shops/{shop_id}/` orders but do not send it.
- Provide clear logs and simple visual feedback (CLI or minimal web).
- Use Python with GraphQL for querying and `pytest` library for unit testing
- Use .env file and use `python-dotenv` library to load environment variables
- For dependencies use `requirements.txt`


## First iteration agent

1. Implement fetching orders
	- Only consider orders that are paid and not yet fully fulfilled.
	- Use GraphQL pagination.

2. Transform to everstox payload
	- Use the `everstox JSON schema` provided below
	- Derive fields from Shopify where possible, mock unknowns with explicit placeholders.

3. Logging and visual feedback
	- Use proper logging with reasonable details for development and production
	- Build a simple interface to trigger the order import and show results (e.g. minimal web page or CLI)

### everstox JSON schema

```json
{
  "shop_instance_id": "uuid",
  "order_number": "string",
  "order_date": "YYYY-MM-DDTHH:MM:SSZ",
  "customer_email": "string",
  "financial_status": "string",
  "payment_method_id": "uuid (optional)",
  "payment_method_name": "string (optional)",
  "requested_warehouse_id": "uuid (optional)",
  "requested_warehouse_name": "string (optional)",
  "requested_delivery_date": "YYYY-MM-DDTHH:MM:SSZ (optional)",
  "order_priority": "integer (optional, 1-99)",
  "picking_date": "YYYY-MM-DDTHH:MM:SSZ (optional)",
  "print_return_label": "boolean (optional, default: false)",
  "picking_hint": "string (optional)",
  "packing_hint": "string (optional)",
  "order_type": "string (optional)",
  "shipping_address": {
    "first_name": "string",
    "last_name": "string",
    "country_code": "string",
    "city": "string",
    "zip": "string",
    "address_1": "string",
    "address_2": "string (optional)",
    "company": "string (optional)",
    "phone": "string (optional)",
    "title": "string (optional)",
    "country": "string (optional)",
    "province_code": "string (optional)",
    "province": "string (optional)",
    "longitude": "number (optional)",
    "latitude": "number (optional)",
    "contact_person": "string (optional)",
    "department": "string (optional)",
    "sub_department": "string (optional)",
    "address_type": "string (optional, enum: private, business)"
  },
  "billing_address": {
    "first_name": "string",
    "last_name": "string",
    "country_code": "string",
    "city": "string",
    "zip": "string",
    "address_1": "string",
    "address_2": "string (optional)",
    "company": "string (optional)",
    "phone": "string (optional)",
    "title": "string (optional)",
    "country": "string (optional)",
    "province_code": "string (optional)",
    "province": "string (optional)",
    "longitude": "number (optional)",
    "latitude": "number (optional)",
    "VAT_number": "string (optional)",
    "contact_person": "string (optional)",
    "department": "string (optional)",
    "sub_department": "string (optional)",
    "address_type": "string (optional, enum: private, business)"
  },
  "shipping_price": {
    "currency": "string",
    "price_net_after_discount": "number",
    "tax_amount": "number",
    "tax_rate": "number",
    "price": "number",
    "tax": "number",
    "discount": "number",
    "discount_gross": "number"
  },
  "custom_attributes": [
    {
      "attribute_key": "string",
      "attribute_value": "string"
    }
  ],
  "order_items": [
    {
      "quantity": "integer (minimum: 1)",
      "product": {
        "sku": "string"
      },
      "shipment_options": [
        {
          "id": "uuid (optional)",
          "name": "string (optional)"
        }
      ],
      "price_set": [
        {
          "quantity": "integer",
          "currency": "string",
          "price_net_after_discount": "number",
          "tax_amount": "number",
          "tax_rate": "number",
          "price": "number",
          "tax": "number",
          "discount": "number",
          "discount_gross": "number"
        }
      ],
      "custom_attributes": [
        {
          "attribute_key": "string",
          "attribute_value": "string"
        }
      ],
      "requested_batch": "string (optional)",
      "requested_batch_expiration_date": "YYYY-MM-DDTHH:MM:SSZ (optional)",
      "picking_hint": "string (optional)",
      "packing_hint": "string (optional)"
    }
  ],
  "attachments": [
    {
      "attachment_type": "string",
      "url": "string (optional)",
      "content": "string (optional)",
      "file_name": "string (optional)"
    }
  ]
}
```

## Second iteration agent

1. Fetching orders
	- Use last 14 days from now window for fetching orders (possibly configurable)
	- Log and respect Shopify GraphQL throttling and cost. Suggest and implement a backoff mechanism if throttled

2. Transforming to everstox payload
	- For items, decide quantities consistent with a partial fulfillment policy (see next point)

3. Partially fulfilled orders
	- Some orders are partially fulfilled. Think about a reasonable way to deal with them and treat them accordingly. Example: fulfill what hasn't been shipped yet to prevent duplicate fulfillments (typical approach for fulfillment)

## Third iteration agent

1. Transforming to everstox payload
	- Map shipping price and taxes consistently. State assumptions if you derive net or rates from gross and tax lines.
	- Use shop currency amounts, not customer presentment currency. Suggest how you would extend to multi-currency.

2. Dry-run POST
	- Build the HTTP request to POST /shops/{shop_id}/orders but **do not execute it** only mock it

3. Priority tagging
	- Robust parsing and error handling is required as data within shopify can be messy (multiple tags, bad spelling, bad format etc.). Map an order tag to everstox `order_priority` in range 1-100.

4. Tag Blacklist and Whitelist
	- Decide how blacklist and whitelist interact. Suggest and document a possible behavior. Examples to consider:
		- Precedence if both appear.
  		- Case sensitivity.
  		- Exact vs contains vs regex.
  	- Excluded orders should be surfaced in logs and summary.
 
## Fourth iteration agent

Create a README.md file with:

- Setup and run commands
- Configuration with examples
- Documentation on strategies for partial fulfillment, blacklist/whitelist semantics and priority parsing
- Explanation for throttling backoff reasoning and any assumptions for tax and currency handling.
- Data flow
- GraphQL queries
- Dependencies
- any useful suggestion for further filtering the data