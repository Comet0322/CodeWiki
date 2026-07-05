# CodeWiki — Skill-Driven Documentation Workflow

## 設計原則

CodeWiki 只負責：
1. **程式分析** — 產生 dependency graph 與 codebase index（`codewiki analyze`）
2. **HTML 輸出** — 將 markdown 轉換為帶導覽的靜態網站（`codewiki html`）

`codewiki generate` 整個移除。所有文檔規劃、內容生成、驗證邏輯 **全部由 Claude Code agent skill 負責**。

---

## Skill 流程：`codewiki-docs`

### Phase 0 — 互動式需求釐清

Skill 必須與使用者對話，確認以下最小必要項目後才能繼續：

| 項目 | 說明 |
|------|------|
| **目標 codebase 路徑** | 要生成文檔的專案根目錄 |
| **文檔語言** | 繁體中文 / 英文 / 其他 |
| **輸出目錄** | 生成的 `.md` 要放哪裡 |

目錄偏好此時不詢問——在看到模組識別結果之前，使用者和 skill 都沒有足夠資訊做有意義的討論。目錄設計延後到 Phase 3。

確認完畢才進入 Phase 1。

---

### Phase 1 — 取得 Dependency Graph

**快取檢查**（跳過條件：`codebase_index.md` 已存在且 header 的 commit hash 與當前 HEAD 一致）：

```bash
# git repo
git -C <codebase_path> rev-parse HEAD

# 非 git repo fallback：檢查是否有比產出物更新的原始碼檔案
find <codebase_path> -newer <output_dir>/codebase_index.md -name "*.py" -o -name "*.ts" ...
```

若快取有效 → 直接跳至 Phase 2 快取檢查。加 `--force` 旗標可強制重跑。

否則呼叫 CodeWiki 分析程式：

```bash
codewiki analyze --repo <codebase_path> --output <output_dir>
```

產出：`codebase_index.md`（含每個檔案的 token 量、in-degree、classes/functions 清單與 docstring）

---

### Phase 2 — 模組識別（全自動，無需使用者介入）

**快取檢查**：`module_map.md` 已存在且記錄的 git hash 與 `codebase_index.md` header 中的 commit 一致 → 直接跳至 Phase 3。

否則：

1. 派 **module-indexer subagent** 讀取 `codebase_index.md`，辨識：
   - 哪些檔案共同組成一個模組
   - 每個模組的功能用途是什麼
   - 模組之間的依賴方向

2. 派 **module-reviewer subagent** 驗證：
   - `codebase_index.md` 中每個檔案都被分配到至少一個模組
   - 模組邊界合理（無明顯切分錯誤）
   - 若發現問題，直接修正後再輸出

輸出：`module_map.md`（含產生時的 git hash），格式如下：

```markdown
## api
**功能**：處理 HTTP 路由與認證
**檔案**：src/api/routes.py, src/api/auth.py
**依賴**：database, utils

## database
**功能**：ORM 層，封裝所有 DB 操作
**檔案**：src/db/models.py, src/db/queries.py
**依賴**：（無）
```

---

### Phase 3 — 目錄設計與文檔規劃（subagent + 審查 + 使用者確認）

1. 派 **toc-planner subagent** 讀取 `module_map.md` 與 Phase 0 確認的語言，設計：
   - 完整文檔目錄（章節 → 子章節，支援巢狀）
   - 每個文檔的來源模組
   - 對每個模組明確標記**收入文檔**或**略過**，略過須附理由（如：test fixture、generated code、internal plumbing）

2. 派 **toc-reviewer subagent** 審查草稿：
   - 確認 `module_map.md` 中每個模組都有明確處置（收入某 section 或標記略過），不允許靜默遺漏
   - 確認 `source_modules` 引用的名稱確實存在於模組清單
   - 確認 `source_sections` 不構成循環依賴
   - 若發現問題，直接修正後再輸出

**審查通過後暫停，呈現給使用者確認或修改。**

使用者確認後，將結果寫入 `doc_spec.json`：

```json
{
  "language": "繁體中文",
  "sections": [
    {
      "title": "系統概覽",
      "file": "overview.md",
      "source_sections": ["後端"]
    },
    {
      "title": "後端",
      "file": "backend/index.md",
      "children": [
        {
          "title": "API 層",
          "file": "backend/api.md",
          "source_modules": ["api"],
          "template": "templates/api.md"
        },
        {
          "title": "資料庫",
          "file": "backend/database.md",
          "source_modules": ["database"]
        }
      ]
    }
  ]
}
```

