"""
HTML command — render markdown docs to a static HTML viewer.

Reads doc_spec.json for navigation structure, validates all markdown files
and internal links, then generates index.html via HTMLGenerator.
"""

import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import click

from codewiki.cli.utils.logging import create_logger
from codewiki.cli.utils.errors import handle_error


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def _collect_leaves(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recursively collect all leaf sections (those with a 'file' key)."""
    leaves = []
    for section in sections:
        if "file" in section:
            leaves.append(section)
        if "children" in section:
            leaves.extend(_collect_leaves(section["children"]))
    return leaves


def _spec_to_module_tree(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert doc_spec.json sections to the module_tree format expected by
    HTMLGenerator / viewer_template.html.

    Leaf nodes carry explicit 'file' and 'title' so the template JS can use
    them instead of deriving a filename from the key.
    """
    tree: Dict[str, Any] = {}
    for i, section in enumerate(sections):
        key = str(i)
        title = section.get("title", key)
        if "file" in section:
            tree[key] = {
                "title": title,
                "file": section["file"],
                "components": ["_"],  # non-empty so the template renders it as a link
                "children": {},
            }
        elif "children" in section:
            tree[key] = {
                "title": title,
                "components": [],
                "children": _spec_to_module_tree(section["children"]),
            }
    return tree


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_files(
    leaves: List[Dict[str, Any]],
    input_dir: Path,
) -> List[str]:
    """Return a list of error messages for missing markdown files."""
    errors = []
    for leaf in leaves:
        md_path = input_dir / leaf["file"]
        if not md_path.exists():
            errors.append(f"Missing file: {leaf['file']}  (expected at {md_path})")
    return errors


def _validate_links(
    leaves: List[Dict[str, Any]],
    input_dir: Path,
) -> List[str]:
    """Return error messages for broken internal .md links."""
    known_files = {leaf["file"] for leaf in leaves}
    errors = []
    link_re = re.compile(r'\[(?:[^\]]*)\]\(([^)]+\.md(?:#[^)]*)?)(?:\))', re.IGNORECASE)

    for leaf in leaves:
        md_path = input_dir / leaf["file"]
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for match in link_re.finditer(text):
            href = match.group(1).split("#")[0]
            if href.startswith("http"):
                continue
            # Resolve relative to the file's own directory
            resolved = (md_path.parent / href).resolve()
            rel = None
            try:
                rel = resolved.relative_to(input_dir.resolve()).as_posix()
            except ValueError:
                pass
            if rel and rel not in known_files:
                errors.append(f"Broken link in {leaf['file']}: [{href}] not in spec")
    return errors


async def _validate_mermaid_async(
    leaves: List[Dict[str, Any]],
    input_dir: Path,
) -> List[str]:
    """Return error messages for invalid mermaid blocks using the existing validator."""
    from codewiki.src.be.utils import validate_mermaid_diagrams

    errors = []
    for leaf in leaves:
        md_path = input_dir / leaf["file"]
        if not md_path.exists():
            continue
        result = await validate_mermaid_diagrams(str(md_path), leaf["file"])
        if result.startswith("Mermaid syntax errors"):
            errors.append(result)
    return errors


def _validate_mermaid(
    leaves: List[Dict[str, Any]],
    input_dir: Path,
) -> List[str]:
    import asyncio
    return asyncio.run(_validate_mermaid_async(leaves, input_dir))


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

@click.command(name="html")
@click.option(
    "--spec",
    required=True,
    type=click.Path(exists=True),
    help="Path to doc_spec.json",
)
@click.option(
    "--input", "-i",
    "input_dir",
    required=True,
    type=click.Path(exists=True),
    help="Directory containing the generated markdown files",
)
@click.option(
    "--output", "-o",
    default="html_docs",
    type=click.Path(),
    help="Output directory for index.html (default: ./html_docs)",
)
@click.option(
    "--title",
    default=None,
    type=str,
    help="Documentation title (default: derived from repo name)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def html_command(spec: str, input_dir: str, output: str, title: Optional[str], verbose: bool):
    """
    Generate a static HTML viewer from markdown files and doc_spec.json.

    Validates that all spec-listed markdown files exist, internal .md links
    are valid, and mermaid code blocks are non-empty before generating HTML.

    \b
    Examples:
      $ codewiki html --spec docs/doc_spec.json --input docs --output site
      $ codewiki html --spec docs/doc_spec.json --input docs --title "My Project"
    """
    logger = create_logger(verbose=verbose)

    try:
        spec_path = Path(spec).expanduser().resolve()
        input_path = Path(input_dir).expanduser().resolve()
        output_path = Path(output).expanduser().resolve()

        # --- Load spec ---
        logger.step("Loading doc_spec.json...", 1, 4)
        try:
            spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            click.secho(f"✗ Invalid JSON in spec: {e}", fg="red", err=True)
            sys.exit(1)

        sections = spec_data.get("sections", [])
        if not sections:
            click.secho("✗ doc_spec.json has no 'sections'", fg="red", err=True)
            sys.exit(1)

        leaves = _collect_leaves(sections)
        logger.success(f"Spec: {len(leaves)} documents across {len(sections)} top-level sections")

        # --- Validate ---
        logger.step("Validating markdown files and links...", 2, 4)

        all_errors: List[str] = []
        all_errors.extend(_validate_files(leaves, input_path))
        all_errors.extend(_validate_links(leaves, input_path))
        all_errors.extend(_validate_mermaid(leaves, input_path))

        if all_errors:
            click.secho(f"\n✗ {len(all_errors)} validation error(s):\n", fg="red", err=True)
            for err in all_errors:
                click.secho(f"  • {err}", fg="red", err=True)
            sys.exit(1)

        logger.success("All files and links valid")

        # --- Build navigation tree ---
        logger.step("Building HTML...", 3, 4)

        module_tree = _spec_to_module_tree(sections)

        doc_title = title
        if not doc_title:
            doc_title = spec_data.get("repo_name") or input_path.name

        # --- Generate HTML ---
        from codewiki.cli.html_generator import HTMLGenerator

        output_path.mkdir(parents=True, exist_ok=True)
        index_html = output_path / "index.html"

        html_gen = HTMLGenerator()
        repo_info = html_gen.detect_repository_info(input_path)

        html_gen.generate(
            output_path=index_html,
            title=doc_title,
            module_tree=module_tree,
            repository_url=repo_info.get("url"),
            github_pages_url=repo_info.get("github_pages_url"),
            docs_dir=input_path,
        )

        logger.step("Done", 4, 4)
        logger.success(f"Generated → {index_html}")

    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        sys.exit(handle_error(e, verbose=verbose))
