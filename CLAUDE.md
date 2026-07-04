# CodeWiki — Skill-Driven Documentation Workflow

## 設計原則

CodeWiki 只負責：
1. **程式分析** — 產生 dependency graph（`codewiki analyze`）
2. **HTML 輸出** — 將 markdown 轉換為帶導覽的靜態網站（`codewiki html`）

`codewiki generate` 整個移除。所有文檔規劃、內容生成、驗證邏輯 **全部由 Claude Code agent skill 負責**。

---

## Skill 流程：`codewiki-docs`

### Phase 0 — 互動式需求釐清

Skill 必須與使用者對話，確認以下項目後才能繼續：

| 項目 | 說明 |
|------|------|
| **目標 codebase 路徑** | 要生成文檔的專案根目錄 |
| **文檔語言** | 繁體中文 / 英文 / 其他 |
| **目標受眾** | 新進工程師 / 架構師 / 外部開發者 / ... |
| **目錄偏好** | 使用者希望的章節大綱（可草稿，後續 agent 細化） |
| **Markdown 風格** | 是否要 mermaid 圖、code block 多寡、敘述詳細程度等 |
| **輸出目錄** | 生成的 `.md` 要放哪裡 |

確認完畢才進入 Phase 1。

---

### Phase 1 — 取得 Dependency Graph

呼叫 CodeWiki 分析程式取得 dependency graph：

```bash
codewiki analyze --repo <codebase_path> --output <output_dir>/dependency_graph.json
```

產出：`dependency_graph.json`（含所有模組的 symbol 與相依關係）

---

### Phase 2 — 模組識別（subagent）

派一個 subagent 讀取 `dependency_graph.json`，辨識：
- 哪些檔案共同組成一個模組
- 每個模組的功能用途是什麼
- 模組之間的依賴方向

輸出：`module_index.md`，格式如下：

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

### Phase 3 — 目錄設計與文檔規劃（subagent + 使用者確認）

派一個 subagent 讀取 `module_index.md` 與 Phase 0 的使用者偏好，設計：
- 完整文檔目錄（章節 → 子章節，支援巢狀）
- 每個文檔的寫作計畫：
  - 來源模組
  - 必須涵蓋的要點（`must_cover`）
  - 預期長度與風格

**輸出草稿後暫停，呈現給使用者確認或修改。**

使用者確認後，將結果寫入 `doc_spec.json`：

```json
{
  "language": "繁體中文",
  "target_audience": "新進工程師",
  "style": {
    "mermaid": true,
    "detail_level": "high"
  },
  "sections": [
    {
      "title": "系統概覽",
      "file": "overview.md",
      "source_sections": ["後端"],
      "must_cover": [
        "系統整體架構圖（mermaid）",
        "主要資料流",
        "技術選型說明"
      ]
    },
    {
      "title": "後端",
      "file": "backend/index.md",
      "source_modules": ["api", "database"],
      "must_cover": ["後端模組概覽"],
      "children": [
        {
          "title": "API 層",
          "file": "backend/api.md",
          "source_modules": ["api"],
          "must_cover": [
            "所有 endpoint 清單",
            "認證機制",
            "錯誤處理策略"
          ]
        },
        {
          "title": "資料庫",
          "file": "backend/database.md",
          "source_modules": ["database"],
          "must_cover": [
            "Schema 設計",
            "ORM 用法",
            "Migration 策略"
          ]
        }
      ]
    }
  ]
}
```

**規則**：
- 有 `file` 的 section 是葉節點（實際會生成 `.md`）
- 有 `children` 的 section 是目錄節點（只出現在導覽，不生成 `.md`）
- 兩者**可以**同時存在（有 `file` 又有 `children`）：此節點本身有文檔，子節點也有各自的文檔
- `file` 路徑必須是**相對於 `--input` 目錄的 root-relative 路徑**（如 `backend/api.md`）；markdown 內的內部連結也必須遵守同樣規則
- `source_modules`：讀取原始碼模組生成的文檔
- `source_sections`：讀取**其他已生成的文檔**後生成（overview 專用）——需等其他文檔完成後才能撰寫
- `codewiki html` 導覽欄標題取自 markdown 檔案第一個 `# ` heading（fallback 為 spec `title`）