**規則**：
- 有 `file` 的 section 是葉節點（實際會生成 `.md`）
- 只有 `children` 沒有 `file` 的 section 是純目錄節點（只出現在導覽，不生成 `.md`）
- `file` 與 `children` **可以同時存在**：此節點本身有文檔，子節點也有各自的文檔
- `file` 路徑必須是**相對於 `--input` 目錄的 root-relative 路徑**（如 `backend/api.md`）；markdown 內的內部連結也必須遵守同樣規則
- `source_modules`：直接讀取原始碼模組生成文檔（葉節點用）
- `source_sections`：跨樹依賴——讀取非子節點的已生成文檔（如 overview 依賴其他頂層章節）
- 有 `file` + `children` 的節點：自動依賴所有直接子章節的產物，不需要額外欄位
- `codewiki html` 導覽欄標題取自 markdown 檔案第一個 `# ` heading（fallback 為 spec `title`）

---

### Phase 4 — Markdown 生成（parallel subagents）

遞迴展開 `doc_spec.json` 中所有葉節點，依拓撲排序分批執行：

依 `source_sections` 依賴關係做拓撲排序，分批平行生成：

- 無 `source_sections`（或 `source_sections` 全部已完成）的節點可立即派 subagent
- 有 `source_sections` 的節點等其所有依賴完成後才派
- 同一批次內的節點全部平行執行

每個 doc-writer subagent：
- 有 `source_modules`：讀取原始碼
- 有 `children` + `file`：讀取所有直接子章節的已生成 markdown
- 有 `source_sections`：額外讀取指定的跨樹文檔
- 若有 `template`：讀取 template，遵守其中的所有生成要求（可包含章節結構、內容格式、語氣、必要圖表、特定欄位等任何指示）
- 語言遵守 spec `language`

---

### Phase 5 — 驗證與修正（per-doc subagent）

每個生成的 markdown，**各派一個 validator subagent**：
1. 若有 `template`：讀取 template，檢查生成的 markdown 是否符合 template 中所有生成要求
2. 若 FAIL：產生 `gaps` 清單，派 corrector subagent 修正
3. 最多 2 次修正循環；超過則標記 `NEEDS_HUMAN_REVIEW`

機械性驗證（檔案存在、mermaid 語法、內部連結）由 `codewiki html` 負責，不在此重複。

---

### Phase 6 — HTML 輸出與最終驗證

呼叫 CodeWiki HTML 指令：

```bash
codewiki html --spec <output_dir>/doc_spec.json --input <output_dir> --output <html_dir>
```

`codewiki html` 負責：
- 遞迴走訪 `doc_spec.json` 的 `sections` 樹，建立帶層級的導覽
- 驗證所有葉節點的 `.md` 檔案確實存在
- 驗證內部檔案連結有效（不 404）
- 驗證 mermaid 語法可正確渲染
- 輸出 `index.html`

---

## CodeWiki 職責邊界

| 功能 | 負責方 |
|------|--------|
| Codebase 靜態分析與 index 生成 | **CodeWiki**（`codewiki analyze`） |
| HTML 生成與驗證 | **CodeWiki**（新增 `codewiki html`） |
| 需求釐清對話 | **Skill** |
| 模組識別 | **Subagent** |
| 目錄設計 | **Subagent** |
| 文檔規劃（spec） | **Subagent + 使用者確認** |
| Markdown 內容生成 | **Parallel subagents** |
| 內容驗證與修正 | **Per-doc subagents** |

---

## 實作任務

### T1 — 建立 skill 檔案
**新檔案**：`.claude/skills/codewiki-docs/SKILL.md`

- [ ] Phase 0 互動式對話流程（只問路徑、語言、輸出目錄）
- [ ] Phase 1 快取檢查 + 呼叫 `codewiki analyze`
- [ ] Phase 2 dispatch module-indexer + module-reviewer subagent（全自動）
- [ ] Phase 3 dispatch toc-planner subagent + 等待使用者確認
- [ ] Phase 4 遞迴展開葉節點，dispatch parallel doc-writer subagents
- [ ] Phase 5 dispatch per-doc validator + corrector subagents
- [ ] Phase 6 呼叫 `codewiki html` 並報告驗證結果

### T5 — Subagent prompt templates
每個 subagent 類型需要對應的 prompt template：
- `module-indexer` — 讀 `codebase_index.md`，輸出 module_map.md
- `toc-planner` — 讀 module_map + Phase 0 確認的語言，輸出 doc_spec.json 草稿
- `doc-writer` — 讀 source code + spec，輸出 markdown
- `validator` — 讀 markdown + template（若有），對照 template 所有要求輸出 pass/fail + gaps
- `corrector` — 讀 draft + gaps，輸出 corrected markdown
