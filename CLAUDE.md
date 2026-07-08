# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

Camera IQ Analyzer — 讀取 Imatest 輸出的 CSV，自動判定影像品質測試結果（PASS/FAIL），並以 GUI 呈現。同時包含 AETool（AE/AWB 曝光平衡驗證工具）。

## 執行方式

```powershell
# 在 venv 環境下執行主程式
.\venv\Scripts\activate
python "Camera IQ Analyzer.py"
```

- GUI 依賴 tkinter / ttkbootstrap / customtkinter，**只能在 Windows 環境測試**
- 無自動化測試框架，功能驗證需手動操作 GUI

## 打包成 .exe

```powershell
.\venv\Scripts\activate
python -m PyInstaller --clean --onedir --windowed --noupx `
    --name "CameraIQAnalyzer" `
    --icon "ImatestAnalyzer_icon.ico" `
    --add-data "ImatestAnalyzer_icon.ico;." `
    "Camera IQ Analyzer.py"
```

**必須用此完整指令**，不可改用 `.spec` 檔直接執行——`--noupx` 和 `--onedir` 組合是避免防毒軟體誤判的關鍵。輸出在 `dist/CameraIQAnalyzer/`。

## 套件版本依賴

套件版本直接影響 GUI 行為，不可隨意升版：

| 套件 | 版本 | 備註 |
|------|------|------|
| ttkbootstrap | 1.20.2 | 主題樣式基礎 |
| tksheet | 7.6.0 | 資料表格 widget |
| openpyxl | 3.1.5 | Excel 輸出 |
| Pillow | 12.2.0 | 影像顯示 |

升版前需手動驗證 GUI 外觀與功能。

## CSV 解析邏輯注意事項

- 使用**動態錨點定位**：掃描 CSV 儲存格尋找特定字串（如 `"A175"`），再根據相對偏移讀取數值
- 此邏輯非常脆弱，Imatest 版本更新若改變輸出格式，錨點座標會失效
- **不可重構或抽象化錨點邏輯**，除非完整理解對應的 Imatest CSV 欄位規格
- 三戰兩勝判定：同一測項 3 次測試中 2 次 PASS 則整體判定為 PASS

## 程式碼風格

- Python 3.10+，遵守 PEP 8，以 Black 格式化為準
- 型別提示優先、`snake_case` 變數、`PascalCase` 類別
- 繁體中文 docstring 與行內註解
