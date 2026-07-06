---
name: codewiki-docs
description: 為任意 codebase 生成結構化技術文檔。使用 codewiki analyze 分析程式結構，透過 subagent 自動識別模組、選擇文檔風格 profile、規劃目錄、平行生成 markdown，最後輸出靜態 HTML 網站。當使用者說「幫我生成文檔」、「document this codebase」、「codewiki」、「產生技術文件」、「幫我寫文件」時觸發。
---

# codewiki-docs

Subagent 行為定義在 `.claude/agents/`；本 skill 只負責流程控制與使用者互動。

## 流程總覽

| Phase | 名稱 | 說明 | 互動 |
|-------|------|------|------|
| 0 | 需求釐清 | 確認 codebase 路徑、輸出目錄、排除路徑 | ⏸️ 與使用者確認 |
| 1 | 靜態分析 | 執行 `codewiki analyze`，產生 `codebase_index.md` | 全自動（有快取則跳過）|
| 2 | 模組識別 | module-mapper subagent 產生 `module_map.md` | 全自動（有快取則跳過）|
| 3 | 目錄設計 | 選 profile → toc-planner 規劃目錄 → 寫入 `doc_spec.json` | ⏸️ 與使用者確認目錄 |
| 4 | Markdown 生成 | 依拓撲排序平行派發 doc-writer subagents | 全自動 |
| 5 | HTML 輸出 | 執行 `codewiki html`，產生靜態網站 | 全自動 |

## Phase 0 — 需求釐清

與使用者確認以下資訊後才繼續：

| 項目 | 說明 |
|------|------|
| **codebase 路徑** | 要生成文檔的專案根目錄 |
| **輸出目錄** | 生成的 `.md` 與產出物要放哪裡（預設：`./docs`） |
| **排除路徑（選填）** | 有沒有明確不想分析的目錄或檔案？（e.g. `dist/`、`public/assets/`） |

語言與文檔風格在 Phase 3 確認。

---

## Phase 1 — 靜態分析

快取檢查（`codebase_index.md` 存在時才執行）：

**有 git：**
```bash
git -C <codebase_path> rev-parse HEAD 2>/dev/null
```
header 第二行格式：`commit: <hash> | files: N | tokens: N | exclude: <patterns>`
commit hash 一致且 exclude patterns 一致 → 跳至 Phase 2。

**無 git（或 git 指令失敗）：**
```bash
find <codebase_path> -newer <output_dir>/codebase_index.md \
  -not -path "*/.git/*" -type f 2>/dev/null | head -1
```
無輸出（沒有比 index 更新的檔案）→ 跳至 Phase 2。

以上皆不符合 → 執行 Step 1。

否則：

**Step 1 — 快速 pre-scan**

```bash
codewiki scan --repo <codebase_path>
```

輸出會列出建議排除的目錄與檔案，以及可直接使用的 `--exclude` 字串。

若有排除項目，列出給使用者確認（可調整）後再繼續；若無，直接執行 Step 2。

**Step 2 — 執行分析**

```bash
codewiki analyze --repo <codebase_path> --output <output_dir> \
  [--exclude '<exclude_patterns>']
```

產出：`<output_dir>/codebase_index.md`（header 格式：`<!-- commit: <hash> exclude: <exclude_patterns> -->`）

---

## Phase 2 — 模組識別（全自動）

快取檢查：`<output_dir>/module_map.md` 存在且第一行的 commit hash 與 `codebase_index.md` header 一致 → 跳至 Phase 3。

否則派 **module-mapper** subagent，傳入：
- 讀取目標：`<output_dir>/codebase_index.md`
- 輸出路徑：`<output_dir>/module_map.md`

---

## Phase 3 — 目錄設計（Profile 選擇 + 使用者確認）

### Step 1：語言與 Profile 選擇

先詢問文檔語言（繁體中文 / 英文 / 其他）。

掃描 `.claude/skills/codewiki-docs/profiles/` 下所有 `.md` 檔案，從各自的「適用場景」欄位擷取第一行摘要，動態組成選單，最後加上「自訂」選項：

```
A. 標準模組層級文檔  — 逐模組圖文完整覆蓋
   [.claude/skills/codewiki-docs/profiles/classic-comprehensive.md]

...

Z. 自訂              — 提供模板檔案路徑，或描述文檔需求
```

選「自訂」時，追問：「你有現成模板檔案嗎？（請提供路徑）或直接描述你的文檔需求。」

**若使用者提供描述（非檔案路徑）**：

