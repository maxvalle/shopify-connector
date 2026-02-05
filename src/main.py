"""CLI entry point for Shopify-Everstox connector.

Provides a command-line interface to:
- Fetch orders from Shopify with progress display
- Filter orders based on tag whitelist/blacklist
- Transform orders to Everstox payload format
- Display rich tables and summaries
- Output results (dry-run mode by default)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from src.config import get_settings
from src.logging_config import setup_logging, get_logger
from src.shopify import ShopifyClient
from src.everstox import EverstoxTransformer, EverstoxClient, BatchSummary
from src.filters import TagFilter, PriorityParser


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Sync unfulfilled Shopify orders to Everstox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main                    # Basic run (dry-run by default)
  python -m src.main --verbose          # With debug logging
  python -m src.main --output results.json  # Save payloads to file
  python -m src.main --days 7           # Only last 7 days of orders
  python -m src.main --no-dry-run       # Actually send to Everstox (use with caution)
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate API calls without sending to Everstox (default: True)",
    )

    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually send orders to Everstox (use with caution)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output file for transformed payloads (JSON)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Number of days to look back for orders (default: 14)",
    )

    parser.add_argument(
        "--show-payloads",
        action="store_true",
        help="Show full payload JSON for each order",
    )

    return parser.parse_args()


def create_progress() -> Progress:
    """Create a Rich progress bar for order fetching.

    Returns:
        Configured Progress instance.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=Console(stderr=True),
    )


def display_filter_summary(
    console: Console,
    total_fetched: int,
    included_orders: list[dict],
    excluded_orders: list[tuple[dict, str]],
) -> None:
    """Display a summary of order filtering.

    Args:
        console: Rich console for output.
        total_fetched: Total number of orders fetched from Shopify.
        included_orders: List of orders that passed filtering.
        excluded_orders: List of (order, reason) tuples for excluded orders.
    """
    console.print()

    # Statistics panel
    stats_text = Text()
    stats_text.append("Total fetched: ", style="dim")
    stats_text.append(f"{total_fetched}\n", style="bold")
    stats_text.append("Included for sync: ", style="dim")
    stats_text.append(f"{len(included_orders)}\n", style="bold green")
    stats_text.append("Excluded: ", style="dim")
    stats_text.append(f"{len(excluded_orders)}", style="bold yellow")

    console.print(Panel(stats_text, title="[bold]Filtering Results[/bold]", border_style="blue"))

    # Excluded orders summary (collapsed)
    if excluded_orders:
        console.print()
        exclusion_reasons: dict[str, int] = {}
        for _, reason in excluded_orders:
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

        exclusion_table = Table(title="Exclusion Reasons", show_header=True, header_style="bold yellow")
        exclusion_table.add_column("Reason", style="yellow")
        exclusion_table.add_column("Count", justify="right")

        for reason, count in sorted(exclusion_reasons.items(), key=lambda x: -x[1]):
            exclusion_table.add_row(reason, str(count))

        console.print(exclusion_table)


def display_orders_table(
    console: Console,
    included_orders: list[dict],
    transformer: EverstoxTransformer,
) -> None:
    """Display detailed table of orders to sync.

    Args:
        console: Rich console for output.
        included_orders: List of orders that passed filtering.
        transformer: Transformer for getting fulfillment summaries.
    """
    if not included_orders:
        console.print("[yellow]No orders to sync.[/yellow]")
        return

    console.print()
    table = Table(title="[bold]Orders to Sync[/bold]", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Order", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")
    table.add_column("Items", justify="right")
    table.add_column("Fulfillable", justify="right")
    table.add_column("Priority", justify="center")
    table.add_column("Tags", max_width=30)

    for idx, order in enumerate(included_orders, 1):
        priority = PriorityParser.parse(order.get("tags", []))
        fulfillment = transformer.get_fulfillment_summary(order)

        # Format priority with color based on value
        priority_style = "dim"
        if priority >= 75:
            priority_style = "bold red"
        elif priority >= 50:
            priority_style = "yellow"

        # Format fulfillment status
        fulfillable = fulfillment["total_fulfillable_quantity"]
        total = fulfillment["total_ordered_quantity"]
        if fulfillable < total:
            fulfillable_str = f"[yellow]{fulfillable}/{total}[/yellow]"
        else:
            fulfillable_str = str(fulfillable)

        # Format tags
        tags = order.get("tags", [])
        tags_str = ", ".join(tags[:2])
        if len(tags) > 2:
            tags_str += f" (+{len(tags) - 2})"

        table.add_row(
            str(idx),
            order.get("name", "N/A"),
            order.get("displayFulfillmentStatus", "N/A"),
            str(fulfillment["total_line_items"]),
            fulfillable_str,
            Text(str(priority), style=priority_style),
            tags_str,
        )

    console.print(table)


