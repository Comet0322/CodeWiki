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
      "type": "overview"
    },
    {
      "title": "後端",
      "file": "backend/index.md",
      "children": [
        {
          "title": "API 層",
          "file": "backend/api.md",
          "source_modules": ["api"],
          "status": "done"
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
- `file` 無 `source_modules` 無 `children` → overview 節點，排程最後執行，doc-writer 讀 output 目錄所有已生成文檔
- `status: "done"`：該節點已通過 doc-writer + doc-validator，由 skill 在節點完成後寫入；re-run 時跳過此節點
- `status: "failed"` + `retries: N`：失敗 N 次（上限 3），skill 暫停等使用者決定重試或中止
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

## 已知問題與改善清單

### 容易出錯的邏輯

- [x] **1.1** — exclude pattern 比對不穩定：codewiki analyze 寫入時排序正規化，skill 讀回直接比對
- [x] **1.3** — module-mapper commit hash 格式：只能複製 hash token，不能複製整行 comment
- [x] **1.4** — toc-planner 輸出格式歧義：無法可靠轉成 doc_spec.json；需改為嚴格欄位格式或直接輸出 JSON
- [x] **1.5** — doc-writer dispatch：`child_sections` 為空時仍需傳 key（空陣列），不可省略
- [x] **1.6** — overview 節點靠 "neither" fallback 偵測太脆弱：doc_spec.json 加 `"type": "overview"` 明確標記
- [x] **1.7** — doc-validator 無法區分葉節點 vs 群組節點：dispatch 需補傳 `has_children`
- [x] **1.8** — Batch rule 2「直接子葉節點」應改為「遞迴所有後代葉節點」
- [x] **1.9** — subagent 失敗無處理路徑：`status: "failed"` + `retries: N`，上限後暫停告知使用者
- [ ] **1.10** — 單一檔案 codebase 無模組可合併：module-mapper 需 fallback

### UX：不必要的來回

- [x] **2.1** — 語言與 profile 選擇是兩個分開問答，可合成一次
- [x] **2.2** — 自訂 profile 命名是第三次停頓，可併入草稿確認
- [x] **2.3** — Phase 0 與 Phase 1 scan 確認都在問 exclude：`codewiki scan` 提前到 Phase 0，一次確認
- [x] **2.4** — workflow 總覽表格未反映自訂 profile 的額外停頓

### UX：強迫自由輸入

- [x] **3.1** — Phase 0 exclude 欄位：改為 scan 推薦的勾選清單
- [x] **3.2** — 語言選擇：改為明確選單（1. 繁體中文 2. English 3. 其他）
- [x] **3.3** — 自訂 profile「描述需求」：改為現有 profile 的填空模板，不強迫使用者從空白開始
- [x] **3.4** — TOC 確認只能散文回答：改為編號清單 + 簡單指令語法（`toggle 3`、`merge 5 6`、`rename 7 "新標題"`）
- [N/A] **3.5** — doc-validator 每次重新詮釋 profile：`status: "done"` 確保每節點只跑一次，非確定性不成立

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
