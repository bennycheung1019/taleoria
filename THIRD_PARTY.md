# 第三方軟件、模型與規則

Taleoria 新實作程式使用 MIT，保留原 `Kobold RPG contributors` 版權聲明。第三方模型及應用不隨安裝包分發，其授權不因本專案 MIT 而改變。

| 項目 | 來源及授權 |
| --- | --- |
| RPG OS v1.01，croatianrdy2defend-create | [原專案](https://github.com/croatianrdy2defend-create/RPG-OS)；核心規則、協定與改編文件概念使用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，原文與授權保存在 `rules/rpg_os_v1_01/` |
| KoboldCpp | [官方專案](https://github.com/LostRuins/koboldcpp)，依該專案及其依賴授權使用 |
| Qwen3.5-9B-Uncensored-HauhauCS-Aggressive | [模型作者頁](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive)，模型頁標示 Apache 2.0；以下載時授權為準 |
| DreamShaper XL Lightning，Lykon | [模型作者頁](https://huggingface.co/Lykon/dreamshaper-xl-lightning)，模型頁標示 OpenRAIL++；需遵守模型／基礎模型條款 |
| Draw Things | [官方網站](https://drawthings.ai/)，應用及任何服務依官方條款使用 |
| Python | [官方授權](https://docs.python.org/3/license.html) |

本專案改編 RPG OS 的 Understand → Establish → Resolve → Portray、Freeform 裁定、玩家主導選擇、NPC 個人基礎及五欄互動狀態等概念，翻譯、節錄並改以 SQLite 保存；不代表原作者背書。沒有把原戰役或原 runtime helper 程式當成本專案新實作。

Taleoria 只是透過本機 HTTP 與外部程式溝通，沒有把這些外部應用或模型權重包進程式。分發前請保留本文件、LICENSE 及 rules 中原授權。
