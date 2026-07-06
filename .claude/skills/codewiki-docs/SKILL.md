---
name: codewiki-docs
description: Generate structured technical documentation for any codebase. Uses `codewiki analyze` to analyze code structure, then dispatches subagents to identify modules, select a documentation profile, plan the table of contents, generate markdown in parallel, and output a static HTML site. Triggered when the user says "generate docs", "document this codebase", "codewiki", "產生技術文件", or "幫我寫文件".
---

# codewiki-docs

Subagent behavior is defined in `.claude/agents/`; this skill only handles flow control and user interaction.

## Workflow Overview

| Phase | Name | Description | Interaction |
|-------|------|-------------|-------------|
| 0 | Requirements | Confirm codebase path, output directory, exclude paths | ⏸️ Confirm with user |
| 1 | Static Analysis | Run `codewiki analyze`, produce `codebase_index.md` | Automatic (skip if cached) |
| 2 | Module Mapping | module-mapper subagent produces `module_map.md` | Automatic (skip if cached) |
| 3 | TOC Design | Select profile → toc-planner plans TOC → write `doc_spec.json` | ⏸️ Language+profile (one form); ⏸️ Confirm TOC; custom profile path adds one extra pause |
| 4 | Markdown Generation | Dispatch doc-writer subagents in topological order | Automatic |
| 5 | HTML Output | Run `codewiki html`, produce static site | Automatic |

## Phase 0 — Requirements

As soon as the user provides the codebase path, run the pre-scan immediately (no waiting for other fields):

```bash
codewiki scan --repo <codebase_path>
```

Then present a single confirmation form combining all fields. Pre-fill the exclude list from scan output (all candidates selected by default):

```
Codebase path:    <path provided by user>
Output directory: ./docs  (change if needed)
Exclude paths:    (select to deselect — all pre-selected from scan)
  [x] node_modules/
  [x] dist/
  [x] ...
  [ ] Add custom pattern: ___
```

⏸️ **Pause**: wait for the user to confirm or adjust, then proceed.

Language and documentation style are confirmed in Phase 3.

---

## Phase 1 — Static Analysis

Cache check (only runs if `codebase_index.md` already exists):

**With git:**
```bash
git -C <codebase_path> rev-parse HEAD 2>/dev/null
```
`codebase_index.md` line 2 format: `commit: <hash> | files: N | tokens: N | exclude: <patterns>`

Compare the `commit` token against the current HEAD hash, and the `exclude` token against the current run's exclude patterns (sort and trim before comparing — the file already stores a sorted canonical form). Both match → skip to Phase 2. If no `exclude` token in the header and no exclude patterns this run, that also counts as a match.

**Without git (or git fails):**
```bash
find <codebase_path> -newer <output_dir>/codebase_index.md \
  -not -path "*/.git/*" -type f 2>/dev/null | head -1
```
No output (no files newer than the index) → skip to Phase 2.

Neither condition met → run analysis.

**Run analysis**

```bash
codewiki analyze --repo <codebase_path> --output <output_dir> \
  [--exclude '<exclude_patterns>']
```

Produces: `<output_dir>/codebase_index.md` (header format: `<!-- commit: <hash> exclude: <exclude_patterns> -->`)

---

## Phase 2 — Module Mapping (automatic)

Cache check: if `<output_dir>/module_map.md` exists and its first-line commit hash matches the `codebase_index.md` header → skip to Phase 3.

Otherwise dispatch the **module-mapper** subagent with:
- Read target: `<output_dir>/codebase_index.md`
- Output path: `<output_dir>/module_map.md`

---

## Phase 3 — TOC Design (Profile Selection + User Confirmation)

### Step 1: Language and Profile Selection

Scan `.claude/skills/codewiki-docs/profiles/` for all `.md` files, extract the first line of each file's "applicable scenarios" section as a summary. Present language and profile as a **single combined form**:

```
Documentation language:
  1. 繁體中文
  2. English
  3. Other (specify): ___

Documentation profile:
  A. Classic Comprehensive  — full module-by-module coverage with diagrams
     [.claude/skills/codewiki-docs/profiles/classic-comprehensive.md]
  ...
  Z. Custom                 — start from an existing profile as a template
```

⏸️ **Pause**: wait for the user to select both language and profile in one response.

When the user selects "Custom":

Follow up: "Do you have an existing template file? (provide the path) Or pick an existing profile as a starting scaffold:"

Present the same profile menu again as a numbered list. If the user picks a base profile (or provides a path), read it and present it as a **fill-in-the-blank form** — keep all section headings intact, replace each content block with a labelled prompt:

```
## Applicable Scenarios
[Describe target audience and use case: ___]

## TOC Organization
[How should modules map to sections? ___]

## Section Writing Guidelines
...
```

⏸️ **Pause**: show the scaffold and ask the user to fill it in. Also ask for a profile name in the same message: "Fill in the sections above, and give this profile a name (lowercase, hyphen-separated, e.g. `api-deep-dive`): ___"

