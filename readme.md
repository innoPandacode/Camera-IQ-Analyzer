# IQ Analyzer 📷📊

IQ Analyzer 是一套專為影像品質（Image Quality, IQ）測試設計的自動化數據分析與判讀工具。
本程式透過動態錨點（Anchor-based）技術掃描 Imatest 或其他儀器輸出的 CSV 報表，自動萃取關鍵數據、套用內建 Spec 進行 Pass/Fail 判定，並支援「三戰兩勝」驗證機制。

---

## ✨ 核心功能 (Features)

* **動態錨點定位 (Dynamic Anchor Extraction)**
  利用關鍵字作為錨點定位數據，提升不同 CSV 格式的容錯能力。

* **三戰兩勝判定機制 (Best 2 out of 3)**
  當同一測項有三次以上結果時，兩次 PASS 即為最終 PASS；不足三次時，只要有 FAIL 即判定 FAIL。

* **白盒化分析詳情 (Traceability Log)**
  提供完整數據來源、計算過程與判斷依據。

* **GUI 操作介面**
  支援表格高亮顯示、一鍵複製與 CSV 匯出。

---

## 📋 測試規格 (Test Specifications)

共內建 17 項測試項目，涵蓋 Color、WB、SNR、Shading、DR、MTF 等指標。

| ID | Item           | Light | Anchor                         | Target   | Spec    | Type           |
| -- | -------------- | ----- | ------------------------------ | -------- | ------- | -------------- |
| 1  | Color Accuracy | A     | A175 = "Max Delta-C_00 uncorr" | B175     | <= 18   | single         |
| 2  | Color Accuracy | CWF   | A175 = "Max Delta-C_00 uncorr" | B175     | <= 15   | single         |
| 3  | Color Accuracy | D65   | A175 = "Max Delta-C_00 uncorr" | B175     | <= 15   | single         |
| 4  | Mean Chroma    | A     | A151 = "Mean camera chroma %"  | B151     | 85~130% | single         |
| 5  | Mean Chroma    | CWF   | A151 = "Mean camera chroma %"  | B151     | 85~130% | single         |
| 6  | Mean Chroma    | D65   | A151 = "Mean camera chroma %"  | B151     | 85~130% | single         |
| 7  | White Balance  | A     | M11 = "WB Delta-C 00"          | M13-15   | < 7     | multi_max      |
| 8  | White Balance  | CWF   | M11 = "WB Delta-C 00"          | M13-15   | < 7     | multi_max      |
| 9  | White Balance  | D65   | M11 = "WB Delta-C 00"          | M13-15   | < 7     | multi_max      |
| 10 | SNR            | D65   | F102 = "Y-SNR(dB)"             | F103-122 | INFO    | snr_max        |
| 11 | Y Shading      | 6500K | A18                            | B18      | > 85%   | single         |
| 12 | Color Shading  | 3000K | A64                            | A65-C65  | < 5%    | shading_diff   |
| 13 | Color Shading  | 4000K | A64                            | A65-C65  | < 5%    | shading_diff   |
| 14 | Color Shading  | 5000K | A64                            | A65-C65  | < 5%    | shading_diff   |
| 15 | Color Shading  | 6500K | A64                            | A65-C65  | < 5%    | shading_diff   |
| 16 | Dynamic Range  | D65   | D129                           | D132     | INFO    | conditional_dr |
| 17 | MTF50P         | D65   | C欄 = "14 Y"                    | J欄       | INFO    | mtf_multi_row  |

---

## 🔍 抓取邏輯 (Extraction Types)

### single

直接抓取單一數值。

* 特例：Mean Chroma < 2 時自動轉為百分比。

### multi_max

多點取最大值後比對 Spec。

### shading_diff

計算偏差值：

```
abs(1 - ratio) * 100
```

取最大偏差。

### snr_max

在範圍內取最大值。

### conditional_dr

先檢查條件，再抓取數值。

### mtf_multi_row

逐列掃描關鍵字並抓取對應數值。

---

## 📂 資料夾結構 (Folder Structure)

需依光源分類資料夾：

```
Test_Data_Folder/
├── D65/
├── CWF/
└── 3000/
```

支援關鍵字：A, CWF, D65, 3000, 4000, 5000, 6500

---

## 🚀 使用方式 (Usage)

### 1. 安裝

```
pip install pandas ttkbootstrap tksheet
```

### 2. 執行

```
python analyzer.py
```

### 3. 操作流程

1. 選擇資料夾
2. 檢視總結報表
3. 查看分析詳情
4. 複製或匯出結果

---

## 📌 說明

* 本工具適用於 Imatest CSV 分析
* 支援多次測試結果整合
* 提供完整數據可追溯性

---

## 📬 聯絡

如需擴充 Spec 或客製化功能，請聯絡開發者。