依照現有 profile 的格式（`適用場景` + `TOC 組織邏輯` + `各章節寫作指引`，含固定 H2 骨架），根據使用者描述起草一份完整的 profile 文件，呈現給使用者確認：

⏸️ **暫停**：列出完整的 profile 草稿，說明「確認後請為它取個名稱，存入 `<output_dir>/profiles/`，之後就可以直接指名使用」。

等待確認或修改（可反覆調整）。確認後追問：「請為這個 profile 取個名稱（英文小寫、連字號分隔，例如 `api-deep-dive`）」

將確認後的 profile 寫入 `<output_dir>/profiles/<name>.md`。

### Step 2：toc-planner subagent

準備 profile 內容（**所有情況皆讀取檔案全文**，不使用 inline 文字）：
- 選單中列出的 profile：讀取對應的 `.md` 檔案全文（路徑已在選單中標示）
- 自訂（提供路徑）：讀取使用者給的檔案路徑全文
- 自訂（描述需求）：讀取 Step 1 中剛存入的 `<output_dir>/profiles/<name>.md` 全文

派 **toc-planner** subagent，傳入：
- profile 內容（上方準備好的全文）
- module_map.md 全文（`<output_dir>/module_map.md`）
- 語言：`<language>`

### Step 3：使用者確認

⏸️ **暫停**：將 toc-planner 的目錄草稿呈現給使用者。

告知使用者可以：調整章節層級、合併或拆分模組、增加新章節、移除不需要的部分、變更略過/收入的決定。

等待確認或修改，然後進 Step 4。

### Step 4：寫入 doc_spec.json

依確認後的目錄組合並寫入 `<output_dir>/doc_spec.json`：

```json
{
  "language": "<language>",
  "profile": "profiles/developer-reference.md",
  "sections": [
    {
      "title": "章節標題",
      "file": "relative/path.md",
      "source_modules": ["module_name"],
      "children": []
    }
  ]
}
```

**欄位規則**：
- `profile`：profile 檔案路徑（相對於 skill 目錄）；所有情況皆使用此欄位，custom 描述需求已在 Phase 3 Step 1 存成 profile 檔案
- `file` 存在 → 葉節點，實際生成 `.md`
- 只有 `children` 沒有 `file` → 純目錄節點
- `file` + `children` 同時存在 → 此節點有自己的文檔，子節點也有各自的文檔
- `source_sections` → 跨樹依賴，讀取非子節點的已生成文檔

---

## Phase 4 — Markdown 生成（parallel subagents）

### 拓撲排序

遞迴展開 `doc_spec.json`，找出所有葉節點（有 `file` 的 section）。

**跳過條件**：節點已有 `"check": true` → 直接視為完成，不重新生成。

分批規則：
1. **第一批**：無 `source_sections`、且無子葉節點的節點
2. **後續批次**：所有 `source_sections` 依賴已完成（含 `check: true` 的舊節點）、且所有直接子葉節點已完成的節點
3. 有 `children` + `file` 的節點，隱式等待所有直接子節點完成

每批最多 **3 個節點**平行執行，等該批全部完成再執行下一批。

### 派發 doc-writer + doc-validator

每個葉節點依序執行：

**Step 1 — doc-writer**：派 **doc-writer** subagent，傳入：

```
章節標題：<title>
輸出路徑：<output_dir>/<file>
語言：<language>

source_modules：<模組對應的原始碼檔案絕對路徑清單>
child_sections：<直接子節點的 output_dir/file 絕對路徑清單>（若有）
source_sections：<跨樹依賴的 output_dir/file 絕對路徑清單>（若有）
profile：<profile 檔案絕對路徑>
doc_spec：<output_dir>/doc_spec.json
module_map：<output_dir>/module_map.md
```

**Step 2 — doc-validator**（僅當該節點有 `source_modules` 時執行）：派 **doc-validator** subagent，傳入：

```
文檔路徑：<output_dir>/<file>
source_modules：<模組對應的原始碼檔案絕對路徑清單>
profile：<profile 檔案絕對路徑>
```

doc-validator 完成後，skill 將該節點在 `doc_spec.json` 中寫入 `"check": true`，此節點才標記為「已完成」，可供後續批次的 source_sections 使用。

---

## Phase 5 — HTML 輸出

```bash
codewiki html --spec <output_dir>/doc_spec.json --input <output_dir> --output <html_dir>
```

將執行結果回報給使用者。若有錯誤，列出具體訊息請使用者處理。