def display_batch_summary(
    console: Console,
    summary: BatchSummary,
    dry_run: bool,
) -> None:
    """Display batch processing summary.

    Args:
        console: Rich console for output.
        summary: Batch processing summary from Everstox client.
        dry_run: Whether this was a dry-run.
    """
    console.print()

    mode_text = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"

    summary_text = Text()
    summary_text.append(f"Mode: {mode_text}\n\n", style="bold")
    summary_text.append("Orders Prepared: ", style="dim")
    summary_text.append(f"{summary.total_orders}\n", style="bold")
    summary_text.append("  Valid: ", style="dim")
    summary_text.append(f"{summary.valid_orders}\n", style="bold green")
    summary_text.append("  Invalid: ", style="dim")
    summary_text.append(f"{summary.invalid_orders}\n", style="bold red" if summary.invalid_orders else "dim")
    summary_text.append("\nTotal Items: ", style="dim")
    summary_text.append(f"{summary.total_items}\n", style="bold")
    summary_text.append("Total Value: ", style="dim")

    currencies = list(summary.currencies)
    currency = currencies[0] if currencies else "EUR"
    summary_text.append(f"{summary.total_value:,.2f} {currency}", style="bold")

    console.print(Panel(
        summary_text,
        title="[bold]Batch Summary[/bold]",
        border_style="green" if not summary.invalid_orders else "yellow"
    ))

    # Show validation issues if any
    if summary.validation_issues:
        console.print()
        console.print("[bold red]Validation Issues:[/bold red]")
        for order_num, issues in summary.validation_issues[:5]:
            console.print(f"  [cyan]{order_num}[/cyan]:")
            for issue in issues:
                console.print(f"    - {issue}", style="red")
        if len(summary.validation_issues) > 5:
            console.print(f"  ... and {len(summary.validation_issues) - 5} more orders with issues")


def fetch_orders_with_progress(
    console: Console,
    shopify_client: ShopifyClient,
    days: int,
) -> list[dict]:
    """Fetch orders from Shopify with a progress display.

    Args:
        console: Rich console for output.
        shopify_client: Initialized Shopify client.
        days: Number of days to look back.

    Returns:
        List of fetched orders.
    """
    orders: list[dict] = []

    with create_progress() as progress:
        task = progress.add_task(
            f"Fetching orders (last {days} days)",
            total=None,  # Unknown total
        )

        for order in shopify_client.fetch_orders(days_lookback=days):
            orders.append(order)
            progress.update(task, advance=1, description=f"Fetched {len(orders)} orders")

        progress.update(task, description=f"[green]Complete: {len(orders)} orders[/green]")

    return orders


