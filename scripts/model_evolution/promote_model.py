#!/usr/bin/env python3
"""Promote a model through registry stages (staging → canary → production).

Manages model lifecycle transitions, archiving previous production versions,
and optionally triggering canary deployment.

Usage:
    # Promote to canary
    python scripts/model_evolution/promote_model.py --model slm-intent-classifier --version 3

    # Promote to production
    python scripts/model_evolution/promote_model.py --model llm-domain-generator --version 2 --to production

    # Promote latest staging version
    python scripts/model_evolution/promote_model.py --model reranker-domain --latest

    # Rollback to previous production version
    python scripts/model_evolution/promote_model.py --model slm-intent-classifier --rollback

    # List all models and versions
    python scripts/model_evolution/promote_model.py --list
    python scripts/model_evolution/promote_model.py --list --model slm-intent-classifier

    # Show current production version
    python scripts/model_evolution/promote_model.py --model slm-intent-classifier --status
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def add_package_path() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def format_version(mv) -> str:
    """Format a ModelVersion for display."""
    metric_str = ", ".join(f"{k}={v:.4f}" for k, v in sorted(mv.metrics.items())[:3])
    return f"  v{mv.version:<6s} [{mv.status:<12s}]  {metric_str}  ({mv.created_at})"


def main() -> None:
    add_package_path()

    from proxy.app.model_evolution.model_registry import ModelRegistry

    parser = argparse.ArgumentParser(
        description="Promote a model through registry stages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model name to promote/list/check",
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="Model version to promote",
    )
    parser.add_argument(
        "--latest", action="store_true",
        help="Promote the latest registered version (any status)",
    )
    parser.add_argument(
        "--to", type=str, default=None,
        choices=["staging", "canary", "production", "archived"],
        help="Target stage (default: next stage in staging→canary→production flow)",
    )
    parser.add_argument(
        "--rollback", action="store_true",
        help="Rollback to the previous production version",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all models or versions of a specific model",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current production version status",
    )
    parser.add_argument(
        "--registry-path", type=str, default=None,
        help="Path to model registry JSON (default: from MODEL_REGISTRY_PATH env)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force promotion without confirmation prompt",
    )

    args = parser.parse_args()

    try:
        registry = ModelRegistry(store_path=args.registry_path)
    except Exception as exc:
        logger.error("Failed to initialize model registry: %s", exc)
        sys.exit(1)

    if args.list:
        if args.model:
            versions = registry.list_versions(args.model)
            if not versions:
                logger.warning("No versions found for model '%s'", args.model)
            else:
                print(f"\nModel: {args.model}")
                print("-" * 80)
                for mv in versions:
                    print(format_version(mv))
                print()
        else:
            models = registry.list_models()
            if not models:
                logger.warning("No models registered")
            else:
                print("\nRegistered Models:")
                print("=" * 80)
                for model_name in models:
                    versions = registry.list_versions(model_name)
                    prod = registry.get_latest_production(model_name)
                    prod_str = f"(production: v{prod.version})" if prod else "(no production version)"
                    print(f"  {model_name}  {len(versions)} versions  {prod_str}")
                    for mv in versions:
                        print(format_version(mv))
                    print()
        return

    if not args.model:
        parser.error("--model is required unless using --list")

    if args.status:
        mv = registry.get_latest_production(args.model)
        if mv:
            print(f"\nModel: {args.model}")
            print(f"  Production:  v{mv.version}")
            print(f"  Created:     {mv.created_at}")
            print(f"  Artifact:    {mv.artifact_path}")
            if mv.metrics:
                print("  Metrics:")
                for k, v in sorted(mv.metrics.items()):
                    print(f"    {k}: {v}")
        else:
            logger.warning("No production version found for '%s'", args.model)
            latest = registry.get_latest(args.model)
            if latest:
                logger.info("Latest version is v%s (%s)", latest.version, latest.status)
        return

    if args.rollback:
        logger.info("Rolling back '%s' to previous production version...", args.model)
        if not args.force:
            response = input("Proceed with rollback? [y/N] ").strip().lower()
            if response not in ("y", "yes"):
                logger.info("Rollback cancelled")
                return
        try:
            mv = registry.rollback(args.model)
            logger.info("Rollback complete — new production: v%s (%s)", mv.version, mv.created_at)
        except (KeyError, ValueError) as exc:
            logger.error("Rollback failed: %s", exc)
            sys.exit(1)
        return

    if args.latest:
        mv = registry.get_latest(args.model)
        if mv is None:
            logger.error("No versions found for model '%s'", args.model)
            sys.exit(1)
        version = mv.version
        logger.info("Using latest version: v%s (%s)", version, mv.status)
    elif args.version:
        version = args.version
    else:
        parser.error("Either --version or --latest is required for promotion")

    try:
        mv = registry.get(args.model, version)
    except KeyError:
        logger.error("Model '%s' version '%s' not found in registry", args.model, version)
        sys.exit(1)

    if mv.status == "production" and not args.force:
        logger.info("Version v%s is already in production", mv.version)
        return

    current = mv.status
    if args.to:
        if args.to == "production" and current == "staging":
            logger.warning("Staging→production skip via explicit --to; promoting through canary first")
        # Just set the status directly for explicit --to
        logger.info("Promoting %s v%s: %s → %s", args.model, version, current, args.to)
        if not args.force:
            response = input("Proceed? [y/N] ").strip().lower()
            if response not in ("y", "yes"):
                logger.info("Promotion cancelled")
                return
    else:
        next_stage = {"staging": "canary", "canary": "production", "production": "production"}.get(current, current)
        if next_stage == current:
            logger.info("Version v%s is already at %s; nothing to promote", mv.version, current)
            return
        logger.info("Promoting %s v%s: %s → %s", args.model, version, current, next_stage)
        if not args.force:
            response = input("Proceed? [y/N] ").strip().lower()
            if response not in ("y", "yes"):
                logger.info("Promotion cancelled")
                return

    try:
        result = registry.promote(args.model, version)
        logger.info("Promoted %s v%s → %s", result.name, result.version, result.status)
    except (KeyError, ValueError) as exc:
        logger.error("Promotion failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
