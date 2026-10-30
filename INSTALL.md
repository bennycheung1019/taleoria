# Taleoria 安裝指南

這份指南以 **Apple Silicon Mac（M1／M2／M3 或更新）** 為主，使用與目前相同的文字及圖像模型。16GB 可先試用；關閉其他大型程式，文字及生圖順序執行。預留約 25GB 可用空間供下載、模型匯入和圖片；這是起步建議，並非記憶體或空間保證。

## 1. 放好 Taleoria，安裝 Python

1. 將 `Taleoria.zip` 解壓，得到 `Taleoria` 資料夾；放在你有權寫入的位置，例如「文件」。
2. 從 [Python 官方網站](https://www.python.org/downloads/macos/) 安裝 **Python 3.11 或以上**。
3. 不需要安裝任何 pip 套件，也不需要 npm。

若要延續自己的故事，改用私人備份包，或依照 [搬機說明](docs/PORTABILITY.md) 複製原本的 `data/`。

## 2. 安裝文字模型

1. 從 [KoboldCpp 官方 Releases](https://github.com/LostRuins/koboldcpp/releases/latest) 下載 `koboldcpp-mac-arm64`。請使用支援 Qwen3.5 的近期版本；此整理階段官方最新版為 1.123.1。
2. 下載 **[Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf?download=true)**，約 5.6GB。[作者與其他版本](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive)。
3. 把 GGUF 放在 `Taleoria/models/` 或其他方便的位置。Taleoria 目前只傳文字，**不用下載 mmproj、BF16、Q6 或 Q8**。
4. 第一次啟動 KoboldCpp：在終端輸入 `chmod +x `，將下載的 `koboldcpp-mac-arm64` 拖入終端，按 Enter；再把它拖入終端一次並按 Enter。若 macOS 阻擋，依 [Apple 官方說明](https://support.apple.com/102445) 檢查來源後於「隱私權與安全性」允許開啟。
5. 在 KoboldCpp 選取剛才的 GGUF；使用 **Metal** 加速。M1 Pro 16GB 可先用 **8192 context**；若記憶體吃緊，改為 4096。不要直接使用模型宣傳的最大 context。
6. Port 設為 **5001**，啟動模型服務並保持運行。你應能開啟 <http://127.0.0.1:5001/api/v1/model>，看見 Qwen 模型名稱。

這是目前使用的低拒答模型；作者的「Uncensored」名稱不保證所有輸出都不受限制，也不代表模型答案可靠。Taleoria 會自行設定回合生成參數。

## 3. 安裝圖片生成（可選）

1. 下載並打開 **[Draw Things](https://drawthings.ai/downloads/)**，完成首次必要下載。
2. 下載 **[DreamShaperXL_Lightning.safetensors](https://huggingface.co/Lykon/dreamshaper-xl-lightning/resolve/main/DreamShaperXL_Lightning.safetensors?download=true)**，約 6.94GB。[作者頁面](https://huggingface.co/Lykon/dreamshaper-xl-lightning)。這是目前選用的普通 Lightning 版，檔名**沒有 `-SFW`**。
3. 在 Draw Things 的模型選單使用 Import／匯入，選取此檔案，完成轉換後選擇 `DreamShaperXL_Lightning`。名稱可能顯示為 `dreamshaperxl_lightning_f16.ckpt`。
4. Draw Things → Advanced → API Server，設定：

| 選項 | 值 |
| --- | --- |
| Protocol | HTTP |
| Server Online | 開啟 |
| IP／Bind address | `127.0.0.1`（localhost only） |
| Port | `7860` |
| Bridge Mode | 關閉 |

5. 模型設定先用 **4 steps、CFG 2、DPM++ SDE Karras、Batch 1**；關閉額外放大、Hires 和 Refiner。Taleoria 會在請求中指定這些生成參數，模型沿用 Draw Things 選定的模型。

場景 1024×768、肖像 768×1024、物品 768×768。未開啟 Draw Things 時仍能玩文字故事。16GB 記憶體若不足，可先停用生圖、縮短文字 context，或分開載入兩個模型；Taleoria 不會自動卸載模型。

## 4. 啟動 Taleoria 並確認連線

1. 確認 KoboldCpp 已載入模型；要生圖時也保持 Draw Things 開啟。
2. 雙擊 `Start_Taleoria.command`。若不能雙擊，開啟終端，輸入 `python3 `，拖入資料夾中的 `taleoria.py`，按 Enter。
3. 瀏覽器會自動打開 <http://127.0.0.1:8787/>；不會自動打開時，手動開啟此網址。**不要直接雙擊 ui.html**。
4. 進入設定，檢查文字模型連線；「插畫」網址填 `http://127.0.0.1:7860`，按「儲存並測試連線」。
5. 可建立自己的新世界；在場景、人物或背包卡上按生圖圖示。圖片和故事會自動保存於 `data/`。

每次使用的順序：**KoboldCpp → Draw Things（可選）→ Taleoria**。結束時在 Taleoria 終端按 Ctrl+C，待停止後再關閉終端。

## 5. 另一部電腦使用不同連接埠時

預設連接埠相同便不用修改。需要變更時，把 `taleoria.example.json` 複製成 `taleoria.local.json`，用文字編輯器修改：

```json
{
  "port": 8787,
  "db": "data/mistbridge.sqlite3",
  "model_url": "http://127.0.0.1:5001"
}
```

- `port`：Taleoria 網站的連接埠；修改後用新網址開啟。
- `db`：起始資料庫；相對於 Taleoria 資料夾。**搬自己的備份時保留原值，隨意改成另一個檔名會開啟另一份遊戲**。
- `model_url`：該電腦 KoboldCpp 的本機網址，不加 `/v1` 或其他路徑。
- 修改以上檔案後重啟 Taleoria。Draw Things 的網址則直接在網站「插畫」設定中修改。

## 遇到問題

| 情況 | 做法 |
| --- | --- |
| 網站開不到／port 已佔用 | 先關閉舊 Taleoria；只保留一個正式服務。仍衝突時修改 `port` |
| 文字模型未連接 | 確認 KoboldCpp 已載入 GGUF、port 正確；Ollama 的 11434 不能直接代替這個 KoboldCpp 整合 |
| 生圖未連接 | 確認 Draw Things 用 HTTP、Server Online 開啟、port 7860、已選好模型 |
| 不同分頁的故事不同 | 同網址的分頁需要重新整理；8787 和 8797 是不同服務。建議用一個分頁遊玩 |
| 模型很慢或記憶體不足 | 關閉大型程式，降低文字 context，分開使用文字與圖片；不要一次生成多張或放大 |
| 搬機後像全新遊戲 | 確認複製了整個 `data/`，以及私人設定的 `db` 正確；只複製 `.rpgsave` 不含圖片 |

可在 Taleoria 資料夾執行 `python3 scripts/check_setup.py`，它只檢查設定與連線，不推進故事。

## Windows／Linux

文字程式沒有第三方 Python 依賴：安裝 Python 3.11+、下載對應平台的 [KoboldCpp](https://github.com/LostRuins/koboldcpp/releases/latest) 並載入相同 GGUF。Windows 雙擊 `Start_Taleoria.bat`；Linux 執行 `sh start_taleoria.sh` 或 `python3 server.py`。

**本階段完整生圖指南及實機驗證限 Apple Silicon Mac。** Draw Things 桌面 app 不適用 Windows；其他提供 `/sdapi/v1/options`、`/sdapi/v1/txt2img` 的 SDXL 本機服務可能相容，但尚未實測，不能視為即裝即用。純文字遊玩不需要安裝圖像模型。

下載來源核對日期：2026-10-30。模型與第三方程式的授權各自適用，詳見 [THIRD_PARTY.md](THIRD_PARTY.md)。
