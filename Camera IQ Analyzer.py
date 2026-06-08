import os
import sys
import ctypes
import re
import csv
import json
import pandas as pd
import cv2
import numpy as np
import pyperclip
from PIL import Image, ImageDraw, ImageFont, ImageTk
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
    from ttkbootstrap.widgets.scrolled import ScrolledText
except ImportError:
    try:
        from ttkbootstrap.widgets import ScrolledText
    except ImportError:
        from tkinter.scrolledtext import ScrolledText

# ==========================================
# 1. 核心定義與規格
# ==========================================
APP_NAME = "Camera IQ Analyzer"
VERSION = "20260608"
ICON_NAME = "ImatestAnalyzer_icon.ico"


class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFO = "INFO"
    UNDEFINED = "UNDEFINED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"


LIGHT_MAP = {
    "A": "A/Fixed",
    "CWF": "CWF/600lux",
    "D65": "D65/Fixed",
    "3000": "3000K/1000lux",
    "4000": "4000K/1000lux",
    "5000": "5000K/1000lux",
    "6500": "6500K/1000lux",
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
    {"id": 10, "name": "SNR", "light": "D65", "display_light": "D65/600Lux", "type": "snr_max", "anchor": ("F102", "Y-SNR(dB)"), "target": "F103:F122", "spec": None, "criteria": "-"},
    {"id": 11, "name": "Y Shading", "light": "6500", "type": "single", "anchor": ("A18", "Worst corner level/max pixel level (%)"), "target": "B18", "spec": 85, "criteria": "> 85%"},
    {"id": 12, "name": "Color Shading", "light": "3000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 13, "name": "Color Shading", "light": "4000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 14, "name": "Color Shading", "light": "5000", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 15, "name": "Color Shading", "light": "6500", "type": "shading_diff", "anchor": ("A64", "Minimum ratio (9 regions) / maximum ratio (9 regions)"), "target": ["A65", "B65", "C65"], "spec": 5, "criteria": "< 5%"},
    {"id": 16, "name": "Dynamic Range", "light": "D65", "display_light": "D65/600Lux", "type": "conditional_dr", "anchor": ("D129", "DR (dB)"), "cond": ("B132", "LOW"), "target": "D132", "spec": None, "criteria": "-"},
    # MTF50P：以 C 欄找 "14 Y"/"14 L"，取 J 欄值
    {"id": 17, "name": "MTF50P", "light": "D65", "display_light": "D65/600Lux", "type": "mtf_multi_row", "anchor": ("C", ["14 Y", "14 L"]), "target": "J", "spec": None, "criteria": "-"},
]

# ==========================================
# 2. 處理類別
# ==========================================
class Reader:
    @staticmethod
    def excel_to_index(coord: str) -> Tuple[int, int]:
        match = re.match(r"([A-Z]+)([0-9]+)", coord.upper())
        if not match:
            raise ValueError(f"無效座標格式: {coord}")
        c, r = match.groups()
        col = sum((ord(char) - 64) * (26 ** i) for i, char in enumerate(reversed(c))) - 1
        return int(r) - 1, col


