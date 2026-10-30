# 搬機、備份與舊專案遷移

## 自己搬到另一部電腦

1. 等故事、人物整理和圖片工作全部完成。
2. 在 Taleoria 終端按 Ctrl+C，待停止後再複製。
3. 將整個 `Taleoria` 資料夾搬到新電腦；或執行 `python3 scripts/package_release.py --private`，搬走 `dist/Taleoria_Private_Backup.zip` 並解壓。
4. 新電腦依 [INSTALL.md](../INSTALL.md) 安裝 Python、KoboldCpp、相同 GGUF，以及 Draw Things／DreamShaper（可選）。
5. 保留 `taleoria.local.json` 的 `db`，修改有需要變更的本機 port，再雙擊新電腦的啟動檔。

現在存檔索引使用相對路徑；搬到不同使用者、不同資料夾名稱後，不需要手動修改 `data/**/index.json`。私人打包也會把舊絕對路徑轉為相對路徑。

`data/` 包含原始戰役、各個獨立分支、存檔索引、當前戰役選擇、圖片資料庫及 PNG。**保留整個 data，不要只挑某一個 sqlite3 或 illustrations 資料夾。** `.rpgsave` 可在遊戲內匯入成新分支，但不內嵌圖片；帶圖搬機以整個 data 為準。

模型沒有打入程式包。GGUF 可自行複製後在 KoboldCpp 重新選取；Draw Things 的匯入模型由它自己管理，新機可重新匯入原始 safetensors。

## 從舊 Kobold RPG 搬入

1. 停止舊服務，包含使用同一份資料的其他測試服務。
2. 解壓乾淨 Taleoria 安裝包；先不要啟動遊戲。
3. 在新的 Taleoria 資料夾執行：

```sh
python3 scripts/migrate_legacy.py "/舊專案所在位置/Kobold RPG"
```

工具只讀舊專案，複製全部 data、使用 SQLite 備份並核對完整性，重寫新副本的存檔索引。新 data 已有進度時會停止，避免覆蓋。來源在複製中改變也會停止；請先關閉舊服務。

4. 舊服務若用過 `--db data/其他檔案.sqlite3`，把同一相對路徑填入新 `taleoria.local.json` 的 `db`；預設 mistbridge 則不用改。
5. 啟動新 Taleoria，核對角色、最後一段故事和圖片後，再決定是否封存舊副本。舊專案不會由遷移工具改名或刪除。

## 給別人全新安裝

執行 `python3 scripts/package_release.py`，分享 `dist/Taleoria.zip`。乾淨包只包含程式、測試、規則與指南，不包含你的 data、私人設定、圖片、模型或舊工作紀錄。第一次啟動會建立新的霧橋鎮戰役。

私人備份含完整劇情及世界私密資料，不能當作公開 release。程式升級時先備份，替換程式檔，保留 data、models 及 taleoria.local.json。
