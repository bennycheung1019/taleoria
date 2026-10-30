# GitHub、Vercel 與自己的模型

Vercel 只提供靜態網頁；RPG OS 引擎、SQLite 存檔、圖片、KoboldCpp 與 Draw Things 留在你選擇的遊戲電腦。這個版本沒有雲端帳戶／雲端存檔，不把 Python 常駐工作搬進 Vercel Functions。

## 在這部 Mac 使用

1. 啟動 KoboldCpp（預設 `http://127.0.0.1:5001`）與選用的 Draw Things（預設 `http://127.0.0.1:7860`）。
2. 雙擊 `Start_Taleoria.command`，打開本機設定。
3. 在「從其他電腦遊玩」加入你的完整 Vercel 網址，例如 `https://你的網站.vercel.app`，按「允許這個網站」。只有明確加入的網站可跨來源連接。
4. 安裝官方 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)，雙擊 `Start_Remote_Taleoria.command`。它只為 Taleoria 提供 HTTPS 通道，不公開 KoboldCpp 或 Draw Things 端口。
5. 本機設定會顯示遊戲電腦的遠端網址與配對碼；Vercel 設定填入這兩項，再按「儲存並連線」。配對碼只保存在目前瀏覽器，從未寫入公開設定或網址。

遠端通道開著時，這部 Mac 必須保持開機、網路暢通。Cloudflare Quick Tunnel 是暫時網址：重啟通道通常會換網址，需更新 Vercel 設定。它適合目前的個人測試，沒有可用性保證；長期服務應使用具固定網域的 named tunnel。

## 回家換另一部模型電腦

在家中電腦安裝此專案並運行自己的模型，重做上述本機配對與遠端通道步驟。然後在 Vercel → 設定更改「遊戲電腦網址、配對碼」。文字模型欄位由那部電腦連線，`127.0.0.1` 指遊戲電腦；可改成當地 KoboldCpp 的其他端口。Draw Things 網址亦由那部電腦連接。

切換電腦會顯示該電腦的存檔；不會自動同步上一部的故事。完整搬機仍可複製 data；目前下載的 `.rpgsave` 尚未包含圖片。

也可直接填入開啟網頁那部電腦的 `http://127.0.0.1:8787` 並配對；是否允許 HTTPS 網頁讀取本機網路，取決於瀏覽器的本機網路權限。跨電腦測試建議使用 HTTPS 通道。

## 發佈

- 儲存庫：[bennycheung1019/taleoria](https://github.com/bennycheung1019/taleoria)。
- Vercel 匯入此 GitHub repo，Framework 選 Other，讀取 `vercel.json`。
- 建置命令：`python3 scripts/build_web.py`；輸出：`web-dist`。
- `web-defaults.json` 只允許預設 companion_url 與 model_url，不能放配對碼或其他金鑰。
- `.gitignore`／`.vercelignore` 排除 data、models、私人設定、工作檔、備份及環境金鑰。靜態建置另採明確檔案清單；沒有本機資料會進入網站輸出。
- 連接 Git 整合後，main 更新可觸發 Vercel 發佈。部署登入憑證由 Vercel 管理，不提交到 repo。

Companion 每次遠端讀寫都要求配對碼，限制跨來源網站，不公開本機 HTML 中的操作 token，拒絕遠端查閱私密 GM 端點；圖片亦經相同驗證後讀取。這是個人的單一遊戲電腦，不是多租戶付費平台。

參考：[Vercel CLI 部署](https://vercel.com/docs/projects/deploy-from-cli)、[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)、[Chrome 本機網路權限](https://developer.chrome.com/blog/local-network-access)。