class Extractor:
    def __init__(self):
        self.reader = Reader()

    _ROUNDS = ["測試結果", "複測結果1", "複測結果2"]

    def process_all(
        self,
        files_df: pd.DataFrame,
        assignment: "Dict[int, Dict[str, str]] | None" = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """分析所有測項。assignment 提供時以 per-rule 明確分配為準，否則依 files_df 路徑推斷。"""
        summary_res, detail_logs = [], []
        file_contents: Dict[str, list] = {}

        # 從 files_df 載入
        for _, f in files_df.iterrows():
            try:
                with open(f["path"], "r", encoding="utf-8-sig", errors="ignore") as fh:
                    file_contents[f["path"]] = list(csv.reader(fh))
            except Exception:
                continue

        # 從 assignment 補充尚未載入的路徑
        if assignment:
            for round_map in assignment.values():
                for path in round_map.values():
                    if path and path not in file_contents:
                        try:
                            with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
                                file_contents[path] = list(csv.reader(fh))
                        except Exception:
                            continue

        for rule in TEST_RULES:
            l_display = rule.get("display_light") or LIGHT_MAP.get(rule["light"], rule["light"])
            item_full = f"{rule['id']}. {rule['name']} ({l_display})"

            # ── 明確分配模式 ──────────────────────────────────
            if assignment and rule["id"] in assignment:
                rule_assign = assignment[rule["id"]]
                if not rule_assign:
                    summary_res.append({"項目": item_full, "Spec": rule["criteria"], "結果類型": "測試結果", "判定值": "- -", "結論": "--"})
                    continue

                if rule["type"] == "mtf_multi_row":
                    c_idx = self.reader.excel_to_index(rule["anchor"][0] + "1")[1]
                    j_idx = self.reader.excel_to_index(rule["target"] + "1")[1]
                    anchor_values = rule["anchor"][1] if isinstance(rule["anchor"][1], list) else [rule["anchor"][1]]
                    anchor_display = ", ".join(anchor_values) if isinstance(anchor_values, list) else anchor_values
                    global_match = 0
                    seen: set = set()
                    for rl in self._ROUNDS:
                        path = rule_assign.get(rl)
                        if not path or path not in file_contents or path in seen:
                            continue
                        seen.add(path)
                        finfo = {"path": path, "rows": file_contents[path], "name": os.path.basename(path)}
                        for r_idx, row in enumerate(finfo["rows"]):
                            if len(row) > c_idx and str(row[c_idx]).strip() in anchor_values:
                                raw_val = row[j_idx] if len(row) > j_idx else None
                                val = self._clean_num(raw_val)
                                lbl = "測試結果" if global_match == 0 else f"複測結果{global_match}"
                                summary_res.append({"項目": item_full, "Spec": rule["criteria"], "結果類型": lbl, "判定值": f"{val:.2f}" if val is not None else "- -", "結論": Status.INFO.value})
                                detail_logs.append({"測項 (Item)": item_full, "階段 (Stage)": lbl, "分析詳情 (Details)": {"CSV檔名": finfo["name"], "抓取類型": rule["type"], "錨點確認": f"座標 {rule['anchor'][0]}{r_idx+1} = '{anchor_display}'", "目標範圍": f"{rule['target']}{r_idx+1}", "取值過程": [{"座標": f"{rule['target']}{r_idx+1}", "原始值": raw_val, "轉換後數值": val, "計算過程": "同檔案由上往下依序掃描"}]}})
                                global_match += 1
                else:
                    for rl in self._ROUNDS:
                        path = rule_assign.get(rl)
                        if not path or path not in file_contents:
                            continue
                        finfo = {"path": path, "rows": file_contents[path], "name": os.path.basename(path)}
                        data, details = self._extract_logic(rule, finfo)
                        data.update({"項目": item_full, "Spec": rule["criteria"], "結果類型": rl})
                        summary_res.append(data)
                        detail_logs.append({"測項 (Item)": item_full, "階段 (Stage)": rl, "分析詳情 (Details)": details})
                continue

            # ── 原有邏輯：依路徑燈光條件過濾 ─────────────────
            eligible_files = []
            for path, rows in file_contents.items():
                if rule["light"].upper() not in [p.upper() for p in os.path.normpath(path).split(os.sep)]:
                    continue
                if rule["type"] == "mtf_multi_row":
                    a_col, a_key = rule["anchor"]
                    c_idx = self.reader.excel_to_index(a_col + "1")[1]
                    anchor_values = a_key if isinstance(a_key, list) else [a_key]
                    if any(len(r) > c_idx and str(r[c_idx]).strip() in anchor_values for r in rows):
                        file_info = files_df[files_df["path"] == path].iloc[0]
                        eligible_files.append({"path": path, "rows": rows, "ctime": file_info["ctime"], "name": file_info["name"]})
                else:
                    a_coord, a_key = rule["anchor"]
                    r, c = self.reader.excel_to_index(a_coord)
                    if len(rows) > r and len(rows[r]) > c and str(rows[r][c]).strip() == a_key:
                        file_info = files_df[files_df["path"] == path].iloc[0]
                        eligible_files.append({"path": path, "rows": rows, "ctime": file_info["ctime"], "name": file_info["name"]})

            eligible_files = sorted(eligible_files, key=lambda x: x["ctime"])
            if not eligible_files:
                summary_res.append({"項目": item_full, "Spec": rule["criteria"], "結果類型": "測試結果", "判定值": "- -", "結論": "--"})
                continue

            if rule["type"] == "mtf_multi_row":
                for finfo in eligible_files:
                    rows = finfo["rows"]
                    c_idx = self.reader.excel_to_index(rule["anchor"][0] + "1")[1]
                    j_idx = self.reader.excel_to_index(rule["target"] + "1")[1]
                    anchor_values = rule["anchor"][1] if isinstance(rule["anchor"][1], list) else [rule["anchor"][1]]
                    anchor_display = ", ".join(anchor_values) if isinstance(anchor_values, list) else anchor_values
                    match_count = 0
                    for r_idx, row in enumerate(rows):
                        if len(row) > c_idx and str(row[c_idx]).strip() in anchor_values:
                            raw_val = row[j_idx] if len(row) > j_idx else None
                            val = self._clean_num(raw_val)
                            label = "測試結果" if match_count == 0 else f"複測結果{match_count}"
                            res = {"判定值": f"{val:.2f}" if val is not None else "- -", "結論": Status.INFO.value}
                            res.update({"項目": item_full, "Spec": rule["criteria"], "結果類型": label})
                            log = {"CSV檔名": finfo["name"], "抓取類型": rule["type"], "錨點確認": f"座標 {rule['anchor'][0]}{r_idx+1} = '{anchor_display}'", "目標範圍": f"{rule['target']}{r_idx+1}", "取值過程": [{"座標": f"{rule['target']}{r_idx+1}", "原始值": raw_val, "轉換後數值": val, "計算過程": "同檔案由上往下依序掃描"}]}
                            summary_res.append(res)
                            detail_logs.append({"測項 (Item)": item_full, "階段 (Stage)": label, "分析詳情 (Details)": log})
                            match_count += 1
                continue

            for idx, finfo in enumerate(eligible_files):
                label = "測試結果" if idx == 0 else f"複測結果{idx}"
                data, details = self._extract_logic(rule, finfo)
                data.update({"項目": item_full, "Spec": rule["criteria"], "結果類型": label})
                summary_res.append(data)
                detail_logs.append({"測項 (Item)": item_full, "階段 (Stage)": label, "分析詳情 (Details)": details})

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
            "取值過程": [],
        }

        try:
            val, unit, is_undefined = None, "", False
            if any(x in rule["name"] for x in ["Chroma", "Shading"]):
                unit = "%"
            elif "Dynamic Range" in rule["name"]:
                unit = " dB"

            if rule["type"] == "single":
                raw = self._get_v(rows, rule["target"])
                val = self._clean_num(raw, auto_scale=rule.get("scale", False))
                calc_step = "直接取值"
                if rule.get("scale") and val and raw:
                    raw_num = float(str(raw).replace("%", "").strip())
                    if 0 < raw_num < 2:
                        calc_step = f"百分比轉換: {raw_num} * 100 = {val}"
                log["取值過程"].append({"座標": rule["target"], "原始值": raw, "轉換後數值": val, "計算過程": calc_step})
                if val is not None:
                    if rule["spec"] is None:
                        res["結論"] = Status.INFO.value
                    elif isinstance(rule["spec"], tuple):
                        res["結論"] = Status.PASS.value if rule["spec"][0] <= val <= rule["spec"][1] else Status.FAIL.value
                    elif "Accuracy" in rule["name"]:
                        res["結論"] = Status.PASS.value if val <= rule["spec"] else Status.FAIL.value
                    else:
                        res["結論"] = Status.PASS.value if val > rule["spec"] else Status.FAIL.value

            elif rule["type"] == "multi_max":
                vals = []
                for c in rule["target"]:
                    raw = self._get_v(rows, c)
                    cv = self._clean_num(raw)
                    log["取值過程"].append({"座標": c, "原始值": raw, "數值": cv})
                    if cv is not None:
                        vals.append(cv)
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
                        log["取值過程"].append({"座標": coord, "原始值": raw, "計算過程": f"abs(1 - {ratio:.4f}) * 100 = {diff_val:.2f}%"})
                if diffs:
                    val = max(diffs)
                    log["結果計算"] = f"取最大偏差值: MAX({[round(d, 2) for d in diffs]}) = {val:.2f}%"
                    res["結論"] = Status.PASS.value if val < rule["spec"] else Status.FAIL.value

            elif rule["type"] == "snr_max":
                s, e = rule["target"].split(":")
                r1, c1 = self.reader.excel_to_index(s)
                r2, c2 = self.reader.excel_to_index(e)
                block = pd.to_numeric(df_rows.iloc[r1 : r2 + 1, c1 : c2 + 1].stack(), errors="coerce").dropna()
                log["取值過程"].append({"搜尋範圍": rule["target"], "範圍內有效數字格數": len(block)})
                if not block.empty:
                    val = block.max()
                    log["結果計算"] = f"範圍內最大值 = {val}"
                    res["結論"] = Status.INFO.value

            elif rule["type"] == "conditional_dr":
                c_c, c_k = rule["cond"]
                raw_cond = self._get_v(rows, c_c)
                log["條件檢查"] = {"條件座標": c_c, "期望關鍵字": c_k, "CSV實際值": raw_cond}
                if str(raw_cond).strip().upper() == c_k:
                    raw_val = self._get_v(rows, rule["target"])
                    val = self._clean_num(raw_val)
                    log["取值過程"].append({"座標": rule["target"], "原始值": raw_val, "轉換數值": val})
                    res["結論"] = Status.INFO.value
                else:
                    is_undefined = True
                    log["結果計算"] = "條件不符，跳過抓取 (判定為 undefined)"
                    res["結論"] = Status.FAIL.value

            if rule["id"] in [10, 17] or (rule["id"] == 16 and not is_undefined):
                res["結論"] = Status.INFO.value

            if is_undefined:
                res["判定值"] = "undefined"
            elif val is not None:
                res["判定值"] = "{:.2f}{}".format(val, unit)
            else:
                res["判定值"] = "- -"
            if isinstance(res["結論"], Status):
                res["結論"] = res["結論"].value

        except Exception as e:
            res["結論"] = "--"
            log["系統錯誤"] = str(e)

        return res, log

    def _get_v(self, rows, c):
        try:
            r, i = self.reader.excel_to_index(c)
            return rows[r][i] if r < len(rows) and i < len(rows[r]) else None
        except Exception:
            return None

    def _clean_num(self, v, auto_scale=False):
        if v is None or str(v).strip() == "" or str(v).lower() == "nan":
            return None
        try:
            num = float(str(v).replace("%", "").strip())
            if auto_scale and 0 < num < 2:
                num *= 100
            return num
        except Exception:
            return None