Wait for confirmation or edits (iterate as needed). Write the confirmed profile to `<output_dir>/profiles/<name>.md`.

### Step 2: toc-planner subagent

Prepare profile content (**always read the full file in all cases**, never use inline text):
- Menu profiles: read the full `.md` file (path shown in menu)
- Custom (file path): read the file at the user-provided path
- Custom (description): read the file just saved at `<output_dir>/profiles/<name>.md`

Dispatch the **toc-planner** subagent with:
- Profile content (full file text prepared above)
- Full text of module_map.md (`<output_dir>/module_map.md`)
- Language: `<language>`

### Step 3: User Confirmation

Render the toc-planner JSON as a readable summary (do not show raw JSON):

```
Sections (N total):
  [overview]  System Overview → overview.md
  Backend/
    API Layer → backend/api.md  [api, auth]
    Database  → backend/database.md  [database]

Skipped (M modules):
  tests — test fixtures
  config — environment config
```

⏸️ **Pause**: present the summary and wait for confirmation or edits.

The user may request changes in natural language (e.g. "rename API Layer to REST API", "merge api and auth into one section", "skip the config module"). Apply each change directly to the JSON, re-render the summary, and confirm again. Repeat until the user approves.

### Step 4: Write doc_spec.json

Write the confirmed JSON (without the `skipped` field and the summary comment line) to `<output_dir>/doc_spec.json`:

```json
{
  "language": "<language>",
  "profile": "profiles/developer-reference.md",
  "sections": [
    {
      "title": "System Overview",
      "file": "overview.md",
      "type": "overview"
    },
    {
      "title": "Section Title",
      "file": "relative/path.md",
      "source_modules": ["module_name"],
      "children": []
    }
  ]
}
```

**Field rules**:
- `profile`: profile file path (relative to skill directory); always use this field — custom descriptions are already saved as profile files in Phase 3 Step 1
- `file` present → this section generates a `.md` file
- `children` only, no `file` → navigation-only node, no file generated
- `file` + `children` both present → this node generates its own file and has child sections
- `type: "overview"` → exactly one per doc; runs last; doc-writer reads all completed `.md` files in output dir

---

## Phase 4 — Markdown Generation (parallel subagents)

### Topological Sort

Recursively expand `doc_spec.json` to find all leaf nodes (sections with a `file`).

**Skip condition**: node already has `"status": "done"` → treat as complete, do not regenerate.

Batching rules:
1. **First batch**: nodes with `source_modules` and no child leaf nodes
2. **Subsequent batches**: nodes with `source_modules` whose all descendant leaf nodes are `status: "done"`; or nodes with `children` + `file` whose all descendant leaf nodes are `status: "done"`
3. **Last batch**: overview nodes (`type: "overview"`) — dispatched only after all other nodes are `status: "done"`; doc-writer reads all `.md` files in the output directory

Maximum **3 nodes** run in parallel per batch; wait for the entire batch before starting the next.

### Dispatching doc-writer + doc-validator

Each leaf node runs in sequence:

**Step 1 — doc-writer**: dispatch the **doc-writer** subagent with:

```
Section title:     <title>
Output path:       <output_dir>/<file>
Language:          <language>

source_modules:    <absolute paths of source files for the module, or [] if none>
child_sections:    <absolute paths of output_dir/file for direct child nodes, or [] if none>
profile:           <absolute path to profile file>
doc_spec:          <output_dir>/doc_spec.json
module_map:        <output_dir>/module_map.md
codebase_index:    <output_dir>/codebase_index.md
```

**Step 2 — doc-validator** (only when the node has `source_modules`): dispatch the **doc-validator** subagent with:

```
Doc path:          <output_dir>/<file>
source_modules:    <absolute paths of source files for the module>
has_children:      <true if the node has children, false otherwise>
profile:           <absolute path to profile file>
codebase_index:    <output_dir>/codebase_index.md
```

After doc-validator completes, the skill writes `"status": "done"` into the node in `doc_spec.json`. Only then is the node considered complete for scheduling purposes.

**Failure handling**: if either subagent fails, the skill increments `retries` on the node in `doc_spec.json` and retries the **entire node** from Step 1 (re-dispatch doc-writer, then doc-validator). After 3 failed attempts (`retries: 3`), the skill sets `"status": "failed"` on the node and ⏸️ pauses to inform the user which node is blocked and ask whether to retry or abort Phase 4.

The main agent must never read validator findings and apply them manually. If a validator cannot write its fixes, that is a subagent failure — increment `retries` and retry the full node.

---

## Phase 5 — HTML Output

```bash
codewiki html --spec <output_dir>/doc_spec.json --input <output_dir> --output <html_dir>
```

Report the result to the user. If there are errors, list the specific messages and ask the user to handle them.
