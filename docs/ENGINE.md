# Taleoria 引擎與開發說明

## 執行結構

瀏覽器向同一部電腦的 Python 後端送出行動；後端讀取 SQLite 狀態，組合模型輸入，經 KoboldCpp 依 RPG OS 主持，再以交易保存敘事及可用的狀態變化。一般行動沒有額外的語意批准者；只保留玩家已授權的超自然能力來源核對。Draw Things 另行接收圖片描述，圖片不寫回故事世界。

- `server.py` 提供網站、玩家 API、非同步生成工作與啟動參數。
- `kobold_rpg/engine.py` 管理狀態、版本及事件鏈。
- `gm.py` 組合目前狀態、相關原規則與近期對話，一般回合一次生成；`model.py` 處理 KoboldCpp 連線。
- `worldgen.py` 建立主角、起點、在場人物與開場。
- `library.py` 管理戰役、存檔及目前分支，磁碟索引以資料夾相對路徑保存。
- `portable.py` 處理 `.rpgsave` 格式；既有檔案格式標記和內部模組名稱保留相容。
- `illustrations.py` 管理獨立生圖工作、快取、設定與 PNG。
- `app.js` 負責故事／人物／背包介面；`illustrations.js` 把圖片及圖示融入既有卡片。

## 啟動及設定

Python 3.11+，只用標準函式庫。從任何工作目錄執行 `python3 /專案位置/server.py`，預設資料都相對於專案資料夾。

```sh
python3 server.py
python3 server.py --port 8787 --model-url http://127.0.0.1:5002
python3 server.py --db data/another.sqlite3 --port 8797
```

預設讀取根目錄 `taleoria.local.json`，CLI 參數覆蓋對應設定。只有使用命令列維護時才需要上述參數；玩家依 [INSTALL.md](../INSTALL.md) 雙擊啟動即可。`taleoria.py` 另會開啟瀏覽器。

網站只監聽 127.0.0.1。模型及生圖設定只接受 HTTP loopback 網址，不支援雲端 API、帳戶金鑰或直接以 Ollama 代替 KoboldCpp。圖像網址及美術風格存於目前遊戲資料目錄下的 illustrations 資料庫；切換另一個 `--db` 及其 library 時可能需要另設。

## 狀態與責任

1. 理解玩家發言、想法和動作，不把未說出口的想法提供給 NPC。
2. 世界身分、能力與資源需有先行來源；模型不能任意新增欄位或授予能力。
3. 版本核對及 request_id 避免舊頁面或重送重複寫入同一次行動。
4. SQLite 交易保存目前狀態、前後快照及事件雜湊鏈；雜湊鏈不是有權重寫資料者無法偽造的簽章。
5. 普通物理交手不使用預設 HP 或強制骰表；傷勢需有效事件，不強迫玩家命中。
6. 私密世界資料及人物內心不傳入普通玩家狀態。完整存檔含私密資料，請視為自己的私人檔案。
7. 故事與人物狀態由同一筆事件交易保存。
8. 當前單一服務內的文字與圖片工作順序執行；不會自動卸載模型，也無法協調其他獨立進程的 GPU 使用。

模型仍可能重複、誤解或答非所問。RPG OS 原文與狀態提供依據，不代表小模型對自然語言的判斷已能形式化證明；此版本不是 RPG OS 全流程的等價實作。

## 開放世界與 RPG OS

建立世界只生成主角、起點、在場人物及開場。只有語言或名稱不符要求時才有修補呼叫。不在開局預寫未來章節或固定劇情真相。

一般回合由同一次 RPG OS 主持生成理解、裁定和敘事。已接受的回合與目前世界狀態作為後續依據；沒有預寫章節催促玩家。死亡、不在場及不知情的人物仍受現況和角色知識限制。

人物頁保留首次遇見時的描述，不另行更新人物卡。人物性格、關係和已發生事件仍由內部世界狀態及完整對話保存。背包只顯示物品名稱和數量，物品用途仍依故事現況判斷。未來故事由實際遊玩發展，不另存預製藍圖。

本機 8K 模型透過文字計數接口選取完整近期對話，在需要時將單次輸出上限由 1500 降至 1200，以保留最新交談。更早對話仍保存在資料庫；這是檢索取捨，沒有額外摘要模型。

## 本機資料

預設起始 DB 為 `data/taleoria.sqlite3`（只有建立世界的空白入口），索引為 `data/library/index.json`，目前選擇保存在 `active.json`（曾切換時建立）。新世界、匯入分支及具名存檔各有獨立 DB。其他 `--db` 使用同層 `<檔名>-library/`。

存檔索引在記憶體中使用完整路徑，寫入磁碟時轉為相對於 library 的路徑，包含指向起始 DB 的 `../檔名.sqlite3`；實際讀取仍限制在該 library 或指定起始 DB。舊索引應使用 [搬機工具](PORTABILITY.md) 轉換。

`.rpgsave` 是可驗證的 JSON，載入後成新分支；不執行 SQL 或腳本，亦不內嵌圖片。完整搬機請停服務後保存整個 data。

## 檢查

```sh
python3 scripts/check_setup.py
python3 scripts/run_checks.py
node --check app.js
node --check illustrations.js
node tests/test_illustrations_ui.cjs
```

Node 只供開發檢查，不是玩家依賴。限制 socket 的環境可明確執行 `python3 scripts/run_checks.py --no-network`；其結果不包括略過的 HTTP 整合測試，不能稱為全套通過。

## 已知限制

- 不同瀏覽器分頁沒有跨分頁即時故事同步；不同服務的選定戰役也獨立。
- 任務生成中重新整理，可在同分頁以 request_id 接回結果；伺服器停止不保留未完成的敘事生成。
- 圖像不能保證臉部一致，沒有角色參考圖或 LoRA 訓練。
- 尚未提供 Vercel 前端與本機 companion 的配對／跨來源架構。
- 沒有完整實作原 RPG OS 建立訪談、長期記憶編譯、世界自主進程、原生存檔匯入或全自動語意裁判。

## 授權與來源

RPG OS v1.01 by croatianrdy2defend-create：[原專案](https://github.com/croatianrdy2defend-create/RPG-OS)。Understand → Establish → Resolve → Portray、Freeform、玩家主導、NPC 個人基礎及五欄互動狀態等改編概念使用 CC BY 4.0；不代表原作者背書。原文、來源和雜湊見 `rules/rpg_os_v1_01/`，呼叫模型前由 rulebook 核對。

詳細見 [THIRD_PARTY.md](../THIRD_PARTY.md) 及 [LICENSE](../LICENSE)。
