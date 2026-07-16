#!/usr/bin/env python3
# scripts/export_openapi.py
"""
Export, validate, and document the RAG Proxy OpenAPI specification.

This script:
  1. Imports the FastAPI app from proxy.app.main
  2. Extracts the OpenAPI spec as JSON
  3. Validates the spec structure (paths, operations, schemas)
  4. Writes the spec to docs/en/api/openapi.json
  5. Generates a human-readable Markdown API reference at docs/en/api/reference.md

Usage:
    python scripts/export_openapi.py [--validate-only] [--output-dir PATH]

Exit codes:
    0 — success
    1 — spec generation or write failure
    2 — validation errors found (warnings only, non-blocking)
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so `proxy.app.main` resolves
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "en" / "api"
SPEC_FILENAME = "openapi.json"
DOCS_FILENAME = "reference.md"

# HTTP methods that represent operations
OPERATION_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


# ═══════════════════════════════════════════════════════════════════════════
# OpenAPI spec extraction
# ═══════════════════════════════════════════════════════════════════════════


def extract_openapi_spec() -> dict[str, Any]:
    """Import the FastAPI app and return its OpenAPI spec dict.

    Raises:
        ImportError: if the proxy app cannot be imported.
        RuntimeError: if the spec cannot be generated.
    """
    try:
        from proxy.app.main import app  # noqa: F811
    except ImportError as exc:
        raise ImportError(
            f"Cannot import proxy.app.main — ensure dependencies are installed.\n"
            f"  Install: pip install -r requirements-proxy.txt\n"
            f"  Error: {exc}"
        ) from exc

    try:
        spec: dict[str, Any] = app.openapi()
    except Exception as exc:
        raise RuntimeError(f"Failed to generate OpenAPI spec: {exc}") from exc

    if not isinstance(spec, dict) or "openapi" not in spec:
        raise RuntimeError("Generated spec is not a valid OpenAPI document (missing 'openapi' key)")

    return spec


# ═══════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════


class ValidationReport:
    """Collects validation issues (errors and warnings)."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines: list[str] = []
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        if not self.errors and not self.warnings:
            lines.append("All checks passed.")
        return "\n".join(lines)


def validate_spec(spec: dict[str, Any]) -> ValidationReport:
    """Run structural validation checks on an OpenAPI spec.

    Checks:
      - openapi version present
      - info.title and info.version present
      - at least one path defined
      - every path has at least one operation
      - every operation has a summary
      - every operation has at least one response
      - referenced schemas exist in components
    """
    report = ValidationReport()

    # ── Top-level ─────────────────────────────────────────────────────────
    if "openapi" not in spec:
        report.error("Missing top-level 'openapi' version field")

    info = spec.get("info", {})
    if not info.get("title"):
        report.error("Missing info.title")
    if not info.get("version"):
        report.error("Missing info.version")

    paths: dict[str, Any] = spec.get("paths", {})
    if not paths:
        report.error("No paths defined — API has zero endpoints")

    # ── Per-path / per-operation ──────────────────────────────────────────
    total_ops = 0
    ops_without_summary = 0
    ops_without_responses = 0

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            report.error(f"Path '{path}' is not a JSON object")
            continue

        has_operation = False
        for method in OPERATION_METHODS:
            op = path_item.get(method)
            if op is None:
                continue
            has_operation = True
            total_ops += 1

            if not op.get("summary") and not op.get("description"):
                ops_without_summary += 1
                report.warn(f"{method.upper()} {path} — missing summary and description")

            responses = op.get("responses", {})
            if not responses:
                ops_without_responses += 1
                report.warn(f"{method.upper()} {path} — no responses defined")

        if not has_operation:
            report.warn(f"Path '{path}' has no operations")

    if total_ops == 0:
        report.error("Spec defines paths but zero operations")

    # ── Schema references ─────────────────────────────────────────────────
    _check_schema_refs(spec, report)

    # ── Summary stats ─────────────────────────────────────────────────────
    report.warn(f"Stats: {len(paths)} paths, {total_ops} operations")
    if ops_without_summary:
        report.warn(f"{ops_without_summary}/{total_ops} operations lack summary/description")
    if ops_without_responses:
        report.warn(f"{ops_without_responses}/{total_ops} operations lack response definitions")

    return report


