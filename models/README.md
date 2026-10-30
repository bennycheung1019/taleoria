# 模型放哪裡？

模型不包含在程式包內，也不應提交到 GitHub。

- 文字模型：把 `Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` 放在此資料夾或任何位置，再在 KoboldCpp 選取它。
- 圖像模型：把 `DreamShaperXL_Lightning.safetensors` 匯入 Draw Things，由 Draw Things 管理轉換後模型。
- Taleoria 只連接本機服務，不會直接載入這些模型檔案。

下載連結及設定請看根目錄 [INSTALL.md](../INSTALL.md)。
