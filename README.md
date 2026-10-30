# Taleoria｜千語之境

在自己電腦運行的 AI 文字 RPG，使用 KoboldCpp 主持故事，可選擇以 Draw Things 生成場景、人物及物品圖片。遊戲、存檔和圖片都保存在本機。

**第一次安裝：依照 [INSTALL.md](INSTALL.md) 完成 5 個步驟。**

## 每次開始玩

1. 打開 KoboldCpp，載入文字模型。
2. 想生成圖片時，打開 Draw Things，選擇圖像模型並啟動 HTTP API。
3. Mac 雙擊 `Start_Taleoria.command`；Windows 雙擊 `Start_Taleoria.bat`。
4. 瀏覽器會打開 <http://127.0.0.1:8787/>。關閉時在 Taleoria 終端按 Ctrl+C。

需要 Python 3.11 或以上；Taleoria 沒有第三方 Python 套件，也不需要 Node、npm 或雲端帳戶。完整文字與生圖流程目前在 Apple Silicon Mac 驗證；Windows／Linux 的文字入口已提供，生圖替代服務尚未實機驗證。

## Vercel 與跨電腦遊玩

Vercel 提供網頁，遊戲引擎、SQLite、KoboldCpp 與 Draw Things 留在你選擇的電腦。網站設定可修改遊戲電腦網址、配對碼及文字模型網址；生圖另有 Draw Things 設定。配對碼只存瀏覽器，不提交 GitHub。部署與配對步驟見 [HOSTING.md](docs/HOSTING.md)。

## 新故事如何開始

第一次開啟會先建立世界，選擇題材、難度、角色與想玩的內容，預覽後再確認開局。AI 先準備精簡開場、固定真相與簡短章節骨架；人物、地點及章節細節隨實際探索逐步建立。遊玩仍由 RPG OS v1.01 主持：你可以生活、拒絕線索、繞路、跳章或改變結局，故事規劃不能取消已發生的後果。

一般回合只用一次主持生成，不另外呼叫故事導演。人物頁會隨實際經歷更新已知資訊、關係與狀況；私密真相不會出現在玩家介面。

人群採分層資料，暫時不相關的人物與路線會退出模型上下文，仍留在存檔，相關時再取回。流程、失敗續接與限制見 [逐步建立世界與記憶](docs/PROGRESSIVE_WORLD.md)。

## 資料夾用途

| 位置 | 用途 |
| --- | --- |
| `Start_Taleoria.*`、`taleoria.py` | 啟動遊戲 |
| `server.py`、`app.js`、`ui.html`、CSS／SVG | 本機網站及後端 |
| `kobold_rpg/` | 遊戲引擎；內部模組名稱保留以相容既有程式與存檔 |
| `data/` | 你的戰役、存檔和生成圖片；搬機必須保留 |
| `models/` | 可選的 GGUF 放置位置；Draw Things 自行管理匯入的模型 |
| `taleoria.example.json` | 連線設定範本 |
| `taleoria.local.json` | 自己的設定；不公開上傳 |
| `docs/` | 生圖、搬機、開發與授權說明 |
| `scripts/` | 安裝檢查、搬入舊資料、打包工具 |
| `tests/`、`rules/` | 回歸測試與原始規則／授權 |
| `dist/`、`archive/`、`work/` | 本機產出的安裝包、舊工作檔與驗證資料；不進發佈包 |

## 搬機和分享

- 自己搬機：先停止 Taleoria，再複製整個專案；模型在新電腦重新安裝。詳細見 [搬機說明](docs/PORTABILITY.md)。
- 給朋友全新安裝：分享 `dist/Taleoria.zip`；沒有你的遊戲資料或模型。
- 私人搬機備份可用 `python3 scripts/package_release.py --private` 建立；**含私人遊戲資料，請勿公開**。
- GitHub 適合保存與分發程式；此階段仍由每位玩家在自己電腦啟動，見 [GitHub／Vercel](docs/HOSTING.md)。

## 目前限制

同一個網址的不同分頁不會即時同步故事，更新後需重新整理；不同連接埠可能是不同遊戲服務。建議用一個分頁遊玩。模型仍可能答非所問或記錯，敘事核對不保證完全正確。圖片也不會自動成為世界設定。

程式版本：`0.12.2-local`。逾時會自動重新連接同一次故事生成；每段故事可手動「描繪這一刻」，依當時的公開敘事與人物外觀生成插畫。新回應顯示後會定位到你的上一個行動；能力名稱與圖片按鈕提供滑鼠提示。引擎設計與歷史限制見 [ENGINE.md](docs/ENGINE.md)，人格模型見 [SOCIAL_MODEL.md](docs/SOCIAL_MODEL.md)。授權見 [LICENSE](LICENSE) 與 [THIRD_PARTY.md](THIRD_PARTY.md)。
