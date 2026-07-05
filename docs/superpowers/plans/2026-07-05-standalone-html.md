# Standalone HTML Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `standalone.html` generation to `codewiki html` — a single-file HTML document with all JS libraries and markdown content inlined so it opens from `file://` with no server or network.

**Architecture:** Extend `HTMLGenerator` with `generate_standalone()` using a new `standalone_template.html` (identical to the existing template but with CDN `<script src>` tags replaced by `<script>{{JS_PLACEHOLDER}}</script>` and the `fetch()` call replaced by a `MARKDOWN_FILES` dict lookup). Vendor `.js` files ship inside the package under `codewiki/templates/vendor/`. `html_command` calls `generate_standalone()` immediately after `generate()`, reusing already-computed data.

**Tech Stack:** Python 3.10+, Click, existing `safe_read`/`safe_write` utils, pytest

## Global Constraints

- Python ≥ 3.10; no new dependencies
- Vendor JS versions must match `viewer_template.html`: `mermaid@11.9.0`, `marked@11.0.0`, `svg-pan-zoom@3.6.1`
- `standalone.html` always generated alongside `index.html` — no new CLI flags
- Template placeholders use `{{UPPER_SNAKE_CASE}}` to match existing convention
- All tests live under `tests/` and are run with `python -m pytest tests/ -v`

---

### Task 1: Download and commit vendor JS files

**Files:**
- Create: `codewiki/templates/vendor/mermaid.min.js`
- Create: `codewiki/templates/vendor/marked.min.js`
- Create: `codewiki/templates/vendor/svg-pan-zoom.min.js`

**Interfaces:**
- Produces: Three vendor JS files at `codewiki/templates/vendor/` readable by `HTMLGenerator.generate_standalone()`

- [ ] **Step 1: Create the vendor directory and download the three files**

```bash
mkdir -p codewiki/templates/vendor
curl -L "https://cdn.jsdelivr.net/npm/mermaid@11.9.0/dist/mermaid.min.js" -o codewiki/templates/vendor/mermaid.min.js
curl -L "https://cdn.jsdelivr.net/npm/marked@11.0.0/marked.min.js" -o codewiki/templates/vendor/marked.min.js
curl -L "https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js" -o codewiki/templates/vendor/svg-pan-zoom.min.js
```

- [ ] **Step 2: Verify the files are non-empty and are valid JS (not HTML error pages)**

```bash
wc -c codewiki/templates/vendor/*.js
head -c 80 codewiki/templates/vendor/mermaid.min.js
head -c 80 codewiki/templates/vendor/marked.min.js
head -c 80 codewiki/templates/vendor/svg-pan-zoom.min.js
```

Expected: mermaid ~3 MB, marked ~50 KB, svg-pan-zoom ~30 KB. Each should begin with JS (not `<!DOCTYPE html>`).

- [ ] **Step 3: Commit**

```bash
git add codewiki/templates/vendor/
git commit -m "feat: add vendor JS files for standalone HTML generation"
```

---

### Task 2: Create standalone_template.html

**Files:**
- Create: `codewiki/templates/github_pages/standalone_template.html`

**Interfaces:**
- Produces: Template with placeholders `{{MERMAID_JS}}`, `{{MARKED_JS}}`, `{{SVG_PAN_ZOOM_JS}}`, `{{MARKDOWN_FILES_JSON}}` in addition to all existing placeholders from `viewer_template.html`

- [ ] **Step 1: Copy viewer_template.html as the base**

```bash
cp codewiki/templates/github_pages/viewer_template.html \
   codewiki/templates/github_pages/standalone_template.html
```

- [ ] **Step 2: Replace the three CDN `<script src>` tags with inline placeholders**

In `standalone_template.html`, find lines 7–9:

```html
    <script src="https://cdn.jsdelivr.net/npm/mermaid@11.9.0/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked@11.0.0/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
```

Replace with:

```html
    <script>{{MERMAID_JS}}</script>
    <script>{{MARKED_JS}}</script>
    <script>{{SVG_PAN_ZOOM_JS}}</script>
```