def _check_schema_refs(spec: dict[str, Any], report: ValidationReport) -> None:
    """Walk the spec and flag any $ref pointing to a missing component schema."""
    schemas = spec.get("components", {}).get("schemas", {})
    refs_found: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            ref = obj.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                refs_found.add(ref)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(spec)

    for ref in sorted(refs_found):
        schema_name = ref.split("/")[-1]
        if schema_name not in schemas:
            report.warn(f"$ref '{ref}' references missing schema '{schema_name}'")


# ═══════════════════════════════════════════════════════════════════════════
# Markdown documentation generator
# ═══════════════════════════════════════════════════════════════════════════


def generate_markdown_docs(spec: dict[str, Any]) -> str:
    """Generate a human-readable Markdown API reference from the OpenAPI spec.

    Organized by tags, with each endpoint showing method, path, summary,
    parameters, request body schema, and response schemas.
    """
    info = spec.get("info", {})
    paths: dict[str, Any] = spec.get("paths", {})
    tags: list[dict[str, str]] = spec.get("openapi_tags", [])
    tag_descriptions = {t["name"]: t.get("description", "") for t in tags}

    # Group operations by tag
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for path, path_item in sorted(paths.items()):
        for method in OPERATION_METHODS:
            op = path_item.get(method)
            if op is None:
                continue
            op_tags = op.get("tags", ["untagged"])
            for tag in op_tags:
                by_tag[tag].append((method.upper(), path, op))

    # Build markdown
    lines: list[str] = []
    _append = lines.append

    # Header
    _append(f"# {info.get('title', 'API Reference')}")
    _append("")
    _append(f"**Version:** {info.get('version', 'unknown')}  ")
    _append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ")  # noqa: UP017
    _append(f"**OpenAPI:** {spec.get('openapi', 'unknown')}  ")
    _append("")
    if info.get("description"):
        _append(info["description"].split("\n##")[0].strip())
        _append("")

    # Table of Contents
    _append("---")
    _append("")
    _append("## Table of Contents")
    _append("")
    for tag_name in sorted(by_tag.keys()):
        desc = tag_descriptions.get(tag_name, "")
        anchor = tag_name.lower().replace(" ", "-")
        _append(f"- [{tag_name}](#{anchor}) — {desc}" if desc else f"- [{tag_name}](#{anchor})")
    _append("")
    _append("---")
    _append("")

    # Per-tag sections
    for tag_name in sorted(by_tag.keys()):
        desc = tag_descriptions.get(tag_name, "")
        _append(f"## {tag_name.title()}")
        if desc:
            _append(f"_{desc}_")
            _append("")

        for method, path, op in by_tag[tag_name]:
            summary = op.get("summary", "")
            description = op.get("description", "")
            operation_id = op.get("operationId", "")

            _append(f"### `{method} {path}`")
            if summary:
                _append(f"**{summary}**")
                _append("")
            if description:
                # Truncate long descriptions to first paragraph
                first_para = description.split("\n\n")[0].strip()
                _append(first_para)
                _append("")

            # Parameters
            params = op.get("parameters", [])
            if params:
                _append("#### Parameters")
                _append("")
                _append("| Name | In | Type | Required | Description |")
                _append("|------|----|------|----------|-------------|")
                for p in params:
                    name = p.get("name", "")
                    loc = p.get("in", "")
                    required = "✓" if p.get("required") else ""
                    schema = p.get("schema", {})
                    ptype = schema.get("type", "any")
                    pdesc = p.get("description", "")
                    _append(f"| `{name}` | {loc} | `{ptype}` | {required} | {pdesc} |")
                _append("")

            # Request body
            req_body = op.get("requestBody", {})
            if req_body:
                _append("#### Request Body")
                _append("")
                content = req_body.get("content", {})
                json_content = content.get("application/json", {})
                schema = json_content.get("schema", {})
                if schema:
                    _append(_schema_to_table(schema, spec))
                    _append("")

            # Responses
            responses = op.get("responses", {})
            if responses:
                _append("#### Responses")
                _append("")
                for status_code, resp in sorted(responses.items()):
                    desc = resp.get("description", "")
                    _append(f"**`{status_code}`** — {desc}")
                    _append("")
                    resp_content = resp.get("content", {})
                    json_resp = resp_content.get("application/json", {})
                    resp_schema = json_resp.get("schema", {})
                    if resp_schema:
                        _append(_schema_to_table(resp_schema, spec))
                        _append("")

            # Tags / operationId
            op_tags = op.get("tags", [])
            if operation_id:
                _append(f"_operationId: `{operation_id}`_")
                _append("")

            _append("---")
            _append("")

    # Schemas appendix
    schemas = spec.get("components", {}).get("schemas", {})
    if schemas:
        _append("## Schemas")
        _append("")
        for schema_name in sorted(schemas.keys()):
            schema = schemas[schema_name]
            _append(f"### `{schema_name}`")
            if schema.get("description"):
                _append(schema["description"])
                _append("")
            _append(_schema_to_table(schema, spec))
            _append("")

    return "\n".join(lines)


