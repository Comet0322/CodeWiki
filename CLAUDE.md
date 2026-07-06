# CodeWiki — Skill-Driven Documentation Workflow

## 設計原則

CodeWiki 只負責：
1. **程式分析** — 產生 dependency graph 與 codebase index（`codewiki analyze`）
2. **HTML 輸出** — 將 markdown 轉換為帶導覽的靜態網站（`codewiki html`）

`codewiki generate` 整個移除。所有文檔規劃、內容生成、驗證邏輯 **全部由 Claude Code agent skill 負責**。

---

## 關鍵 Schema

詳細流程見 `.claude/skills/codewiki-docs/SKILL.md`。

### module_map.md 格式

```markdown
<!-- commit: <hash> -->

## api
**功能**：處理 HTTP 路由與認證
**檔案**：src/api/routes.py, src/api/auth.py
**Token 量**：11,300
**依賴**：database, utils
```

### doc_spec.json 格式

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

**doc_spec.json 規則**：
- 有 `file` → 葉節點，會生成 `.md`
- 只有 `children` 無 `file` → 純目錄節點，只出現在導覽
- `file` + `children` 可同時存在
- `file` 路徑相對於 `--input` 目錄
- `source_modules`：讀原始碼生成
- `source_sections`：讀已生成的跨樹文檔
- `check: true`：該節點已通過 doc-writer + doc-validator，由 skill 在節點完成後寫入；re-run 時跳過此節點
- `codewiki html` 導覽標題取自 markdown 第一個 `# ` heading

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

### T1 — 建立 skill 檔案 ✅（概要完成，需細化）
**檔案**：`.claude/skills/codewiki-docs/SKILL.md`

- [x] Phase 0~6 概要流程建立
- [ ] **Phase 2**：補上 module-indexer/module-reviewer 的 dispatch 細節與 prompt 指引
- [ ] **Phase 3**：補上 toc-planner/toc-reviewer 的 dispatch 細節與 prompt 指引
- [ ] **Phase 4**：補上拓撲排序邏輯、doc-writer dispatch 方式
- [ ] **Phase 5**：補上 validator/corrector dispatch 與重試邏輯

### T2 — Subagent prompt templates
每個 subagent 需要明確的 prompt，說明輸入、輸出格式、判斷準則：

- [ ] `module-indexer` — 讀 `codebase_index.md`，按目錄結構 + depends_on + in_degree 分組，輸出 `module_map.md`
- [ ] `module-reviewer` — 確認每個檔案有模組歸屬、邊界合理，直接修正後輸出
- [ ] `toc-planner` — 讀 `module_map.md` + 使用者需求，設計目錄，每個模組標記收入或略過
- [ ] `toc-reviewer` — 確認無遺漏、無循環依賴，直接修正後輸出
- [ ] `doc-writer` — 讀原始碼 / 子章節 / 跨樹文檔，依 spec 與使用者需求生成 markdown
- [ ] `validator` — 對照 template 所有要求輸出 pass/fail + gaps 清單
- [ ] `corrector` — 讀 draft + gaps，輸出修正後的 markdown

### T3 — 端對端測試
- [ ] 選一個小型 codebase 跑完整流程（Phase 0 → Phase 6）
- [ ] 驗證 `codewiki html` 能正確讀取生成的 markdown 並輸出 HTML