- [ ] **Step 3: Add `MARKDOWN_FILES` constant after `DOCS_BASE_PATH` in the embedded config block**

Find this block in the `<script>` section (the embedded configuration block):

```js
        // Embedded configuration
        const CONFIG = {{CONFIG_JSON}};
        const MODULE_TREE = {{MODULE_TREE_JSON}};
        const METADATA = {{METADATA_JSON}};
        const DOCS_BASE_PATH = '{{DOCS_BASE_PATH}}';
```

Replace with:

```js
        // Embedded configuration
        const CONFIG = {{CONFIG_JSON}};
        const MODULE_TREE = {{MODULE_TREE_JSON}};
        const METADATA = {{METADATA_JSON}};
        const DOCS_BASE_PATH = '{{DOCS_BASE_PATH}}';
        const MARKDOWN_FILES = {{MARKDOWN_FILES_JSON}};
```

- [ ] **Step 4: Replace the `fetch()` block inside `loadDocument` with a dict lookup**

Find this block inside the `loadDocument` async function:

```js
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${filename}` : filename;
                const response = await fetch(docPath);
                if (!response.ok) {
                    throw new Error(`Failed to load ${filename}`);
                }
                
                const markdown = await response.text();
                const html = await renderMarkdown(markdown);
```

Replace with:

```js
                const markdown = MARKDOWN_FILES[filename];
                if (!markdown) { showError(`Document not found: ${filename}`); return; }
                const html = await renderMarkdown(markdown);
```

- [ ] **Step 5: Verify no CDN references remain and all four new placeholders are present**

```bash
grep -c "cdn.jsdelivr.net" codewiki/templates/github_pages/standalone_template.html
# Expected: 0

grep -n "MARKDOWN_FILES_JSON\|MERMAID_JS\|MARKED_JS\|SVG_PAN_ZOOM_JS" \
  codewiki/templates/github_pages/standalone_template.html
# Expected: 4 lines (one per placeholder)
```

- [ ] **Step 6: Commit**

```bash
git add codewiki/templates/github_pages/standalone_template.html
git commit -m "feat: add standalone_template.html with inlined JS and embedded markdown"
```

---

### Task 3: Add `generate_standalone()` to HTMLGenerator

**Files:**
- Modify: `codewiki/cli/html_generator.py`
- Create: `tests/__init__.py`
- Create: `tests/test_standalone_generator.py`

**Interfaces:**
- Consumes: vendor JS files from `self.vendor_dir`; `standalone_template.html` from `self.template_dir`; leaf markdown files from `input_dir`
- Produces:
  ```python
  HTMLGenerator(template_dir=None, vendor_dir=None)
  HTMLGenerator.generate_standalone(
      output_path: Path,
      title: str,
      input_dir: Path,
      leaves: List[Dict[str, Any]],
      module_tree: Optional[Dict[str, Any]] = None,
      repository_url: Optional[str] = None,
      github_pages_url: Optional[str] = None,
      config: Optional[Dict[str, Any]] = None,
      metadata: Optional[Dict[str, Any]] = None,
  ) -> None
  ```

- [ ] **Step 1: Write failing tests**

Create `tests/__init__.py` (empty file):

```python
```

Create `tests/test_standalone_generator.py`:

```python
import json
import pytest
from pathlib import Path
from codewiki.cli.html_generator import HTMLGenerator
from codewiki.cli.utils.errors import FileSystemError


