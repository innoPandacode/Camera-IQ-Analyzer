import os
import sys
import ctypes
import re
import csv
import json
import pandas as pd
from enum import Enum
from datetime import datetime
from typing import List, Dict, Any, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tksheet import Sheet

# ==========================================
# 解決 ScrolledText 匯入相容性問題
# ==========================================
try:
    from ttkbootstrap.widgets import ScrolledText
except ImportError:
    try:
        from ttkbootstrap.scrolled import ScrolledText
    except ImportError:
        from tkinter.scrolledtext import ScrolledText

# ==========================================
# 1. 核心定義與規格
# ==========================================
APP_NAME = "Camera IQ Analyzer"
VERSION = "20260521"
ICON_NAME = "ImatestAnalyzer_icon.ico"

class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFO = "INFO"
    UNDEFINED = "UNDEFINED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"

LIGHT_MAP = {
    "A": "A/Fixed", "CWF": "CWF/600lux", "D65": "D65/Fixed",
    "3000": "3000K/1000lux", "4000": "4000K/1000lux", 
    "5000": "5000K/1000lux", "6500": "6500K/1000lux"
}

TEST_RULES = [
    {"id": 1, "name": "Color Accuracy", "light": "A", "type": "single", "anchor": ("A175", "Max   Delta-C_00 uncorr"), "target": "B175", "spec": 18, "criteria": "<=18"},
    {"id": 2, "name": "Color Accuracy", "light": "CWF", "type": "single", "anchor": ("A175", "Max   Delta-C_00 uncorr"), "target": "B175", "spec": 15, "criteria": "<=15"},
    {"id": 3, "name": "Color Accuracy", "light": "D65", "type": "single", "anchor": ("A175", "Max   Delta-C_00 uncorr"), "target": "B175", "spec": 15, "criteria": "<=15"},
    {"id": 4, "name": "Mean Chroma", "light": "A", "type": "single", "anchor": ("A151", "Mean camera chroma %"), "target": "B151", "spec": (85, 130), "criteria": "85~130%", "scale": True},
    {"id": 5, "name": "Mean Chroma", "light": "CWF", "type": "single", "anchor": ("A151", "Mean camera chroma %"), "target": "B151", "spec": (85, 130), "criteria": "85~130%", "scale": True},
    {"id": 6, "name": "Mean Chroma", "light": "D65", "type": "single", "anchor": ("A151", "Mean camera chroma %"), "target": "B151", "spec": (85, 130), "criteria": "85~130%", "scale": True},
    {"id": 7, "name": "White Balance", "light": "A", "type": "multi_max", "anchor": ("M11", "WB Delta-C 00"), "target": ["M13", "M14", "M15"], "spec": 7, "criteria": "< 7"},
    {"id": 8, "name": "White Balance", "light": "CWF", "type": "multi_max", "anchor": ("M11", "WB Delta-C 00"), "target": ["M13", "M14", "M15"], "spec": 7, "criteria": "< 7"},
    {"id": 9, "name": "White Balance", "light": "D65", "type": "multi_max", "anchor": ("M11", "WB Delta-C 00"), "target": ["M13", "M14", "M15"], "spec": 7, "criteria": "< 7"},
    {"id": 10, "name": "SNR", "light": "D65", "type": "snr_max", "anchor": ("F102", "Y-SNR(dB)"), "target": "F103:F122", "spec": None, "criteria": "-"},
    {"id": 11, "name": "Y Shading", "light": "6500", "type": "single", "anchor": ("A18", "Worst corner level/max pixel level (%)"), "target": "B18", "spec": 85, "criteria": "> 85%"},
    {"id": 12, "name": "Color Shading", "light": "3000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 13, "name": "Color Shading", "light": "4000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 14, "name": "Color Shading", "light": "5000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 15, "name": "Color Shading", "light": "6500", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 16, "name": "Dynamic Range", "light": "D65", "type": "conditional_dr", "anchor": ("D129", "DR (dB)"), "cond": ("B132", "LOW"), "target": "D132", "spec": None, "criteria": "-"},
    
    # [修改這裡] 針對 MTF50P 設定特殊規則：以 C 欄找 "14 Y"，並去 J 欄拿值
    {"id": 17, "name": "MTF50P", "light": "D65", "type": "mtf_multi_row", "anchor": ("C", ["14 Y", "14 L"]), "target": "J", "spec": None, "criteria": "-"}
]

# ==========================================
# 2. 處理類別
# ==========================================
class Reader:
    @staticmethod
    def excel_to_index(coord: str) -> Tuple[int, int]:
        match = re.match(r"([A-Z]+)([0-9]+)", coord.upper())
        c, r = match.groups()
        col = sum((ord(char) - 64) * (26 ** i) for i, char in enumerate(reversed(c))) - 1
        return int(r) - 1, col

class Extractor:
    def __init__(self): self.reader = Reader()

    def process_all(self, files_df: pd.DataFrame) -> Tuple[List[Dict], List[Dict]]:
        summary_res, detail_logs = [], []
        file_contents = {}
        for _, f in files_df.iterrows():
            try:
                with open(f['path'], 'r', encoding='utf-8-sig', errors='ignore') as csvfile:
                    file_contents[f['path']] = list(csv.reader(csvfile))
            except: continue

        for rule in TEST_RULES:
            l_display = LIGHT_MAP.get(rule["light"], rule["light"])
            item_full = f"{rule['id']}. {rule['name']} ({l_display})"
            eligible_files = []
            
            # --- 篩選符合條件的 CSV 檔案 ---
            for path, rows in file_contents.items():
                if rule["light"].upper() not in [p.upper() for p in os.path.normpath(path).split(os.sep)]: continue
                
                # 若為 mtf_multi_row，只要 C 欄出現 "14 Y" 就把此檔案加入 (不用限定在哪一列)
                if rule["type"] == "mtf_multi_row":
                    a_col, a_key = rule["anchor"]
                    c_idx = self.reader.excel_to_index(a_col + "1")[1] # 取得欄位 Index
                    anchor_values = a_key if isinstance(a_key, list) else [a_key]
                    if any(len(r) > c_idx and str(r[c_idx]).strip() in anchor_values for r in rows):
                        file_info = files_df[files_df['path'] == path].iloc[0]
                        eligible_files.append({"path": path, "rows": rows, "ctime": file_info['ctime'], "name": file_info['name']})
                else:
                    a_coord, a_key = rule["anchor"]; r, c = self.reader.excel_to_index(a_coord)
                    if len(rows) > r and len(rows[r]) > c and str(rows[r][c]).strip() == a_key:
                        file_info = files_df[files_df['path'] == path].iloc[0]
                        eligible_files.append({"path": path, "rows": rows, "ctime": file_info['ctime'], "name": file_info['name']})
            
            eligible_files = sorted(eligible_files, key=lambda x: x["ctime"])
            if not eligible_files:
                summary_res.append({"項目": item_full, "Spec": rule["criteria"], "結果類型": "測試結果", "判定值": "- -", "結論": "--"})
                continue

            # --- [新增邏輯] 處理 MTF50P (同檔多列搜尋) ---
            if rule["type"] == "mtf_multi_row":
                for finfo in eligible_files:
                    rows = finfo["rows"]
                    c_idx = self.reader.excel_to_index(rule["anchor"][0] + "1")[1]
                    j_idx = self.reader.excel_to_index(rule["target"] + "1")[1]
                    
                    match_count = 0
                    anchor_values = rule["anchor"][1] if isinstance(rule["anchor"][1], list) else [rule["anchor"][1]]
                    for r_idx, row in enumerate(rows):
                        if len(row) > c_idx and str(row[c_idx]).strip() in anchor_values:
                            raw_val = row[j_idx] if len(row) > j_idx else None
                            val = self._clean_num(raw_val)
                            
                            label = "測試結果" if match_count == 0 else f"複測結果{match_count}"
                            res = {"判定值": f"{val:.2f}" if val is not None else "- -", "結論": Status.INFO.value}
                            res.update({"項目": item_full, "Spec": rule["criteria"], "結果類型": label})
                            
                            log = {
                                "CSV檔名": finfo["name"],
                                "抓取類型": rule["type"],
                                "錨點確認": f"座標 {rule['anchor'][0]}{r_idx+1} = '{rule['anchor'][1]}'",
                                "目標範圍": f"{rule['target']}{r_idx+1}",
                                "取值過程": [{
                                    "座標": f"{rule['target']}{r_idx+1}", 
                                    "原始值": raw_val, 
                                    "轉換後數值": val, 
                                    "計算過程": "同檔案由上往下依序掃描"
                                }]
                            }
                            summary_res.append(res)
                            detail_logs.append({"測項 (Item)": item_full, "階段 (Stage)": label, "分析詳情 (Details)": log})
                            match_count += 1
                continue # 處理完畢直接跳下一規則，不執行後面的標準邏輯

            # --- 處理一般測項 (多檔案，每檔只有一個結果) ---
            for idx, finfo in enumerate(eligible_files):
                label = "測試結果" if idx == 0 else f"複測結果{idx}"
                data, details = self._extract_logic(rule, finfo)
                data.update({"項目": item_full, "Spec": rule["criteria"], "結果類型": label})
                summary_res.append(data)
                
                detail_logs.append({
                    "測項 (Item)": item_full,
                    "階段 (Stage)": label,
                    "分析詳情 (Details)": details
                })
                
        return summary_res, detail_logs

    def _extract_logic(self, rule: Dict, finfo: Dict) -> Tuple[Dict, Dict]:
        res = {"判定值": "- -", "結論": "--"}
        rows = finfo["rows"]
        df_rows = pd.DataFrame(rows)
        
        log = {
            "CSV檔名": finfo["name"],
            "抓取類型": rule["type"],
            "錨點確認": f"座標 {rule['anchor'][0]} = '{rule['anchor'][1]}'",
            "目標範圍": rule["target"],
            "取值過程": []
        }

        try:
            val, unit, is_undefined = None, "", False
            if any(x in rule["name"] for x in ["Chroma", "Shading"]): unit = "%"
            elif "Dynamic Range" in rule["name"]: unit = " dB"

            if rule["type"] == "single":
                raw = self._get_v(rows, rule["target"])
                val = self._clean_num(raw, auto_scale=rule.get("scale", False))
                
                calc_step = "直接取值"
                if rule.get("scale") and val and raw:
                    raw_num = float(str(raw).replace('%', '').strip())
                    if 0 < raw_num < 2: calc_step = f"百分比轉換: {raw_num} * 100 = {val}"
                
                log["取值過程"].append({
                    "座標": rule["target"],
                    "原始值": raw,
                    "轉換後數值": val,
                    "計算過程": calc_step
                })

                if val is not None:
                    if rule["spec"] is None: res["結論"] = Status.INFO.value
                    elif isinstance(rule["spec"], tuple): res["結論"] = Status.PASS.value if rule["spec"][0] <= val <= rule["spec"][1] else Status.FAIL.value
                    elif "Accuracy" in rule["name"]: res["結論"] = Status.PASS.value if val <= rule["spec"] else Status.FAIL.value
                    else: res["結論"] = Status.PASS.value if val > rule["spec"] else Status.FAIL.value

            elif rule["type"] == "multi_max":
                vals = []
                for c in rule["target"]:
                    raw = self._get_v(rows, c)
                    cv = self._clean_num(raw)
                    log["取值過程"].append({"座標": c, "原始值": raw, "數值": cv})
                    if cv is not None: vals.append(cv)
                
                if vals: 
                    val = max(vals)
                    log["結果計算"] = f"取最大值: MAX({vals}) = {val}"
                    res["結論"] = Status.PASS.value if val < rule["spec"] else Status.FAIL.value

            elif rule["type"] == "shading_diff":
                diffs = []
                for coord in rule["target"]:
                    raw = self._get_v(rows, coord)
                    rv = self._clean_num(raw)
                    if rv is not None:
                        ratio = rv / 100.0 if rv > 2 else rv
                        diff_val = abs(1 - ratio) * 100
                        diffs.append(diff_val)
                        log["取值過程"].append({
                            "座標": coord,
                            "原始值": raw,
                            "計算過程": f"abs(1 - {ratio:.4f}) * 100 = {diff_val:.2f}%"
                        })
                if diffs: 
                    val = max(diffs)
                    log["結果計算"] = f"取最大偏差值: MAX({[round(d, 2) for d in diffs]}) = {val:.2f}%"
                    res["結論"] = Status.PASS.value if val < rule["spec"] else Status.FAIL.value

            elif rule["type"] == "snr_max":
                s, e = rule["target"].split(":")
                r1, c1 = self.reader.excel_to_index(s); r2, c2 = self.reader.excel_to_index(e)
                block = pd.to_numeric(df_rows.iloc[r1:r2+1, c1:c2+1].stack(), errors='coerce').dropna()
                log["取值過程"].append({
                    "搜尋範圍": rule["target"],
                    "範圍內有效數字格數": len(block)
                })
                if not block.empty: 
                    val = block.max()
                    log["結果計算"] = f"範圍內最大值 = {val}"
                    res["結論"] = Status.INFO.value

            elif rule["type"] == "conditional_dr":
                c_c, c_k = rule["cond"]
                raw_cond = self._get_v(rows, c_c)
                log["條件檢查"] = {
                    "條件座標": c_c,
                    "期望關鍵字": c_k,
                    "CSV實際值": raw_cond
                }
                if str(raw_cond).strip().upper() == c_k:
                    raw_val = self._get_v(rows, rule["target"])
                    val = self._clean_num(raw_val)
                    log["取值過程"].append({"座標": rule["target"], "原始值": raw_val, "轉換數值": val})
                    res["結論"] = Status.INFO.value
                else: 
                    is_undefined = True
                    log["結果計算"] = "條件不符，跳過抓取 (判定為 undefined)"
                    res["結論"] = Status.FAIL.value

            if rule["id"] in [10, 17] or (rule["id"] == 16 and not is_undefined): res["結論"] = Status.INFO.value
            
            if is_undefined: res["判定值"] = "undefined"
            elif val is not None: res["判定值"] = "{:.2f}{}".format(val, unit)
            else: res["判定值"] = "- -"
            if isinstance(res["結論"], Status): res["結論"] = res["結論"].value
        except Exception as e: 
            res["結論"] = "--"
            log["系統錯誤"] = str(e)
            
        return res, log

    def _get_v(self, rows, c):
        try:
            r, i = self.reader.excel_to_index(c)
            return rows[r][i] if r < len(rows) and i < len(rows[r]) else None
        except: return None

    def _clean_num(self, v, auto_scale=False):
        if v is None or str(v).strip() == "" or str(v).lower() == "nan": return None
        try:
            num = float(str(v).replace('%', '').strip())
            if auto_scale and 0 < num < 2: num *= 100
            return num
        except: return None

# ==========================================
# 3. UI 介面
# ==========================================
class Scanner:
    @staticmethod
    def scan_deep(root_dir: str) -> pd.DataFrame:
        found = []
        for root, _, files in os.walk(root_dir):
            parts = [p.upper() for p in os.path.normpath(root).split(os.sep)]
            light = next((l for l in LIGHT_MAP.keys() if l in parts), None)
            if not light: continue
            for f in files:
                if f.lower().endswith('.csv'):
                    p = os.path.join(root, f)
                    found.append({"light": light, "path": p, "ctime": os.path.getctime(p), "name": f})
        return pd.DataFrame(found).sort_values("ctime").reset_index(drop=True) if found else pd.DataFrame()

class AnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1000x640")
        self.summary_df = pd.DataFrame()
        self.detail_logs = []
        self._set_app_icon()
        self._build_ui()

    def _resource_path(self, relative_path):
        """
        讓開發環境與 PyInstaller 打包後都能正確找到資源檔。
        """
        if hasattr(sys, "_MEIPASS"):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        return os.path.join(base_path, relative_path)

    def _set_app_icon(self):
        """
        設定 Windows 視窗左上角 icon 與工作列 icon。
        """
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "innodisk.camera_iq_analyzer"
            )
        except Exception as e:
            print(f"設定 AppUserModelID 失敗: {e}")

        icon_path = self._resource_path(ICON_NAME)

        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception as e:
                print(f"載入圖示失敗: {e}")
        else:
            print(f"找不到圖示檔案: {icon_path}")

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(15, 10)); top.pack(side=TOP, fill=X)
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var, font=('Microsoft JhengHei', 10)).pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(top, text="選擇測試資料夾", command=self._run_analysis, bootstyle=PRIMARY).pack(side=LEFT, padx=10)

        bot = ttk.Frame(self.root, padding=(15, 8)); bot.pack(side=BOTTOM, fill=X)
        # 左下角 1：版本資訊 (最先 pack，所以會在最左邊)
        ttk.Label(bot, text=f"Version: {VERSION}", font=('Consolas', 10), foreground="gray").pack(side=LEFT, padx=(0, 15))
        # 左下角 2：狀態文字 (排在版本資訊的右邊)
        self.stat_lbl = ttk.Label(bot, text="狀態: 準備就緒", font=('Microsoft JhengHei', 10))
        self.stat_lbl.pack(side=LEFT)
        ttk.Button(bot, text="下載報表 (.xlsx)", command=self._download_csv, bootstyle=INFO).pack(side=RIGHT, padx=5)
        ttk.Button(bot, text="複製結果", command=self._copy_excel, bootstyle=SUCCESS).pack(side=RIGHT, padx=5)

        self.notebook = ttk.Notebook(self.root, bootstyle=INFO); self.notebook.pack(side=TOP, fill=BOTH, expand=True, padx=15, pady=5)
        self.tab_summary = ttk.Frame(self.notebook, padding=5); self.notebook.add(self.tab_summary, text=" 總結報表 ")
        self.tab_details = ttk.Frame(self.notebook, padding=5); self.notebook.add(self.tab_details, text=" 分析詳情 ")
        
        self.sheet = Sheet(self.tab_summary, headers=["項目", "Spec", "測試結果", "複測結果1", "複測結果2", "Result"],
                           header_font=("Microsoft JhengHei", 10, "bold"), font=("Microsoft JhengHei", 10, "normal"), row_height=25)
        self.sheet.pack(fill=BOTH, expand=True)
        self.sheet.enable_bindings("single_select", "drag_select", "row_select", "column_select", "copy", "arrowkeys")
        self.detail_text = ScrolledText(self.tab_details, padding=10, font=("Consolas", 10)); self.detail_text.pack(fill=BOTH, expand=True)

    def _run_analysis(self):
        path = filedialog.askdirectory()
        if not path: return
        self.path_var.set(path)
        self.sheet.set_sheet_data([]); self.sheet.dehighlight_all(); self.detail_text.delete('1.0', END)
        
        f_df = Scanner.scan_deep(path)
        raw_res, logs = Extractor().process_all(f_df)
        if not raw_res: return
        
        df_raw = pd.DataFrame(raw_res)
        pivot = df_raw.pivot_table(index=['項目', 'Spec'], columns='結果類型', values='判定值', aggfunc='first').reset_index()
        
        # 最終判定 (Result 欄位) 真正的三戰兩勝邏輯
        def judge_final(name):
            item_data = df_raw[df_raw['項目'] == name]
            concs = dict(zip(item_data['結果類型'], item_data['結論']))
            
            # INFO 類型的測項直接回傳 INFO
            if any(s in name for s in ["10. SNR", "16. Dynamic Range", "17. MTF50P"]): 
                return "INFO"

            # 計算 PASS 和 FAIL 的總數
            pass_count = list(concs.values()).count("PASS")
            fail_count = list(concs.values()).count("FAIL")

            # 1. 三戰兩勝機制：如果有測試到 3 次 (或以上)
            if (pass_count + fail_count) >= 3:
                if pass_count >= 2:
                    return "PASS"
                else:
                    return "FAIL"
            
            # 2. 測試次數不到 3 次的正常判定：
            # 只要有 FAIL 就判定 FAIL，否則有 PASS 就判定 PASS
            if fail_count > 0:
                return "FAIL"
            if pass_count > 0:
                return "PASS"
            
            return "--"

        pivot['Result'] = pivot['項目'].apply(judge_final)
        for c in ["測試結果", "複測結果1", "複測結果2"]:
            if c not in pivot.columns: pivot[c] = "- -"
        
        pivot = pivot.fillna("- -").replace("N/A", "- -")
        pivot['sk'] = pivot['項目'].apply(lambda x: int(x.split('.')[0]))
        self.summary_df = pivot.sort_values('sk').drop(columns=['sk'])[["項目", "Spec", "測試結果", "複測結果1", "複測結果2", "Result"]].reset_index(drop=True)

        self.sheet.set_sheet_data(self.summary_df.values.tolist())
        self.sheet.set_column_widths([300, 80, 110, 110, 110, 110])
        
        # --- 強制著色邏輯 ---
        color_red = "#dc3545"   # 明顯的紅色
        color_green = "#28a745" # 明顯的綠色

        # 2. 使用 enumerate 確保 row_idx 絕對是從 0 開始的連續整數，對齊 UI 表格
        for row_idx, (_, row) in enumerate(self.summary_df.iterrows()):
            item_name = row["項目"]
            
            # [處理 Result 總結欄位]
            final_res = row["Result"]
            if final_res == "PASS":
                self.sheet.highlight_cells(row=row_idx, column=5, fg=color_green)
            elif final_res == "FAIL":
                self.sheet.highlight_cells(row=row_idx, column=5, fg=color_red)

            # [處理數值欄位 (測試結果, 複測結果1, 複測結果2)]
            for c_idx, label in enumerate(["測試結果", "複測結果1", "複測結果2"], start=2):
                # 找到原始判定結論
                match = df_raw[(df_raw['項目'] == item_name) & (df_raw['結果類型'] == label)]
                if not match.empty:
                    c_status = match.iloc[0]['結論']
                    cell_val = str(row[label])
                    
                    if c_status == "FAIL" or cell_val == "undefined":
                        # 不合格：強制紅色 (移除了不支援的 font 參數)
                        self.sheet.highlight_cells(row=row_idx, column=c_idx, fg=color_red)
                    elif c_status == "PASS":
                        # 合格：強制綠色
                        self.sheet.highlight_cells(row=row_idx, column=c_idx, fg=color_green)
                    # INFO 或 "--" 保持預設黑字

        self.sheet.redraw()
        self.detail_logs = logs

        version_header = (
            f"{APP_NAME}\n"
            f"Version: {VERSION}\n"
            f"Generated Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'='*60}\n\n"
        )

        self.detail_text.insert(
            END,
            version_header + json.dumps(logs, indent=4, ensure_ascii=False)
        )

        self.stat_lbl.config(text=f"狀態: 分析完成")

    def _copy_excel(self):
        if self.summary_df.empty: return
        self.root.clipboard_clear(); self.root.clipboard_append(self.summary_df.to_csv(sep='\t', index=False, lineterminator='\n'))
        messagebox.showinfo("成功", "內容已複製。")

    def _download_csv(self):
        if self.summary_df.empty:
            return
        f = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel 活頁簿", "*.xlsx")],
            initialfile=f"Report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        )
        if not f:
            return
        try:
            log_rows = []
            for entry in self.detail_logs:
                log_rows.append({
                    "測項 (Item)": entry.get("測項 (Item)", ""),
                    "階段 (Stage)": entry.get("階段 (Stage)", ""),
                    "分析詳情 (Details)": json.dumps(entry.get("分析詳情 (Details)", {}), ensure_ascii=False, indent=2)
                })
            log_df = pd.DataFrame(log_rows)

            with pd.ExcelWriter(f, engine='openpyxl') as writer:
                self.summary_df.to_excel(writer, sheet_name='總結報表', index=False)
                log_df.to_excel(
                    writer,
                    sheet_name='分析詳情',
                    index=False,
                    startrow=4
                )

                ws_log = writer.sheets['分析詳情']

                ws_log['A1'] = APP_NAME
                ws_log['A2'] = f"Version: {VERSION}"
                ws_log['A3'] = f"Generated Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

                # 自動調整欄寬
                for sheet_name in writer.sheets:
                    ws = writer.sheets[sheet_name]
                    for col in ws.columns:
                        max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
                        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 80)

            messagebox.showinfo("成功", f"報表已儲存（含分析詳情）：\n{f}")
        except Exception as e:
            messagebox.showerror("錯誤", f"儲存失敗：{e}")

if __name__ == "__main__":
    app_root = ttk.Window(themename="cosmo")
    AnalyzerApp(app_root); app_root.mainloop()