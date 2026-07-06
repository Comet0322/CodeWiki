"""
Scan command — fast filesystem walk to detect build artifacts before analysis.
No content parsing. Runs in under a second.
"""

import fnmatch
from pathlib import Path

import click

from codewiki.cli.utils.logging import create_logger
from codewiki.src.be.dependency_analyzer.languages import SUPPORTED_EXTENSIONS


# Top-level directory names that are almost always build artifacts / vendored deps
ARTIFACT_DIRS = {
    "node_modules", ".venv", "venv", "env", ".env",
    "dist", "build", "out", "output", "target",
    "vendor", "__pycache__", ".next", ".nuxt", ".cache",
    "coverage", ".gradle", ".idea", ".vs", ".eggs",
    "site-packages", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", "htmlcov",
    ".git",  # always exclude — never source code
}

# Substrings in filenames that strongly indicate generated/minified content
BUNDLE_NAME_SIGNALS = ("bundle", "chunk", "vendor", ".min.", "-min.")

# Directories that start with a dot and are typically tool data, not source
DOT_DIR_SIGNALS = {
    ".codegraph", ".gitnexus", ".superpowers", ".understand-anything",
}

LARGE_FILE_THRESHOLD = 200 * 1024  # 200 KB



def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.1f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _read_gitignore(repo_path: Path) -> list[str]:
    gi = repo_path / ".gitignore"
    if not gi.exists():
        return []
    patterns = []
    for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_gitignored(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat):
            return True
    return False


def _scan(repo_path: Path):
    """
    Returns (suggestions, file_count) where suggestions is a list of dicts:
      {pattern, size, reason, in_gitignore}
    """
    gitignore = _read_gitignore(repo_path)
    suggestions = []
    excluded_prefixes: set[Path] = set()
    file_count = 0

    # --- Pass 1: known artifact directories (top-level + dot dirs) ---
    for child in sorted(repo_path.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        is_artifact = name in ARTIFACT_DIRS or name in DOT_DIR_SIGNALS
        if is_artifact:
            size = _dir_size(child)
            in_gi = _is_gitignored(name, gitignore) or _is_gitignored(name + "/", gitignore)
            reason = "known artifact directory"
            if in_gi:
                reason += " (in .gitignore)"
            suggestions.append({
                "pattern": f"{name}/**",
                "display": f"{name}/",
                "size": size,
                "reason": reason,
                "in_gitignore": in_gi,
            })
            excluded_prefixes.add(child.resolve())

    # --- Pass 2: walk remaining files, flag large or bundle-named ones ---
    def _is_excluded(p: Path) -> bool:
        resolved = p.resolve()
        for excl in excluded_prefixes:
            try:
                resolved.relative_to(excl)
                return True
            except ValueError:
                pass
        return False

    for f in repo_path.rglob("*"):
        if not f.is_file():
            continue
        if _is_excluded(f):
            continue
        file_count += 1
        try:
            size = f.stat().st_size
        except OSError:
            continue

        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        name_lower = f.name.lower()
        is_bundle_named = any(sig in name_lower for sig in BUNDLE_NAME_SIGNALS)
        is_large = size >= LARGE_FILE_THRESHOLD

        if is_bundle_named or is_large:
            rel = str(f.relative_to(repo_path))
            in_gi = _is_gitignored(rel, gitignore) or _is_gitignored(f.name, gitignore)
            reason_parts = []
            if is_bundle_named:
                reason_parts.append("bundle/minified naming pattern")
            if is_large:
                reason_parts.append(f"large file ({_fmt_size(size)})")
            if in_gi:
                reason_parts.append("in .gitignore")
            suggestions.append({
                "pattern": rel,
                "display": rel,
                "size": size,
                "reason": ", ".join(reason_parts),
                "in_gitignore": in_gi,
            })

    return suggestions, file_count


@click.command(name="scan")
@click.option(
    "--repo", "-r",
    default=".",
    type=click.Path(exists=True),
    help="Repository path to scan (default: current directory)",
)
def scan_command(repo: str):
    """
    Scan a repository for build artifacts and large generated files.

    Fast filesystem walk — no content parsing, no LLM calls.
    Use the suggested --exclude flag with `codewiki analyze` to skip these paths.

    \b
    Examples:
      $ codewiki scan
      $ codewiki scan --repo ../my-project
    """
    logger = create_logger()
    repo_path = Path(repo).expanduser().resolve()

    click.echo(f"Scanning {repo_path.name}...")
    suggestions, file_count = _scan(repo_path)

    if not suggestions:
        logger.success(f"Scanned {file_count} files — no artifacts detected.")
        return

    # Sort: directories first (by size desc), then files (by size desc)
    dirs = sorted([s for s in suggestions if s["display"].endswith("/")], key=lambda x: -x["size"])
    files = sorted([s for s in suggestions if not s["display"].endswith("/")], key=lambda x: -x["size"])
    ordered = dirs + files

    click.echo()
    click.secho("Suggested exclusions:", bold=True)
    for s in ordered:
        size_str = _fmt_size(s["size"]).rjust(8)
        click.secho(f"  {size_str}  ", nl=False)
        click.secho(s["display"].ljust(30), fg="yellow", nl=False)
        click.echo(s["reason"])

    exclude_val = ",".join(s["pattern"] for s in ordered)
    click.echo()
    click.secho("Suggested --exclude flag:", bold=True)
    click.secho(f"  {exclude_val}", fg="cyan")
    click.echo()
    click.secho(
        f"Run: codewiki analyze --repo {repo_path} --exclude '{exclude_val}'",
        fg="blue",
    )