@pytest.fixture
def tmp_docs(tmp_path):
    (tmp_path / "intro.md").write_text("# Introduction\nHello world.", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "details.md").write_text("# Details\nMore info.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def leaves():
    return [
        {"title": "Introduction", "file": "intro.md"},
        {"title": "Details", "file": "sub/details.md"},
    ]


@pytest.fixture
def module_tree():
    return {
        "0": {"title": "Introduction", "file": "intro.md", "components": ["_"], "children": {}},
        "1": {"title": "Details", "file": "sub/details.md", "components": ["_"], "children": {}},
    }


def test_generate_standalone_creates_file(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_generate_standalone_embeds_markdown(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    content = out.read_text(encoding="utf-8")
    assert "Hello world." in content
    assert "intro.md" in content
    assert "More info." in content
    assert "sub/details.md" in content


def test_generate_standalone_no_cdn_references(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    content = out.read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net" not in content


def test_generate_standalone_title_in_output(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="My Project Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    assert "My Project Docs" in out.read_text(encoding="utf-8")


def test_generate_standalone_missing_vendor_raises(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator(vendor_dir=tmp_path / "no_vendor_here")
    out = tmp_path / "site" / "standalone.html"
    with pytest.raises(FileSystemError, match="vendor file missing"):
        gen.generate_standalone(
            output_path=out,
            title="Test",
            input_dir=tmp_docs,
            leaves=leaves,
            module_tree=module_tree,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/asteroid/Code/CodeWiki
python -m pytest tests/test_standalone_generator.py -v 2>&1 | head -30
```

Expected: All 5 tests fail with `AttributeError: 'HTMLGenerator' object has no attribute 'generate_standalone'` or similar.

- [ ] **Step 3: Modify `__init__` to accept `vendor_dir` and add `generate_standalone()`**

In `codewiki/cli/html_generator.py`:

First, update the import line to add `List`:
```python
from typing import Optional, Dict, Any, List
```

Replace the existing `__init__` method:
```python
def __init__(self, template_dir: Optional[Path] = None, vendor_dir: Optional[Path] = None):
    if template_dir is None:
        template_dir = Path(__file__).parent.parent / "templates" / "github_pages"
    if vendor_dir is None:
        vendor_dir = Path(__file__).parent.parent / "templates" / "vendor"
    self.template_dir = Path(template_dir)
    self.vendor_dir = Path(vendor_dir)
```

Add this method to `HTMLGenerator` (after the existing `generate()` method, before `_build_info_content()`):

```python
def generate_standalone(
    self,
    output_path: Path,
    title: str,
    input_dir: Path,
    leaves: List[Dict[str, Any]],
    module_tree: Optional[Dict[str, Any]] = None,
    repository_url: Optional[str] = None,
    github_pages_url: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    if module_tree is None:
        module_tree = {}
    if config is None:
        config = {}

    def _load_vendor(filename: str) -> str:
        path = self.vendor_dir / filename
        if not path.exists():
            raise FileSystemError(
                f"Vendor file missing: {path} — reinstall the package"
            )
        return safe_read(path)

    mermaid_js = _load_vendor("mermaid.min.js")
    marked_js = _load_vendor("marked.min.js")
    svg_pan_zoom_js = _load_vendor("svg-pan-zoom.min.js")

    markdown_files: Dict[str, str] = {}
    for leaf in leaves:
        md_path = Path(input_dir) / leaf["file"]
        markdown_files[leaf["file"]] = safe_read(md_path)

    template_path = self.template_dir / "standalone_template.html"
    if not template_path.exists():
        raise FileSystemError(f"Template not found: {template_path}")
    template_content = safe_read(template_path)

    info_content = self._build_info_content(metadata)
    show_info = "block" if info_content else "none"

    repo_link = ""
    if repository_url:
        repo_link = (
            f'<a href="{repository_url}" class="repo-link" target="_blank">'
            "🔗 View Repository</a>"
        )

    html_content = template_content
    for placeholder, value in {
        "{{TITLE}}": self._escape_html(title),
        "{{REPO_LINK}}": repo_link,
        "{{SHOW_INFO}}": show_info,
        "{{INFO_CONTENT}}": info_content,
        "{{CONFIG_JSON}}": json.dumps(config, indent=2),
        "{{MODULE_TREE_JSON}}": json.dumps(module_tree, indent=2),
        "{{METADATA_JSON}}": json.dumps(metadata, indent=2) if metadata else "null",
        "{{DOCS_BASE_PATH}}": "",
        "{{MARKDOWN_FILES_JSON}}": json.dumps(markdown_files),
        "{{MERMAID_JS}}": mermaid_js,
        "{{MARKED_JS}}": marked_js,
        "{{SVG_PAN_ZOOM_JS}}": svg_pan_zoom_js,
    }.items():
        html_content = html_content.replace(placeholder, value)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write(output_path, html_content)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_standalone_generator.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add codewiki/cli/html_generator.py tests/__init__.py tests/test_standalone_generator.py
git commit -m "feat: add generate_standalone() to HTMLGenerator"
```

---

### Task 4: Wire `generate_standalone()` into html_command

**Files:**
- Modify: `codewiki/cli/commands/html.py`
- Modify: `tests/test_standalone_generator.py` (add CLI integration test)

**Interfaces:**
- Consumes: `HTMLGenerator.generate_standalone(output_path, title, input_dir, leaves, module_tree, repository_url, github_pages_url, metadata)` — exact signature from Task 3
- Produces: `output_dir/standalone.html` created as a side-effect of `codewiki html`; success log shows both output paths

- [ ] **Step 1: Write a failing integration test**

Add this test to `tests/test_standalone_generator.py`:

```python
import json
from click.testing import CliRunner
from codewiki.cli.commands.html import html_command


@pytest.fixture
def spec_and_docs(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "intro.md").write_text("# Intro\nHello.", encoding="utf-8")

    spec = {
        "language": "English",
        "sections": [{"title": "Introduction", "file": "intro.md"}],
    }
    spec_path = docs / "doc_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    dep = {"analyzed_at": "2026-07-05", "commit_id": "abc1234", "total_components": 3}
    (docs / "dependency_graph.json").write_text(json.dumps(dep), encoding="utf-8")

    return tmp_path, docs, spec_path


def test_html_command_generates_standalone(spec_and_docs):
    root, docs, spec_path = spec_and_docs
    out_dir = root / "site"

    runner = CliRunner()
    result = runner.invoke(html_command, [
        "--spec", str(spec_path),
        "--input", str(docs),
        "--output", str(out_dir),
        "--title", "Test Docs",
    ])

    assert result.exit_code == 0, result.output
    assert (out_dir / "standalone.html").exists()
    content = (out_dir / "standalone.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net" not in content
    assert "Hello." in content
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_standalone_generator.py::test_html_command_generates_standalone -v
```

Expected: FAIL — `standalone.html` does not exist.

- [ ] **Step 3: Add the `generate_standalone()` call in `html_command`**

In `codewiki/cli/commands/html.py`, find the `# --- Generate HTML ---` section (around line 282) and replace the entire block from that comment through `logger.success(...)` with:

```python
        # --- Generate HTML ---
        from codewiki.cli.html_generator import HTMLGenerator

        output_path.mkdir(parents=True, exist_ok=True)
        index_html = output_path / "index.html"
        standalone_html = output_path / "standalone.html"

        html_gen = HTMLGenerator()
        repo_info = html_gen.detect_repository_info(input_path)

        html_gen.generate(
            output_path=index_html,
            title=doc_title,
            module_tree=module_tree,
            repository_url=repo_info.get("url"),
            github_pages_url=repo_info.get("github_pages_url"),
            docs_dir=input_path,
            metadata=spec_metadata,
        )

        html_gen.generate_standalone(
            output_path=standalone_html,
            title=doc_title,
            input_dir=input_path,
            leaves=leaves,
            module_tree=module_tree,
            repository_url=repo_info.get("url"),
            github_pages_url=repo_info.get("github_pages_url"),
            metadata=spec_metadata,
        )

        logger.step("Done", 4, 4)
        logger.success(f"Generated → {index_html}")
        logger.success(f"Generated → {standalone_html}")
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python -m pytest tests/test_standalone_generator.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Smoke-test the CLI manually with real docs**

```bash
codewiki html --spec output/doc_spec.json --input output --output /tmp/cw_test
ls -lh /tmp/cw_test/
# Expected: both index.html and standalone.html present
open /tmp/cw_test/standalone.html   # should open in browser directly from file://
```

- [ ] **Step 6: Commit**

```bash
git add codewiki/cli/commands/html.py tests/test_standalone_generator.py
git commit -m "feat: always generate standalone.html alongside index.html"
```