def _schema_to_table(schema: dict[str, Any], full_spec: dict[str, Any]) -> str:
    """Convert a JSON Schema object to a Markdown table.

    Handles $ref resolution, nested objects (one level), and arrays.
    """
    # Resolve $ref
    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], full_spec)

    # Inline enum / const
    if schema.get("enum"):
        return f"Enum: `{'`, `'.join(str(e) for e in schema['enum'])}`"

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        # Primitive or array — just describe it
        parts = [f"Type: `{schema_type}`"]
        if schema.get("format"):
            parts.append(f"Format: `{schema['format']}`")
        if schema.get("description"):
            parts.append(schema["description"])
        return " — ".join(parts)

    properties: dict[str, Any] = schema.get("properties", {})
    required_set: set[str] = set(schema.get("required", []))

    if not properties:
        return "_No properties defined._"

    lines: list[str] = []
    lines.append("| Field | Type | Required | Description |")
    lines.append("|-------|------|----------|-------------|")

    for prop_name, prop_schema in properties.items():
        resolved = prop_schema
        if "$ref" in resolved:
            resolved = _resolve_ref(resolved["$ref"], full_spec)

        ptype = resolved.get("type", "any")
        if ptype == "array" and "items" in resolved:
            items = resolved["items"]
            item_type = items["$ref"].split("/")[-1] if "$ref" in items else items.get("type", "any")
            ptype = f"array[{item_type}]"

        format_str = resolved.get("format", "")
        if format_str:
            ptype = f"{ptype} ({format_str})"

        required = "✓" if prop_name in required_set else ""
        desc = resolved.get("description", "")
        lines.append(f"| `{prop_name}` | `{ptype}` | {required} | {desc} |")

    return "\n".join(lines)


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a $ref like '#/components/schemas/Foo' to its schema dict."""
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, {})
        else:
            return {}
    return node if isinstance(node, dict) else {}


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export, validate, and document the RAG Proxy OpenAPI specification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/export_openapi.py
              python scripts/export_openapi.py --validate-only
              python scripts/export_openapi.py --output-dir ./api-docs
        """),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the spec; do not write files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for generated files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--skip-docs",
        action="store_true",
        help="Skip Markdown documentation generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # ── 1. Extract spec ───────────────────────────────────────────────────
    print("Extracting OpenAPI spec from FastAPI app...")
    try:
        spec = extract_openapi_spec()
    except (ImportError, RuntimeError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    info = spec.get("info", {})
    paths = spec.get("paths", {})
    total_ops = sum(1 for p in paths.values() if isinstance(p, dict) for m in OPERATION_METHODS if p.get(m) is not None)
    print(f"  → OpenAPI {spec.get('openapi')}")
    print(f"  → {info.get('title')} v{info.get('version')}")
    print(f"  → {len(paths)} paths, {total_ops} operations")

    # ── 2. Validate ──────────────────────────────────────────────────────
    print("\nValidating spec...")
    report = validate_spec(spec)
    print(report.summary())

    if args.validate_only:
        return 0 if report.ok else 2

    # ── 3. Write spec JSON ────────────────────────────────────────────────
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    spec_path = output_dir / SPEC_FILENAME
    print(f"\nWriting OpenAPI spec to {spec_path.relative_to(PROJECT_ROOT)}...")
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  → {spec_path.stat().st_size:,} bytes written")

    # ── 4. Generate Markdown docs ─────────────────────────────────────────
    if not args.skip_docs:
        docs_path = output_dir / DOCS_FILENAME
        print(f"Generating API reference to {docs_path.relative_to(PROJECT_ROOT)}...")
        markdown = generate_markdown_docs(spec)
        docs_path.write_text(markdown, encoding="utf-8")
        print(f"  → {len(markdown):,} chars, {markdown.count(chr(10))} lines written")

    # ── 5. Summary ────────────────────────────────────────────────────────
    print("\nDone.")
    print(f"  Spec:  {spec_path.resolve()}")
    if not args.skip_docs:
        print(f"  Docs:  {(output_dir / DOCS_FILENAME).resolve()}")
    if report.warnings:
        print(f"  Warnings: {len(report.warnings)} (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