---

### Phase 4 — Markdown 生成（parallel subagents）

遞迴展開 `doc_spec.json` 中所有葉節點，分兩批：

**批次 1 — 所有 `source_modules` 節點**，各派一個 subagent 平行生成：
- 讀取對應 source_modules 的原始碼
- 依照 `must_cover` 列點撰寫
- 遵守 Phase 0 確認的 markdown 風格
- 文末附 self-check table：`| must_cover 項目 | 對應段落 | 涵蓋 Y/N |`

**批次 2 — 所有 `source_sections` 節點**（通常只有 overview），等批次 1 全部完成後再派 subagent：
- 讀取 `source_sections` 列出的已生成 markdown 檔案
- 依照 `must_cover` 撰寫整體概覽

---

### Phase 5 — 驗證與修正（per-doc subagent）

每個生成的 markdown，**各派一個 validator subagent**：
1. 逐項核查 `must_cover` 是否有實質內容
2. 檢查 mermaid 語法（若有）
3. 檢查內部連結格式
4. 若 FAIL：產生 `gaps` 清單，派 corrector subagent 修正
5. 最多 2 次修正循環；超過則標記 `NEEDS_HUMAN_REVIEW`

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
| Dependency graph 分析 | **CodeWiki**（新增 `codewiki analyze`） |
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

- [ ] Phase 0 互動式對話流程
- [ ] Phase 1 呼叫 `codewiki analyze`
- [ ] Phase 2 dispatch module-indexer subagent
- [ ] Phase 3 dispatch toc-planner subagent + 等待使用者確認
- [ ] Phase 4 遞迴展開葉節點，dispatch parallel doc-writer subagents
- [ ] Phase 5 dispatch per-doc validator + corrector subagents
- [ ] Phase 6 呼叫 `codewiki html` 並報告驗證結果

### T2 — 新增 `codewiki analyze` 指令
**新檔案**：`codewiki/cli/commands/analyze.py`

- [ ] `--repo`：目標 codebase 根目錄
- [ ] `--output`：`dependency_graph.json` 輸出路徑
- [ ] 從現有 `generate` 的分析邏輯抽取，不保留文檔生成部分

### T3 — 新增 `codewiki html` 指令
**新檔案**：`codewiki/cli/commands/html.py`

- [ ] `--spec`：`doc_spec.json` 路徑
- [ ] `--input`：markdown 檔案根目錄
- [ ] `--output`：HTML 輸出目錄
- [ ] 遞迴走訪 spec 樹，建立帶層級的導覽結構
- [ ] 驗證所有葉節點 `.md` 存在，缺少的列出錯誤
- [ ] 驗證內部連結（`[text](other.md)` 形式）
- [ ] 驗證 mermaid code block 語法（靜態檢查）
- [ ] 串接現有 `HTMLGenerator`

### T4 — 移除 `codewiki generate`
- [ ] 刪除 `codewiki/cli/commands/generate.py`
- [ ] 從 `codewiki/cli/main.py` 移除 `generate_command` 的註冊
- [ ] 刪除 `codewiki/cli/adapters/doc_generator.py`（文檔生成 adapter，不再需要）

### T5 — Subagent prompt templates
每個 subagent 類型需要對應的 prompt template：
- `module-indexer` — 讀 dependency graph，輸出 module_index.md
- `toc-planner` — 讀 module_index + 使用者偏好，輸出 doc_spec.json 草稿
- `doc-writer` — 讀 source code + spec，輸出 markdown
- `validator` — 讀 markdown + must_cover，輸出 pass/fail + gaps
- `corrector` — 讀 draft + gaps，輸出 corrected markdown