# ==========================================
# 3. 檔案掃描
# ==========================================
class Scanner:
    @staticmethod
    def scan_deep(root_dir: str) -> pd.DataFrame:
        found = []
        for root, _, files in os.walk(root_dir):
            parts = [p.upper() for p in os.path.normpath(root).split(os.sep)]
            light = next((l for l in LIGHT_MAP.keys() if l in parts), None)
            if not light:
                continue
            for f in files:
                if f.lower().endswith(".csv"):
                    p = os.path.join(root, f)
                    found.append({"light": light, "path": p, "ctime": os.path.getctime(p), "name": f})
        return pd.DataFrame(found).sort_values("ctime").reset_index(drop=True) if found else pd.DataFrame()


# ==========================================
# 4. AE 分析模組
# ==========================================
class AEPhotoDetail:
    """分析單張影像的曝光資訊。"""

    def __init__(self, path: str):
        self.path = path
        self.filename = os.path.basename(path)
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"無法讀取影像: {self.filename}")
        self.h, self.w = img.shape[:2]
        cx, cy = self.w // 2, self.h // 2
        x1, y1, x2, y2 = cx - 50, cy - 50, cx + 50, cy + 50
        roi = img[max(0, y1) : min(self.h, y2), max(0, x1) : min(self.w, x2)]
        b_avg, g_avg, r_avg = cv2.mean(roi)[:3]
        self.rgb_avg = (round(r_avg, 2), round(g_avg, 2), round(b_avg, 2))
        self.y_avg = 0.299 * r_avg + 0.587 * g_avg + 0.114 * b_avg
        self.diff_from_avg = 0.0
        self.full_res_boxed = self._get_boxed_img(img, x1, y1, x2, y2)

    def _get_boxed_img(self, img, x1: int, y1: int, x2: int, y2: int) -> Image.Image:
        """在影像中心繪製紅色取樣框。"""
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(pil_img)
        draw.rectangle([x1, y1, x2, y2], outline="red", width=6)
        return pil_img


