# Standalone HTML Generation

**Date:** 2026-07-05
**Status:** Approved

## Problem

`codewiki html` generates `index.html` that loads JS libraries from CDN and fetches
markdown files via `fetch()` at runtime. This requires a web server and internet access
to use. Users need a single-file version they can open directly in a browser.

## Goal

Always generate `standalone.html` alongside `index.html`. It must open from the local
filesystem (`file://`) with no server and no network access.

## Approach

Extend `HTMLGenerator` with a `generate_standalone()` method that uses a new
`standalone_template.html`. Vendor JS files ship inside the Python package.

## File Layout

```
codewiki/
  templates/
    github_pages/
      viewer_template.html          (existing, unchanged)
      standalone_template.html      (new)
    vendor/
      mermaid.min.js                (~3 MB, mermaid@11.9.0)
      marked.min.js                 (~50 KB, marked@11.0.0)
      svg-pan-zoom.min.js           (~30 KB, svg-pan-zoom@3.6.1)

codewiki/cli/
  html_generator.py                 (add generate_standalone())
  commands/html.py                  (call generate_standalone() after generate())
```

## API

`generate_standalone()` mirrors the existing `generate()` signature and adds one
required parameter:

```python
def generate_standalone(
    self,
    output_path: Path,           # e.g. output_dir / "standalone.html"
    title: str,
    input_dir: Path,             # required: read all leaf .md files from here
    leaves: List[Dict],          # leaf sections from doc_spec to know which files to embed
    module_tree: Optional[Dict] = None,
    repository_url: Optional[str] = None,
    github_pages_url: Optional[str] = None,
    config: Optional[Dict] = None,
    metadata: Optional[Dict] = None,
):
```

## Data Flow (build time)

1. Read all leaf `.md` files listed in `leaves` from `input_dir` → `{filename: content}` dict
2. Read `codewiki/templates/vendor/mermaid.min.js`, `marked.min.js`, `svg-pan-zoom.min.js`
3. Fill `standalone_template.html` placeholders:
   - `{{MERMAID_JS}}` → raw mermaid JS content
   - `{{MARKED_JS}}` → raw marked JS content
   - `{{SVG_PAN_ZOOM_JS}}` → raw svg-pan-zoom JS content
   - `{{MARKDOWN_FILES_JSON}}` → `JSON.dumps({"path/file.md": "# content..."})`
   - All existing placeholders (TITLE, MODULE_TREE_JSON, METADATA_JSON, etc.) unchanged
4. Write to `output_dir/standalone.html`

## Runtime Behaviour (browser)

`standalone_template.html` is identical to `viewer_template.html` except:

- `<script src="...cdn...">` tags replaced with `<script>{{MERMAID_JS}}</script>` etc.
- A `const MARKDOWN_FILES = {{MARKDOWN_FILES_JSON}};` block is injected
- `loadDocument(filename)` replaces `fetch()` with a dict lookup:

```js
const markdown = MARKDOWN_FILES[filename];
if (!markdown) { showError(`Document not found: ${filename}`); return; }
```

Navigation, mermaid rendering, svg-pan-zoom, and internal link handling are identical
to `index.html`.

## CLI Integration

`html_command` calls `generate_standalone()` immediately after `generate()`, reusing
the already-computed `module_tree`, `metadata`, `leaves`, and `repo_info`. No new CLI
flags.

The success log shows both output paths:

```
✓ Generated → /path/to/site/index.html
✓ Generated → /path/to/site/standalone.html
```

## Error Handling

| Scenario | Behaviour |
|---|---|
| Vendor `.js` file missing | `FileSystemError` at build time: "vendor file missing — reinstall the package" |
| Markdown file missing | Caught earlier by `_validate_files()`, never reaches standalone generation |
| `standalone.html` write failure | Surfaces via existing `safe_write` error path |
| Filename not in `MARKDOWN_FILES` at runtime | `showError()` in the template |

## Vendor File Acquisition

The three vendor files must be downloaded once and committed to the repo under
`codewiki/templates/vendor/`. They are not fetched at install or build time.
Exact versions to match the CDN URLs already in `viewer_template.html`:
- `mermaid@11.9.0` — `mermaid.min.js`
- `marked@11.0.0` — `marked.min.js`
- `svg-pan-zoom@3.6.1` — `svg-pan-zoom.min.js`
