# Camera IQ Analyzer

**Version: 20260608**

Imatest 影像品質測試結果自動判定工具。讀取 Imatest 輸出的 CSV 與 AE 報告，自動計算 PASS/FAIL，並以 GUI 呈現結果與詳細分析紀錄。

---

## 功能概覽

| 功能 | 說明 |
|------|------|
| 自動掃描 | 選擇測試資料夾後，自動遞迴尋找符合條件的 CSV 與 AE txt |
| 三戰兩勝判定 | 同一測項 3 次測試中 ≥2 次 PASS 則整體判定為 PASS |
| 檔案設定 | 以測試項目為單位，手動指定每輪使用的 CSV／AE txt，不受資料夾結構限制 |
| AE 分析 | 解析 `AE_Report_Data_*.txt`，判定曝光一致性（Avg ±5%） |
| 報表匯出 | 下載含總結報表與分析詳情的 `.xlsx` |
| 複製結果 | 一鍵複製 TSV 格式，可直接貼入 Excel |

---

## 測試項目（共 18 項）

| # | 測項名稱 | 燈光條件 | Spec |
|---|---------|---------|------|
| 1 | Color Accuracy | A/Fixed | ≤18 |
| 2 | Color Accuracy | CWF/600lux | ≤15 |
| 3 | Color Accuracy | D65/Fixed | ≤15 |
| 4 | Mean Chroma | A/Fixed | 85~130% |
| 5 | Mean Chroma | CWF/600lux | 85~130% |
| 6 | Mean Chroma | D65/Fixed | 85~130% |
| 7 | White Balance | A/Fixed | <7 |
| 8 | White Balance | CWF/600lux | <7 |
| 9 | White Balance | D65/Fixed | <7 |
| 10 | SNR | D65/600Lux | INFO |
| 11 | Y Shading | 6500K/1000lux | >85% |
| 12 | Color Shading | 3000K/1000lux | <5% |
| 13 | Color Shading | 4000K/1000lux | <5% |
| 14 | Color Shading | 5000K/1000lux | <5% |
| 15 | Color Shading | 6500K/1000lux | <5% |
| 16 | Dynamic Range | D65/600Lux | INFO |
| 17 | MTF50P | D65/600Lux | INFO |
| 18 | AE | 4870K | Avg ±5% |

> **INFO 項目**（10、16、17）：僅記錄數值，不參與 PASS/FAIL 判定。

---

## 操作流程

### 標準流程

1. 點擊「**選擇測試資料夾**」
2. 程式自動掃描 CSV 與 AE txt，執行分析並停在「**總結報表**」
3. 綠色 = PASS，紅色 = FAIL
4. 切到「**分析詳情**」可查看每個測項的錨點、原始值、計算過程

### 手動指定檔案（適用於需要選取特定輪次的情境）

> 例：做了 5 次測試，但只想取第 1、4、5 次的結果。

1. 先完成「選擇測試資料夾」（自動填入預設分配）
2. 切到「**檔案設定**」Tab
3. 找到目標測項與對應輪次，點「**選擇檔案**」從檔案總管指定 CSV
4. AE 區段同樣可指定 `.txt` 檔
5. 按「**✕**」可清空不需要的輪次（不計入該輪判定）
6. 點「**套用並更新報表**」→ 自動切回總結報表，分析詳情同步更新

---

## Tab 說明

| Tab | 功能 |
|-----|------|
| 總結報表 | 18 項測試數值（最多三輪）與最終 Result |
| AE 分析 | 載入影像分析曝光一致性，結果自動寫入總結報表第 18 列 |
| 檔案設定 | 以測試項目分組，每輪可獨立選擇 CSV／AE txt 或清空 |
| 分析詳情 | JSON 格式完整分析 log，含錨點座標、原始值、計算過程 |

---

## 資料夾結構要求（自動掃描模式）

CSV 必須放在含有燈光條件名稱的子資料夾內：

```
測試資料夾/
├── A/                        ← A/Fixed
│   ├── run1.csv
│   ├── run2.csv
│   └── run3.csv
├── CWF/                      ← CWF/600lux
├── D65/                      ← D65/Fixed
├── 3000/                     ← 3000K/1000lux
├── 4000/
├── 5000/
├── 6500/                     ← Y Shading & Color Shading
└── （任意路徑）/
    └── AE_Report_Data_*.txt  ← AE 報告，遞迴搜尋
```

> 若結構不符，請改用「**檔案設定**」Tab 手動指定。

---

## 環境需求

| 項目 | 版本 |
|------|------|
| Python | 3.12 |
| ttkbootstrap | 1.20.2 |
| tksheet | 7.6.0 |
| openpyxl | 3.1.5 |
| Pillow | 12.2.0 |
| pandas | — |
| opencv-python | — |
| numpy | — |

> 套件版本直接影響 GUI 行為，升版前需手動驗證外觀與功能。

---

## 執行方式

```powershell
.\venv\Scripts\activate
python "Camera IQ Analyzer.py"
```

---

## 打包成 .exe

```powershell
.\venv\Scripts\activate
python -m PyInstaller --clean --onedir --windowed --noupx `
    --name "CameraIQAnalyzer" `
    --icon "ImatestAnalyzer_icon.ico" `
    --add-data "ImatestAnalyzer_icon.ico;." `
    "Camera IQ Analyzer.py"
```

輸出位置：`dist\CameraIQAnalyzer\CameraIQAnalyzer.exe`

> `--noupx` 與 `--onedir` 組合為必要參數，可避免防毒軟體誤判，請勿改用 `.spec` 檔直接執行。

---

## 注意事項

- **CSV 解析使用動態錨點定位**：依特定儲存格字串定位數值，Imatest 版本更新若改變輸出格式，錨點可能失效，需同步修改對應規則
- **GUI 僅支援 Windows**：依賴 tkinter，不支援 Linux／macOS
- **AE 分析模組獨立**：AE Tab 的分析結果在同 session 內會暫存，重新選擇資料夾後自動以資料夾內 txt 為準