def filter_orders(
    orders: list[dict],
    tag_filter: TagFilter,
    transformer: EverstoxTransformer,
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Filter orders based on tags and fulfillment status.

    Args:
        orders: Raw orders from Shopify.
        tag_filter: Configured tag filter.
        transformer: Transformer for fulfillment checks.

    Returns:
        Tuple of (included_orders, excluded_orders with reasons).
    """
    included: list[dict] = []
    excluded: list[tuple[dict, str]] = []

    for order in orders:
        tags = order.get("tags", [])
        is_included, reason = tag_filter.should_include(tags)

        if not is_included:
            excluded.append((order, reason))
            continue

        # Check fulfillment status
        if not transformer.has_fulfillable_items(order):
            excluded.append((order, "No fulfillable items remaining"))
            continue

        included.append(order)

    return included, excluded


def main() -> int:
    """Main entry point for the CLI.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = parse_args()
    console = Console()

    # Handle dry-run flag logic
    dry_run = not args.no_dry_run

    # Setup logging
    log_level = "DEBUG" if args.verbose else None
    logger = setup_logging(log_level=log_level)

    try:
        settings = get_settings()

        # Print banner
        console.print()
        console.print(Panel(
            "[bold]Shopify → Everstox Order Sync[/bold]\n"
            f"Mode: {'[yellow]DRY RUN[/yellow]' if dry_run else '[green]LIVE[/green]'}",
            border_style="blue",
        ))
        console.print()

        logger.info("Starting Shopify-Everstox sync", extra={"dry_run": dry_run})

        # Initialize components
        tag_filter = TagFilter(
            whitelist=settings.tag_whitelist,
            blacklist=settings.tag_blacklist,
            match_mode=settings.tag_match_mode,
        )
        transformer = EverstoxTransformer(settings)
        everstox_client = EverstoxClient(settings, dry_run=dry_run)

        # Fetch orders from Shopify with progress
        with ShopifyClient(settings) as shopify_client:
            raw_orders = fetch_orders_with_progress(console, shopify_client, args.days)

        logger.info(f"Fetched {len(raw_orders)} orders from Shopify")

        # Filter orders
        console.print()
        console.print("[bold]Filtering orders...[/bold]")
        included_orders, excluded_orders = filter_orders(
            raw_orders, tag_filter, transformer
        )

        # Display filtering results
        display_filter_summary(console, len(raw_orders), included_orders, excluded_orders)

        if not included_orders:
            console.print("\n[yellow]No orders to sync after filtering.[/yellow]")
            return 0

        # Display orders table
        display_orders_table(console, included_orders, transformer)

        # Transform to Everstox payloads
        console.print()
        console.print("[bold]Transforming orders to Everstox format...[/bold]")

        payloads = transformer.transform_batch(included_orders)

        # Prepare batch and get summary
        prepared_requests, batch_summary = everstox_client.prepare_batch(payloads)

        # Display batch summary
        display_batch_summary(console, batch_summary, dry_run)

        # Output payloads to file if requested
        if args.output:
            output_data = {
                "summary": batch_summary.to_dict(),
                "payloads": payloads,
                "prepared_requests": [r.to_dict() for r in prepared_requests],
            }
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2, default=str)
            console.print(f"\n[green]Output saved to {args.output}[/green]")

        # Show sample payload if verbose
        if args.show_payloads and payloads:
            console.print()
            console.print("[bold]Sample Payload:[/bold]")
            console.print_json(json.dumps(payloads[0], default=str, indent=2))

        # Show curl command for first order (helpful for debugging)
        if args.verbose and prepared_requests:
            console.print()
            console.print("[bold]Sample curl command:[/bold]")
            console.print(f"[dim]{prepared_requests[0].to_curl()[:200]}...[/dim]")

        # Process orders (dry-run just logs, live would send)
        if not dry_run and batch_summary.valid_orders > 0:
            console.print()
            console.print("[bold red]LIVE MODE: Sending orders to Everstox...[/bold red]")
            # In production, you would iterate and call execute_prepared here
            console.print("[yellow]Live execution not yet implemented[/yellow]")

        logger.info(
            "Sync complete",
            extra={
                "orders_processed": len(included_orders),
                "orders_excluded": len(excluded_orders),
                "valid_payloads": batch_summary.valid_orders,
                "invalid_payloads": batch_summary.invalid_orders,
                "dry_run": dry_run,
            },
        )

        # Print final status
        console.print()
        if dry_run:
            console.print("[bold green]✓[/bold green] Dry run completed successfully.")
            console.print("[dim]Run with --no-dry-run to send orders to Everstox.[/dim]")
        else:
            console.print("[bold green]✓[/bold green] Sync completed.")

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        return 130

    except Exception as e:
        logger.exception("Error during sync")
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if args.verbose:
            console.print_exception()
        return 1


if __name__ == "__main__":
    sys.exit(main())
