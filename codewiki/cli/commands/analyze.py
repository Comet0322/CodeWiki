"""
Analyze command — static dependency analysis for a repository.
Outputs dependency_graph.json without any LLM calls.
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import click

from codewiki.cli.utils.logging import create_logger
from codewiki.cli.utils.repo_validator import validate_repository, get_git_commit_hash
from codewiki.cli.utils.errors import handle_error



def _build_file_tree(paths: list) -> dict:
    """Build nested directory tree from relative file paths."""
    tree: dict = {}
    for path in sorted(paths):
        parts = Path(path).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None
    return tree


def _build_enriched_index(
    components: Dict[str, Any],
    repo_path: Path,
    commit_id: Optional[str],
) -> dict:
    """Build enriched codebase index with token counts, in-degree, and structured components."""
    def count_tokens(text: str) -> int:
        return len(text) // 4

    files: Dict[str, Dict] = {}
    file_deps: Dict[str, set] = {}
    file_language: Dict[str, str] = {}

    for node in components.values():
        rel = node.relative_path
        if rel not in files:
            files[rel] = {"tokens": 0, "in_degree": 0, "classes": [], "functions": [], "depends_on": []}
            file_deps[rel] = set()
        if node.language and rel not in file_language:
            file_language[rel] = node.language

        comp_type = (node.component_type or "").lower()
        is_public = not node.name.startswith("_")
        entry: Dict[str, Any] = {"name": node.name, "public": is_public}
        if node.has_docstring and node.docstring:
            entry["docstring"] = node.docstring[:300]

        if "class" in comp_type:
            files[rel]["classes"].append(entry)
        else:
            files[rel]["functions"].append(entry)

        for dep_id in node.depends_on:
            if dep_id in components:
                dep_file = components[dep_id].relative_path
                if dep_file != rel:
                    file_deps[rel].add(dep_file)

    # Compute in-degree
    in_degree: Dict[str, int] = {p: 0 for p in files}
    for deps in file_deps.values():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1

    # Token counts from actual file content (skip files > 512KB)
    MAX_BYTES = 512 * 1024
    total_tokens = 0
    for rel_path in files:
        try:
            abs_path = repo_path / rel_path
            if abs_path.stat().st_size > MAX_BYTES:
                t = -1  # sentinel: too large to count
            else:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                t = count_tokens(content)
        except Exception:
            t = 0
        files[rel_path]["tokens"] = t
        total_tokens += t

    # Finalize per-file fields
    for rel_path in files:
        files[rel_path]["in_degree"] = in_degree.get(rel_path, 0)
        files[rel_path]["depends_on"] = sorted(file_deps.get(rel_path, set()))
        if rel_path in file_language:
            files[rel_path]["language"] = file_language[rel_path]

    return {
        "meta": {
            "repo_name": repo_path.name,
            "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "commit_id": commit_id,
            "total_files": len(files),
            "total_tokens": total_tokens,
        },
        "file_tree": _build_file_tree(list(files.keys())),
        "files": files,
    }


def _render_index_markdown(index: dict, exclude_patterns: Optional[list] = None) -> str:
    """Render codebase_index dict as compact markdown for LLM consumption."""
    meta = index["meta"]
    header = f"commit: {meta['commit_id'] or 'n/a'} | files: {meta['total_files']} | tokens: {meta['total_tokens']}"
    if exclude_patterns:
        normalised = ",".join(sorted(p.strip() for p in exclude_patterns))
        header += f" | exclude: {normalised}"
    lines = [
        f"# {meta['repo_name']} — codebase index",
        header,
        "",
    ]

    # File tree as indented block
    def _tree_lines(node: dict, prefix: str = "") -> list:
        result = []
        for name, child in node.items():
            if child is None:
                result.append(f"{prefix}{name}")
            else:
                result.append(f"{prefix}{name}/")
                result.extend(_tree_lines(child, prefix + "  "))
        return result

    lines.append("## File tree")
    lines.extend(_tree_lines(index.get("file_tree", {})))
    lines.append("")

    # Per-file sections
    for path, info in index["files"].items():
        tokens = info["tokens"] if info["tokens"] >= 0 else "large"
        meta_parts = [f"tokens: {tokens}", f"in_degree: {info['in_degree']}"]
        if info.get("language"):
            meta_parts.append(f"lang: {info['language']}")
        lines.append(f"## {path}")
        lines.append(" | ".join(meta_parts))

        if info.get("depends_on"):
            lines.append(f"depends_on: {', '.join(info['depends_on'])}")

        for cls in info.get("classes", []):
            doc = f' — "{cls["docstring"]}"' if cls.get("docstring") else ""
            private = " [private]" if not cls["public"] else ""
            lines.append(f"class {cls['name']}:{private}{doc}")

        fns = info.get("functions", [])
        if fns:
            public = [f["name"] for f in fns if f["public"]]
            private = [f["name"] for f in fns if not f["public"]]
            if public:
                lines.append(f"functions: {', '.join(public)}")
            if private:
                lines.append(f"private: {', '.join(private)}")

        lines.append("")

    return "\n".join(lines)


@click.command(name="analyze")
@click.option(
    "--repo", "-r",
    default=".",
    type=click.Path(),
    help="Repository path to analyze (default: current directory)",
)
@click.option(
    "--output", "-o",
    default=".",
    type=click.Path(),
    help="Output directory for codebase_index.md and codebase_index.json (default: current directory)",
)
@click.option(
    "--include",
    type=str,
    default=None,
    help="Comma-separated file patterns to include (e.g. '*.cs,*.py')",
)
@click.option(
    "--exclude",
    type=str,
    default=None,
    help="Comma-separated patterns to exclude (e.g. '*Tests*,test_*')",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def analyze_command(repo: str, output: str, include: Optional[str], exclude: Optional[str], verbose: bool):
    """
    Analyze a repository and output codebase_index.md and codebase_index.json.

    Performs static analysis only — no LLM calls.

    \b
    Examples:
      $ codewiki analyze
      $ codewiki analyze --repo ../my-project --output docs/
      $ codewiki analyze --exclude '*.min.js,*.bundle.js'
    """
    logger = create_logger(verbose=verbose)

    try:
        repo_path = Path(repo).expanduser().resolve()
        repo_path, languages = validate_repository(repo_path)
        logger.success(f"Repository: {repo_path.name}")
        if verbose and languages:
            logger.debug(f"Languages: {', '.join(f'{l} ({c} files)' for l, c in languages)}")

        output_dir = Path(output).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.step("Running dependency analysis...", 1, 1)

        include_patterns = [p.strip() for p in include.split(",")] if include else None
        exclude_patterns = [p.strip() for p in exclude.split(",")] if exclude else None

        with tempfile.TemporaryDirectory() as tmp:
            from codewiki.src.config import Config as BackendConfig
            from codewiki.src.be.dependency_analyzer import DependencyGraphBuilder

            agent_instructions: Dict[str, Any] = {}
            if include_patterns:
                agent_instructions["include_patterns"] = include_patterns
            if exclude_patterns:
                agent_instructions["exclude_patterns"] = exclude_patterns

            config = BackendConfig.from_cli(
                repo_path=str(repo_path),
                output_dir=tmp,
                llm_base_url="",
                llm_api_key="",
                main_model="",
                cluster_model="",
                agent_instructions=agent_instructions or None,
            )

            builder = DependencyGraphBuilder(config)
            components, _ = builder.build_dependency_graph()

        logger.success(f"Analyzed {len(components)} components across {len(set(n.relative_path for n in components.values()))} files")

        commit_id = get_git_commit_hash(repo_path) or None
        enriched = _build_enriched_index(components, repo_path, commit_id)

        md_path = output_dir / "codebase_index.md"
        md_path.write_text(_render_index_markdown(enriched, exclude_patterns), encoding="utf-8")
        logger.success(f"Saved → {md_path}")

    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        sys.exit(handle_error(e, verbose=verbose))
