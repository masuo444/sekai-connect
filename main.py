#!/usr/bin/env python3
"""Connect-Nexus CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from src.database.models import Database


def _pipeline() -> "Pipeline":  # noqa: F821
    """Lazy-import Pipeline so lightweight commands (init, status) work
    even when heavy dependencies like pyyaml are not yet installed."""
    from src.pipeline import Pipeline
    return Pipeline()


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the database."""
    db = Database()
    db.init_db()
    print(f"Database initialized at {db.db_path}")
    db.close()


def cmd_collect(args: argparse.Namespace) -> None:
    """Run news collection only."""
    pipeline = _pipeline()
    pipeline.step_collect()
    pipeline.db.close()


def cmd_generate(args: argparse.Namespace) -> None:
    """Run article + visual generation."""
    pipeline = _pipeline()
    pipeline.step_generate_articles()
    pipeline.step_generate_visuals()
    pipeline.db.close()


def cmd_run(args: argparse.Namespace) -> None:
    """Run the full pipeline."""
    pipeline = _pipeline()
    pipeline.run_all()
    pipeline.db.close()


def cmd_status(args: argparse.Namespace) -> None:
    """Display database content status summary."""
    db = Database()
    db.init_db()
    summary = db.get_status_summary()

    print("\n======== Connect-Nexus Status ========\n")

    label_map = {
        "news_items": "News Items",
        "articles": "Articles",
        "visual_assets": "Visual Assets",
        "distribution_queue": "Distribution Queue",
    }

    for table, label in label_map.items():
        data = summary.get(table, {})
        total = sum(data.values())
        print(f"  {label} ({total} total)")
        if data:
            for status_name, count in sorted(data.items()):
                print(f"    - {status_name}: {count}")
        else:
            print("    (empty)")
        print()

    db.close()



def cmd_sync(args: argparse.Namespace) -> None:
    """Sync local DB to Airtable."""
    from src.database.airtable_sync import AirtableSync
    syncer = AirtableSync()
    if not syncer.enabled:
        print("Airtable sync disabled. Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID in .env")
        return
    results = syncer.sync_all()
    print("\n======== Airtable Sync Results ========\n")
    for table, count in results.items():
        print(f"  {table}: {count} records synced")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="connect-nexus",
        description="Connect-Nexus: Multi-country media pipeline",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize the database")
    sub.add_parser("collect", help="Collect news from RSS feeds")
    sub.add_parser("generate", help="Generate articles and visuals")
    sub.add_parser("run", help="Run the full pipeline")
    sub.add_parser("status", help="Show database content status")
    sub.add_parser("sync", help="Sync local DB to Airtable")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    commands = {
        "init": cmd_init,
        "collect": cmd_collect,
        "generate": cmd_generate,
        "run": cmd_run,
        "status": cmd_status,
        "sync": cmd_sync,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