class AETab(ttk.Frame):
    """AE 曝光一致性分析分頁。"""

    AE_VERSION = "DQE_20260317"

    def __init__(self, parent, on_result=None):
        super().__init__(parent, padding=0)
        self.results_cache: List[Dict] = []
        self.global_max_diff = 0.0
        self.global_max_lv_list: List[str] = []
        self._photo_refs: List = []  # 防止 GC 清除 PhotoImage
        self._on_result_cb = on_result
        self._setup_ui()

    def _setup_ui(self):
        # ── 左側控制面板 ──────────────────────────────
        sidebar = ttk.Frame(self, width=230)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)

        ttk.Label(sidebar, text="DQE AE Tool", font=("Microsoft JhengHei", 16, "bold")).pack(pady=(25, 10))
        ttk.Button(sidebar, text="📂 選擇主資料夾", command=self._start_analysis, bootstyle=PRIMARY, width=20).pack(pady=6, padx=15)

        self.btn_copy = ttk.Button(sidebar, text="📋 複製 Excel 數據", command=self._copy_to_clipboard, bootstyle=SUCCESS, width=20, state=DISABLED)
        self.btn_copy.pack(pady=6, padx=15)

        ttk.Button(sidebar, text="🗑 清空結果", command=self._clear_results, bootstyle=DANGER, width=20).pack(pady=6, padx=15)

        self.status_lbl = ttk.Label(sidebar, text="Ready", font=("Microsoft JhengHei", 13, "bold"))
        self.status_lbl.pack(pady=(25, 4))
        self.max_stat_lbl = ttk.Label(sidebar, text="", font=("Microsoft JhengHei", 11), wraplength=210, justify=LEFT)
        self.max_stat_lbl.pack(pady=4, padx=10)

        ttk.Label(sidebar, text="判定規範：\nDiff > 5% 為 Fail\nDiff ≤ 5% 為 Pass", font=("Microsoft JhengHei", 11), justify=LEFT).pack(side=BOTTOM, pady=15)
        ttk.Label(sidebar, text=f"Version: {self.AE_VERSION}", font=("Consolas", 10), foreground="gray").pack(side=BOTTOM, pady=5)

        ttk.Separator(self, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=2)

        # ── 右側捲動結果區 ────────────────────────────
        right = ttk.Frame(self)
        right.pack(side=LEFT, fill=BOTH, expand=True)

        self.canvas = tk.Canvas(right, highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient=VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)

        self.scroll_frame = ttk.Frame(self.canvas)
        self._canvas_win = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._canvas_win, width=e.width))

        # 僅在滑鼠進入捲動區時才綁定滾輪，避免干擾其他分頁
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _clear_results(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self.results_cache.clear()
        self.global_max_diff = 0.0
        self.global_max_lv_list.clear()
        self._photo_refs.clear()
        self.status_lbl.config(text="Ready", foreground="")
        self.max_stat_lbl.config(text="")
        self.btn_copy.config(state=DISABLED)
        messagebox.showinfo("清空", "所有結果已清除。")

    def _start_analysis(self):
        main_path = filedialog.askdirectory()
        if not main_path:
            return
        subfolders = sorted(
            [d for d in os.listdir(main_path) if os.path.isdir(os.path.join(main_path, d))],
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"([0-9]+)", s)],
        )
        subfolders = [d for d in subfolders if d.lower() != "results"]
        if not subfolders:
            messagebox.showerror("錯誤", "找不到符合規範的子資料夾。")
            return

        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self.results_cache.clear()
        self.global_max_diff = 0.0
        self.global_max_lv_list.clear()
        self._photo_refs.clear()
        overall_pass, has_error = True, False
        valid_ext = (".png", ".jpg", ".jpeg", ".bmp", ".tif")

        try:
            for folder_name in subfolders:
                folder_path = os.path.join(main_path, folder_name)
                files = sorted(
                    [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.lower().endswith(valid_ext)],
                    key=os.path.getmtime,
                )
                if len(files) != 3:
                    messagebox.showwarning("檔案數量錯誤", f"資料夾 '{folder_name}' 偵測到 {len(files)} 張照片（應為 3 張）。已跳過此階分析。")
                    res_data = {"level": folder_name, "status": "Skip", "error": f"Error: Found {len(files)} files, expected 3", "photos": []}
                    has_error = True
                else:
                    photo_details = [AEPhotoDetail(f) for f in files]
                    avg_y = sum(p.y_avg for p in photo_details) / 3
                    lv_max_diff = 0.0
                    for p in photo_details:
                        p.diff_from_avg = abs(p.y_avg - avg_y) / avg_y * 100 if avg_y != 0 else 0
                        if p.diff_from_avg > lv_max_diff:
                            lv_max_diff = p.diff_from_avg

                    if round(lv_max_diff, 2) > round(self.global_max_diff, 2):
                        self.global_max_diff = lv_max_diff
                        self.global_max_lv_list = [folder_name]
                    elif round(lv_max_diff, 2) == round(self.global_max_diff, 2) and lv_max_diff > 0:
                        if folder_name not in self.global_max_lv_list:
                            self.global_max_lv_list.append(folder_name)

                    status = "Pass" if lv_max_diff <= 5.0 else "Fail"
                    if status == "Fail":
                        overall_pass = False
                    res_data = {
                        "level": folder_name,
                        "y_list": [p.y_avg for p in photo_details],
                        "avg": avg_y,
                        "max_diff": lv_max_diff,
                        "status": status,
                        "photos": photo_details,
                    }

                self.results_cache.append(res_data)
                self._render_level_section(res_data)

            overall_text = "OVERALL: PASS" if overall_pass and not has_error else "OVERALL: FAIL/WARN"
            overall_fg = "green" if overall_pass and not has_error else "orange"
            self.status_lbl.config(text=overall_text, foreground=overall_fg)
            self.max_stat_lbl.config(text=f"Max Diff: {self.global_max_diff:.2f}%\n@ {', '.join(self.global_max_lv_list)}")
            self.btn_copy.config(state=NORMAL)
            if self._on_result_cb:
                self._on_result_cb(self.global_max_diff, overall_pass and not has_error)
            self._auto_save_results(main_path, overall_pass and not has_error)

        except Exception as e:
            messagebox.showerror("錯誤", f"處理失敗：{str(e)}")

    def _render_level_section(self, res: Dict):
        if res["status"] == "Skip":
            f = ttk.LabelFrame(self.scroll_frame, text=f"Level: {res['level']}")
            f.pack(fill=X, pady=8, padx=10)
            ttk.Label(f, text=res["error"], foreground="orange").pack(pady=5)
            return

        title_fg = "green" if res["status"] == "Pass" else "red"
        title = f"Level: {res['level']} | Avg Y: {res['avg']:.2f} | Max Diff: {res['max_diff']:.2f}% | {res['status']}"
        f = ttk.LabelFrame(self.scroll_frame, text=title)
        f.pack(fill=X, pady=8, padx=10)
        ttk.Label(f, text=title, foreground=title_fg, font=("Microsoft JhengHei", 10, "bold")).pack(anchor=W, pady=(0, 6))

        row_f = ttk.Frame(f)
        row_f.pack(fill=X)

        for i, p in enumerate(res["photos"]):
            card = tk.Frame(row_f, padx=8, pady=8, relief="solid", borderwidth=1)
            card.pack(side=LEFT, padx=8, pady=5, expand=True, fill=BOTH)

            thumb = p.full_res_boxed.copy()
            thumb.thumbnail((180, 135))
            tk_img = ImageTk.PhotoImage(thumb)
            self._photo_refs.append(tk_img)
            tk.Label(card, image=tk_img).pack(pady=5)

            ordinal = ["1st", "2nd", "3rd"][i]
            txt = (f"【{ordinal}】\n檔名: {p.filename}\n尺寸: {p.w}x{p.h}\n"
                   f"RGB: {p.rgb_avg}\nY: {p.y_avg:.2f}\nDiff: {p.diff_from_avg:.2f}%")
            fg = "red" if p.diff_from_avg > 5.0 else ""
            tk.Label(card, text=txt, justify=LEFT, font=("Consolas", 10), fg=fg or "black").pack(pady=5, padx=8)

    def _copy_to_clipboard(self):
        header = "Level\t1st\t2nd\t3rd\tAvg\tMax Diff\tResult\n"
        rows = []
        for r in self.results_cache:
            if r["status"] == "Skip":
                rows.append(f"{r['level']}\t--\t--\t--\t--\t--\t{r['error']}")
            else:
                rows.append(f"{r['level']}\t{r['y_list'][0]:.2f}\t{r['y_list'][1]:.2f}\t{r['y_list'][2]:.2f}\t{r['avg']:.2f}\t{r['max_diff']:.2f}%\t{r['status']}")
        pyperclip.copy(
            header + "\n".join(rows)
            + f"\nGlobal Max Difference:\t{self.global_max_diff:.2f}%\t@ {', '.join(self.global_max_lv_list)}"
        )
        messagebox.showinfo("成功", "數據已成功複製至剪貼簿。")

    def _auto_save_results(self, main_path: str, overall_pass: bool):
        save_dir = os.path.join(main_path, "Results", "AE")
        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_path = os.path.join(save_dir, f"AE_Report_Data_{timestamp}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("Level\t1st\t2nd\t3rd\tAvg\tMax Diff\tResult\n")
            for r in self.results_cache:
                if r["status"] == "Skip":
                    f.write(f"{r['level']}\t--\t--\t--\t--\t--\t{r['error']}\n")
                else:
                    f.write(f"{r['level']}\t{r['y_list'][0]:.2f}\t{r['y_list'][1]:.2f}\t{r['y_list'][2]:.2f}\t{r['avg']:.2f}\t{r['max_diff']:.2f}%\t{r['status']}\n")
            f.write(f"\n[Global Summary]\nGlobal Max Difference:\t{self.global_max_diff:.2f}%\tLocated in:\t{', '.join(self.global_max_lv_list)}\n")
        self._generate_long_report_image(os.path.join(save_dir, f"AE_Report_Image_{timestamp}.png"), overall_pass)
        messagebox.showinfo("自動存檔", f"數據與長圖已儲存至：\n{save_dir}")

    def _generate_long_report_image(self, save_path: str, overall_pass: bool):
        width, row_h, header_h = 1100, 420, 130
        img = Image.new("RGB", (width, header_h + len(self.results_cache) * row_h + 60), color=(25, 25, 25))
        draw = ImageDraw.Draw(img)
        draw.text((30, 20), f"AE Tool Version : {self.AE_VERSION}", fill=(255, 255, 255))
        draw.text((30, 50), f"Overall Result: {'PASS' if overall_pass else 'FAIL/WARN'} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fill=(46, 204, 113) if overall_pass else (231, 76, 60))
        draw.text((30, 80), f"Global Max Difference: {self.global_max_diff:.2f}% (Found in {', '.join(self.global_max_lv_list)})", fill=(230, 126, 34))

        curr_y = header_h
        ordinals = ["1st", "2nd", "3rd"]
        for res in self.results_cache:
            draw.line([(20, curr_y), (width - 20, curr_y)], fill=(80, 80, 80), width=1)
            if res["status"] == "Skip":
                draw.text((30, curr_y + 15), f"Level: {res['level']} | {res['error']}", fill=(241, 196, 15))
            else:
                lv_color = (46, 204, 113) if res["status"] == "Pass" else (231, 76, 60)
                draw.text((30, curr_y + 15), f"Level: {res['level']} | Avg Y: {res['avg']:.2f} | Max Diff: {res['max_diff']:.2f}% | Result: {res['status']}", fill=lv_color)
                for i, p in enumerate(res["photos"]):
                    thumb = p.full_res_boxed.copy()
                    thumb.thumbnail((280, 210))
                    tw, th = thumb.size
                    img_x = 30 + i * 350
                    img_y = curr_y + 50
                    img.paste(thumb, (img_x, img_y))
                    text_y = img_y + th + 10
                    ordinal_label = ordinals[i] if i < 3 else f"[{i+1}th]"
                    draw.multiline_text(
                        (img_x, text_y),
                        f"[{ordinal_label}]\nFilename: {p.filename}\nSize: {p.w}x{p.h}\nRGB: {p.rgb_avg}\nY: {p.y_avg:.2f}\nDiff: {p.diff_from_avg:.2f}%",
                        fill=(231, 76, 60) if p.diff_from_avg > 5.0 else (200, 200, 200),
                        spacing=4,
                    )
            curr_y += row_h
        img.save(save_path)


# ==========================================
# 5. 檔案設定 Tab
# ==========================================
class FileAssignTab(ttk.Frame):
    """以測試項目為單位顯示每輪 CSV 分配，每格有「選擇檔案」按鈕。"""

    ROUNDS = ["測試結果", "複測結果1", "複測結果2"]

    def __init__(self, parent, on_apply=None):
        super().__init__(parent)
        self._on_apply = on_apply
        # key=(rule_id, round_label), value=path
        self._assign: Dict[Tuple[int, str], str] = {}
        self._path_vars: Dict[Tuple[int, str], tk.StringVar] = {}
        # AE: round_label -> txt path
        self._ae_assign: Dict[str, str] = {}
        self._ae_vars: Dict[str, tk.StringVar] = {}
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(side=TOP, fill=X)
        self.info_lbl = ttk.Label(top, text="請先選擇測試資料夾", font=("Microsoft JhengHei", 10))
        self.info_lbl.pack(side=LEFT)
        ttk.Button(top, text="套用並更新報表", command=self._apply, bootstyle=PRIMARY).pack(side=RIGHT, padx=5)

        ttk.Separator(self, orient=HORIZONTAL).pack(fill=X, padx=10)

        container = ttk.Frame(self)
        container.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        self._canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self._canvas.pack(side=LEFT, fill=BOTH, expand=True)

        self._scroll_frame = ttk.Frame(self._canvas)
        self._win_id = self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        self._scroll_frame.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._win_id, width=e.width))
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def load(self, files_df: pd.DataFrame, base_path: str = ""):
        """從 files_df 依燈光條件推導每個 TEST_RULE 的預設分配，並掃描 AE txt。"""
        self._assign = {}
        self._ae_assign = {}

        # 建立 light -> [path sorted by ctime] 的對照
        pool: Dict[str, List[str]] = {}
        for _, row in files_df.sort_values("ctime").iterrows():
            pool.setdefault(row["light"], []).append(row["path"])

        # 每條規則依其 light 取前 3 個檔案對應三輪
        for rule in TEST_RULES:
            paths = pool.get(rule["light"], [])
            for i, rl in enumerate(self.ROUNDS):
                if i < len(paths):
                    self._assign[(rule["id"], rl)] = paths[i]

        # 掃描 AE txt 檔並預設分配
        if base_path:
            import glob
            txts = sorted(glob.glob(os.path.join(base_path, "**", "AE_Report_Data_*.txt"), recursive=True))[-3:]
            for i, rl in enumerate(self.ROUNDS):
                if i < len(txts):
                    self._ae_assign[rl] = txts[i]

        csv_count = sum(len(v) for v in pool.values())
        self.info_lbl.config(text=f"掃描到 {csv_count} 個 CSV。請確認各測項對應檔案，或按「選擇檔案」手動指定。")
        self._rebuild_rows()

    def _rebuild_rows(self):
        """清空並重建捲動區內的所有表單列（以測試項目分組）。"""
        for w in self._scroll_frame.winfo_children():
            w.destroy()
        self._path_vars = {}

        for rule in TEST_RULES:
            l_display = rule.get("display_light") or LIGHT_MAP.get(rule["light"], rule["light"])
            item_full = f"{rule['id']}. {rule['name']} ({l_display})"

            # 項目標題列
            grp = ttk.Frame(self._scroll_frame, padding=(8, 6, 8, 2))
            grp.pack(fill=X)
            ttk.Label(grp, text=item_full, font=("Microsoft JhengHei", 10, "bold")).pack(side=LEFT)
            ttk.Separator(self._scroll_frame, orient=HORIZONTAL).pack(fill=X, padx=8, pady=(0, 2))

            # 每輪一列
            for rl in self.ROUNDS:
                key = (rule["id"], rl)
                path = self._assign.get(key, "")
                var = tk.StringVar(value=path)
                self._path_vars[key] = var

                row_f = ttk.Frame(self._scroll_frame, padding=(20, 3, 8, 3))
                row_f.pack(fill=X)
                ttk.Label(row_f, text=rl, font=("Microsoft JhengHei", 10), width=10, anchor=W).pack(side=LEFT)
                ttk.Entry(row_f, textvariable=var, font=("Microsoft JhengHei", 9), state="readonly").pack(
                    side=LEFT, fill=X, expand=True, padx=(6, 8)
                )
                ttk.Button(
                    row_f, text="選擇檔案", bootstyle=SECONDARY, width=10,
                    command=lambda k=key, r=rule: self._pick_file(k, r),
                ).pack(side=LEFT)
                ttk.Button(
                    row_f, text="✕", bootstyle="danger-outline", width=3,
                    command=lambda k=key, v=var: self._clear_slot(k, v),
                ).pack(side=LEFT, padx=(4, 0))

            ttk.Separator(self._scroll_frame, orient=HORIZONTAL).pack(fill=X, padx=8, pady=(4, 0))

        # AE 區段
        self._ae_vars = {}
        ae_grp = ttk.Frame(self._scroll_frame, padding=(8, 6, 8, 2))
        ae_grp.pack(fill=X)
        ttk.Label(ae_grp, text="18. AE (4870K)", font=("Microsoft JhengHei", 10, "bold")).pack(side=LEFT)
        ttk.Label(ae_grp, text="  （AE_Report_Data_*.txt）", font=("Microsoft JhengHei", 9), foreground="gray").pack(side=LEFT)
        ttk.Separator(self._scroll_frame, orient=HORIZONTAL).pack(fill=X, padx=8, pady=(0, 2))

        for rl in self.ROUNDS:
            path = self._ae_assign.get(rl, "")
            var = tk.StringVar(value=path)
            self._ae_vars[rl] = var

            row_f = ttk.Frame(self._scroll_frame, padding=(20, 3, 8, 3))
            row_f.pack(fill=X)
            ttk.Label(row_f, text=rl, font=("Microsoft JhengHei", 10), width=10, anchor=W).pack(side=LEFT)
            ttk.Entry(row_f, textvariable=var, font=("Microsoft JhengHei", 9), state="readonly").pack(
                side=LEFT, fill=X, expand=True, padx=(6, 8)
            )
            ttk.Button(
                row_f, text="選擇檔案", bootstyle=SECONDARY, width=10,
                command=lambda r=rl: self._pick_ae_file(r),
            ).pack(side=LEFT)
            ttk.Button(
                row_f, text="✕", bootstyle="danger-outline", width=3,
                command=lambda r=rl, v=var: self._clear_ae_slot(r, v),
            ).pack(side=LEFT, padx=(4, 0))

        ttk.Separator(self._scroll_frame, orient=HORIZONTAL).pack(fill=X, padx=8, pady=(4, 0))

    def _pick_file(self, key: Tuple[int, str], rule: Dict):
        """開啟 filedialog，讓使用者選取該測項 / 輪次的 CSV 檔案。"""
        l_display = rule.get("display_light") or LIGHT_MAP.get(rule["light"], rule["light"])
        path = filedialog.askopenfilename(
            title=f"選取 CSV — {rule['id']}. {rule['name']} ({l_display}) / {key[1]}",
            filetypes=[("CSV 檔案", "*.csv"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        self._assign[key] = path
        if key in self._path_vars:
            self._path_vars[key].set(path)

    def _clear_slot(self, key: Tuple[int, str], var: tk.StringVar):
        """清空指定 CSV 槽位的路徑。"""
        self._assign.pop(key, None)
        var.set("")

    def _clear_ae_slot(self, round_label: str, var: tk.StringVar):
        """清空指定 AE 槽位的路徑。"""
        self._ae_assign.pop(round_label, None)
        var.set("")

    def _pick_ae_file(self, round_label: str):
        """開啟 filedialog，讓使用者選取該輪 AE txt 檔案。"""
        path = filedialog.askopenfilename(
            title=f"選取 AE 報告 — {round_label}",
            filetypes=[("AE 報告", "AE_Report_Data_*.txt"), ("文字檔", "*.txt"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        self._ae_assign[round_label] = path
        if round_label in self._ae_vars:
            self._ae_vars[round_label].set(path)

    def get_ae_assignment(self) -> "Dict[str, str]":
        """回傳 {round_label: txt_path}，僅包含已指定路徑的輪次。"""
        return {rl: p for rl, p in self._ae_assign.items() if p}

    def get_assignment(self) -> "Dict[int, Dict[str, str]]":
        """回傳 {rule_id: {round_label: path}} 供 Extractor 使用。"""
        result: Dict[int, Dict[str, str]] = {}
        for (rule_id, rl), path in self._assign.items():
            if path:
                result.setdefault(rule_id, {})[rl] = path
        return result

    def _apply(self):
        if self._on_apply:
            self._on_apply()


# ==========================================
# 6. UI 介面
# ==========================================
class AnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1000x640")
        self.summary_df = pd.DataFrame()
        self.detail_logs = []
        self._ae_cached: Dict = {}  # {"判定值": ..., "結論": ...}
        self._set_app_icon()
        self._build_ui()

    def _resource_path(self, relative_path):
        """讓開發環境與 PyInstaller 打包後都能正確找到資源檔。"""
        if hasattr(sys, "_MEIPASS"):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

    def _set_app_icon(self):
        """設定 Windows 視窗左上角 icon 與工作列 icon。"""
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("innodisk.camera_iq_analyzer")
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
        top = ttk.Frame(self.root, padding=(15, 10))
        top.pack(side=TOP, fill=X)
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var, font=("Microsoft JhengHei", 10)).pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(top, text="選擇測試資料夾", command=self._run_analysis, bootstyle=PRIMARY).pack(side=LEFT, padx=10)

        bot = ttk.Frame(self.root, padding=(15, 8))
        bot.pack(side=BOTTOM, fill=X)
        ttk.Label(bot, text=f"Version: {VERSION}", font=("Consolas", 10), foreground="gray").pack(side=LEFT, padx=(0, 15))
        self.stat_lbl = ttk.Label(bot, text="狀態: 準備就緒", font=("Microsoft JhengHei", 10))
        self.stat_lbl.pack(side=LEFT)
        ttk.Button(bot, text="下載報表 (.xlsx)", command=self._download_csv, bootstyle=INFO).pack(side=RIGHT, padx=5)
        ttk.Button(bot, text="複製結果", command=self._copy_excel, bootstyle=SUCCESS).pack(side=RIGHT, padx=5)

        self.notebook = ttk.Notebook(self.root, bootstyle=INFO)
        self.notebook.pack(side=TOP, fill=BOTH, expand=True, padx=15, pady=5)

        self.tab_summary = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.tab_summary, text=" 總結報表 ")

        self.tab_ae = AETab(self.notebook, on_result=self._on_ae_result)
        self.notebook.add(self.tab_ae, text=" AE 分析 ")

        self.tab_assign = FileAssignTab(self.notebook, on_apply=self._apply_assign)
        self.notebook.add(self.tab_assign, text=" 檔案設定 ")

        self.tab_details = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.tab_details, text=" 分析詳情 ")

        self.sheet = Sheet(
            self.tab_summary,
            headers=["項目", "Spec", "測試結果", "複測結果1", "複測結果2", "Result"],
            header_font=("Microsoft JhengHei", 10, "bold"),
            font=("Microsoft JhengHei", 10, "normal"),
            row_height=25,
        )
        self.sheet.pack(fill=BOTH, expand=True)
        self.sheet.enable_bindings("single_select", "drag_select", "row_select", "column_select", "copy", "arrowkeys")
        self.detail_text = ScrolledText(self.tab_details, padding=10, font=("Consolas", 10))
        self.detail_text.pack(fill=BOTH, expand=True)

    def _parse_ae_file(self, txt_path: str) -> "Dict | None":
        """解析單一 AE_Report_Data_*.txt，回傳判定結果 dict 或 None。"""
        try:
            with open(txt_path, encoding="utf-8") as f:
                content = f.read()
            data_section = content.split("[Global Summary]")[0]
            data_lines = [ln for ln in data_section.strip().splitlines()[1:] if ln.strip()]
            overall_pass = bool(data_lines) and all(ln.endswith("\tPass") for ln in data_lines)
            m = re.search(r"Global Max Difference:\t([\d.]+)%", content)
            if not m:
                return None
            header = ["Level", "1st", "2nd", "3rd", "Avg", "Max Diff", "Result"]
            level_details = [dict(zip(header, ln.split("\t"))) for ln in data_lines]
            return {
                "判定值": f"{float(m.group(1)):.2f}%",
                "結論": "PASS" if overall_pass else "FAIL",
                "log": {
                    "來源檔案": os.path.basename(txt_path),
                    "各 Level 結果": level_details,
                    "Global Max Difference": m.group(1) + "%",
                },
            }
        except Exception:
            return None

    def _read_ae_result(self, base_path: str) -> List[Dict]:
        """遞迴搜尋 base_path 下所有 AE_Report_Data_*.txt，回傳最多 3 筆（由舊到新）。"""
        import glob
        txts = sorted(glob.glob(os.path.join(base_path, "**", "AE_Report_Data_*.txt"), recursive=True))[-3:]
        return [r for r in (self._parse_ae_file(t) for t in txts) if r]

    def _on_ae_result(self, global_max_diff: float, overall_pass: bool):
        """AE 分析完成時由 AETab 呼叫，更新快取並刷新摘要表第 18 列。"""
        self._ae_cached = {
            "判定值": f"{global_max_diff:.2f}%",
            "結論": "PASS" if overall_pass else "FAIL",
        }
        self._update_ae_sheet_row()

    def _update_ae_sheet_row(self):
        """在不重算全表的情況下，只更新摘要表的 AE 那一列（同 session callback 用）。"""
        if self.summary_df.empty:
            return
        item_name = "18. AE (4870K)"
        idxs = self.summary_df.index[self.summary_df["項目"] == item_name].tolist()
        if not idxs:
            return
        row_idx = idxs[0]
        val = self._ae_cached.get("判定值", "- -")
        conc = self._ae_cached.get("結論", "--")
        # 更新「測試結果」欄（col 2）與「Result」欄（col 5）
        self.summary_df.at[row_idx, "測試結果"] = val
        col_map = {"測試結果": 2, "複測結果1": 3, "複測結果2": 4, "Result": 5}
        self.sheet.set_cell_data(row_idx, col_map["測試結果"], val)
        # 重新計算 Result（三戰兩勝）
        pass_vals = [
            self.summary_df.at[row_idx, c]
            for c in ["測試結果", "複測結果1", "複測結果2"]
            if self.summary_df.at[row_idx, c] not in ("- -", None)
        ]
        # 從 summary_df 無法直接取得結論，直接用快取結論更新 Result
        self.summary_df.at[row_idx, "Result"] = conc
        self.sheet.set_cell_data(row_idx, col_map["Result"], conc)
        color_red, color_green = "#dc3545", "#28a745"
        if conc == "PASS":
            self.sheet.highlight_cells(row=row_idx, column=col_map["測試結果"], fg=color_green)
            self.sheet.highlight_cells(row=row_idx, column=col_map["Result"], fg=color_green)
        elif conc == "FAIL":
            self.sheet.highlight_cells(row=row_idx, column=col_map["測試結果"], fg=color_red)
            self.sheet.highlight_cells(row=row_idx, column=col_map["Result"], fg=color_red)
        self.sheet.redraw()

    def _run_analysis(self):
        path = filedialog.askdirectory()
        if not path:
            return
        self.path_var.set(path)
        f_df = Scanner.scan_deep(path)
        if f_df.empty:
            self.stat_lbl.config(text="狀態: 找不到符合的 CSV 檔案")
            return
        self.tab_assign.load(f_df, base_path=path)
        self._execute_analysis(f_df)

    def _apply_assign(self):
        """由「檔案設定」Tab 的「套用並更新報表」按鈕觸發。"""
        assignment = self.tab_assign.get_assignment()
        if not assignment:
            messagebox.showwarning("無資料", "沒有可分析的 CSV 分配，請先選擇測試資料夾。")
            return
        ae_assignment = self.tab_assign.get_ae_assignment()
        self._execute_analysis(pd.DataFrame(), assignment=assignment, ae_assignment=ae_assignment)

    def _execute_analysis(
        self,
        f_df: pd.DataFrame,
        assignment: "Dict[int, Dict[str, str]] | None" = None,
        ae_assignment: "Dict[str, str] | None" = None,
    ):
        """核心分析邏輯：Extractor → pivot → judge → GUI 更新，完成後切到總結報表。"""
        self.sheet.set_sheet_data([])
        self.sheet.dehighlight_all()
        self.detail_text.delete("1.0", END)

        raw_res, logs = Extractor().process_all(f_df, assignment=assignment)
        if not raw_res:
            self.stat_lbl.config(text="狀態: 找不到符合的 CSV 檔案")
            return

        # 注入 item 18 AE
        if ae_assignment:
            # 明確指定模式：依三輪順序解析指定 txt
            ae_runs = []
            for rl in ["測試結果", "複測結果1", "複測結果2"]:
                txt_path = ae_assignment.get(rl)
                if txt_path:
                    result = self._parse_ae_file(txt_path)
                    if result:
                        ae_runs.append(result)
        else:
            base_path = self.path_var.get()
            ae_runs = self._read_ae_result(base_path) if base_path else []
            if not ae_runs and self._ae_cached:
                ae_runs = [self._ae_cached]
        labels = ["測試結果", "複測結果1", "複測結果2"]
        item_name = "18. AE (4870K)"
        if ae_runs:
            for i, run in enumerate(ae_runs):
                raw_res.append({
                    "項目": item_name,
                    "Spec": "Avg ±5%",
                    "結果類型": labels[i],
                    "判定值": run.get("判定值", "- -"),
                    "結論": run.get("結論", "--"),
                })
                logs.append({
                    "測項 (Item)": item_name,
                    "階段 (Stage)": labels[i],
                    "分析詳情 (Details)": run.get("log", {"來源": "同 session 記憶體結果", "判定值": run.get("判定值", "- -")}),
                })
        else:
            raw_res.append({
                "項目": item_name,
                "Spec": "Avg ±5%",
                "結果類型": "測試結果",
                "判定值": "- -",
                "結論": "--",
            })
            logs.append({
                "測項 (Item)": item_name,
                "階段 (Stage)": "測試結果",
                "分析詳情 (Details)": {"備註": "找不到 AE_Report_Data_*.txt，請先執行 AE 分析"},
            })

        df_raw = pd.DataFrame(raw_res)
        pivot = df_raw.pivot_table(index=["項目", "Spec"], columns="結果類型", values="判定值", aggfunc="first").reset_index()

        def judge_final(name):
            item_data = df_raw[df_raw["項目"] == name]
            concs = dict(zip(item_data["結果類型"], item_data["結論"]))
            if any(s in name for s in ["10. SNR", "16. Dynamic Range", "17. MTF50P"]):
                return "INFO"
            pass_count = list(concs.values()).count("PASS")
            fail_count = list(concs.values()).count("FAIL")
            if (pass_count + fail_count) >= 3:
                return "PASS" if pass_count >= 2 else "FAIL"
            if fail_count > 0:
                return "FAIL"
            if pass_count > 0:
                return "PASS"
            return "--"

        pivot["Result"] = pivot["項目"].apply(judge_final)
        for c in ["測試結果", "複測結果1", "複測結果2"]:
            if c not in pivot.columns:
                pivot[c] = "- -"

        pivot = pivot.fillna("- -").replace("N/A", "- -")
        pivot["sk"] = pivot["項目"].apply(lambda x: int(x.split(".")[0]))
        self.summary_df = pivot.sort_values("sk").drop(columns=["sk"])[["項目", "Spec", "測試結果", "複測結果1", "複測結果2", "Result"]].reset_index(drop=True)

        self.sheet.set_sheet_data(self.summary_df.values.tolist())
        self.sheet.set_column_widths([300, 80, 110, 110, 110, 110])

        color_red = "#dc3545"
        color_green = "#28a745"
        for row_idx, (_, row) in enumerate(self.summary_df.iterrows()):
            item_name = row["項目"]
            final_res = row["Result"]
            if final_res == "PASS":
                self.sheet.highlight_cells(row=row_idx, column=5, fg=color_green)
            elif final_res == "FAIL":
                self.sheet.highlight_cells(row=row_idx, column=5, fg=color_red)

            for c_idx, label in enumerate(["測試結果", "複測結果1", "複測結果2"], start=2):
                match = df_raw[(df_raw["項目"] == item_name) & (df_raw["結果類型"] == label)]
                if not match.empty:
                    c_status = match.iloc[0]["結論"]
                    cell_val = str(row[label])
                    if c_status == "FAIL" or cell_val == "undefined":
                        self.sheet.highlight_cells(row=row_idx, column=c_idx, fg=color_red)
                    elif c_status == "PASS":
                        self.sheet.highlight_cells(row=row_idx, column=c_idx, fg=color_green)

        self.sheet.redraw()
        self.detail_logs = logs

        version_header = (
            f"{APP_NAME}\n"
            f"Version: {VERSION}\n"
            f"Generated Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'='*60}\n\n"
        )
        self.detail_text.insert(END, version_header + json.dumps(logs, indent=4, ensure_ascii=False))
        self.stat_lbl.config(text="狀態: 分析完成")
        self.notebook.select(self.tab_summary)

    def _copy_excel(self):
        if self.summary_df.empty:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.summary_df.to_csv(sep="\t", index=False, lineterminator="\n"))
        messagebox.showinfo("成功", "內容已複製。")

    def _download_csv(self):
        if self.summary_df.empty:
            return
        f = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel 活頁簿", "*.xlsx")],
            initialfile=f"Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
        )
        if not f:
            return
        try:
            log_rows = []
            for entry in self.detail_logs:
                log_rows.append({
                    "測項 (Item)": entry.get("測項 (Item)", ""),
                    "階段 (Stage)": entry.get("階段 (Stage)", ""),
                    "分析詳情 (Details)": json.dumps(entry.get("分析詳情 (Details)", {}), ensure_ascii=False, indent=2),
                })
            log_df = pd.DataFrame(log_rows)

            with pd.ExcelWriter(f, engine="openpyxl") as writer:
                self.summary_df.to_excel(writer, sheet_name="總結報表", index=False)
                log_df.to_excel(writer, sheet_name="分析詳情", index=False, startrow=4)
                ws_log = writer.sheets["分析詳情"]
                ws_log["A1"] = APP_NAME
                ws_log["A2"] = f"Version: {VERSION}"
                ws_log["A3"] = f"Generated Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
    AnalyzerApp(app_root)
    app_root.mainloop()
