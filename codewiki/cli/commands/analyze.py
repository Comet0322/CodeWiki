"""
Analyze command — static dependency analysis for a repository.
Outputs dependency_graph.json without any LLM calls.
"""

import sys
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import click

from codewiki.cli.utils.logging import create_logger
from codewiki.cli.utils.repo_validator import validate_repository
from codewiki.cli.utils.errors import handle_error


def _build_file_graph(components: Dict[str, Any]) -> Dict[str, Any]:
    """Build a file-centric dependency map from component-level data."""
    files: Dict[str, Dict[str, Any]] = {}

    for node in components.values():
        rel = node.relative_path
        if rel not in files:
            files[rel] = {"components": [], "depends_on": []}
        files[rel]["components"].append(node.name)

    file_deps: Dict[str, set] = {p: set() for p in files}
    for node in components.values():
        src = node.relative_path
        for dep_id in node.depends_on:
            if dep_id in components:
                dep_file = components[dep_id].relative_path
                if dep_file != src:
                    file_deps[src].add(dep_file)

    for path in files:
        files[path]["depends_on"] = sorted(file_deps[path])

    return files


@click.command(name="analyze")
@click.option(
    "--repo", "-r",
    default=".",
    type=click.Path(),
    help="Repository path to analyze (default: current directory)",
)
@click.option(
    "--output", "-o",
    default="dependency_graph.json",
    type=click.Path(),
    help="Output path for dependency_graph.json (default: ./dependency_graph.json)",
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
    Analyze a repository and output a dependency_graph.json.

    Performs static analysis only — no LLM calls.

    \b
    Examples:
      $ codewiki analyze
      $ codewiki analyze --repo ../my-project --output docs/dependency_graph.json
      $ codewiki analyze --exclude '**/tests/**,**/__pycache__/**'
    """
    logger = create_logger(verbose=verbose)

    try:
        repo_path = Path(repo).expanduser().resolve()
        repo_path, languages = validate_repository(repo_path)
        logger.success(f"Repository: {repo_path.name}")
        if verbose and languages:
            logger.debug(f"Languages: {', '.join(f'{l} ({c} files)' for l, c in languages)}")

        output_path = Path(output).expanduser().resolve()
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
            components, leaf_nodes = builder.build_dependency_graph()

        files = _build_file_graph(components)
        total_files = len(files)
        logger.success(f"Analyzed {len(components)} components across {total_files} files")

        commit_id = None
        try:
            import git as gitpkg
            commit_id = gitpkg.Repo(repo_path).head.commit.hexsha
        except Exception:
            pass

        result = {
            "repo_name": repo_path.name,
            "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_files": total_files,
            "total_components": len(components),
            "commit_id": commit_id,
            "leaf_nodes": leaf_nodes,
            "files": files,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        logger.success(f"Saved → {output_path}")

    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        sys.exit(handle_error(e, verbose=verbose))
