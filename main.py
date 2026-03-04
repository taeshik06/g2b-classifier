"""
나라장터 공고 분류기 - GUI 메인
"""

import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path

import g2b_api


def get_base_dir() -> Path:
    """PyInstaller .exe 또는 일반 스크립트 모두 동일 경로 반환."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "keywords": [
        {"name": "파일첨부 요구", "type": "AND",      "words": ["첨부", "제출"]},
        {"name": "자격 요구",     "type": "CONTAINS",  "words": ["자격"]},
        {"name": "실적 요구",     "type": "CONTAINS",  "words": ["실적"]},
    ],
    "amount_ranges": [
        {"label": "1억 미만",  "min": 0,          "max": 100000000},
        {"label": "1억~5억",   "min": 100000000,  "max": 500000000},
        {"label": "5억~10억",  "min": 500000000,  "max": 1000000000},
        {"label": "10억 이상", "min": 1000000000, "max": None},
    ],
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("나라장터 공고 분류기")
        self.geometry("1000x780")
        self.minsize(780, 580)

        self.config = self._load_config()
        self._build_ui()

    # ── Config ─────────────────────────────────────────────────

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return dict(DEFAULT_CONFIG)

    def _save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    # ── UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        # ── API 키 ──────────────────────────────────────────
        api_frame = ttk.LabelFrame(self, text=" API 설정 ", padding=8)
        api_frame.pack(fill=tk.X, **pad)

        ttk.Label(api_frame, text="인증키:").pack(side=tk.LEFT)

        self._api_var = tk.StringVar(value=self.config.get("api_key", ""))
        self._api_entry = ttk.Entry(
            api_frame, textvariable=self._api_var, show="*", width=55
        )
        self._api_entry.pack(side=tk.LEFT, padx=(4, 2), fill=tk.X, expand=True)

        self._show_key = False
        self._toggle_btn = ttk.Button(
            api_frame, text="보기", width=5, command=self._toggle_key
        )
        self._toggle_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(api_frame, text="저장", width=6, command=self._save_api_key).pack(
            side=tk.LEFT, padx=2
        )

        # ── 공고번호 입력 ────────────────────────────────────
        in_frame = ttk.LabelFrame(
            self, text=" 공고번호 입력  (한 줄에 하나씩) ", padding=8
        )
        in_frame.pack(fill=tk.X, **pad)

        self._input_box = scrolledtext.ScrolledText(
            in_frame, height=6, font=("Consolas", 10), relief=tk.SOLID, borderwidth=1
        )
        self._input_box.pack(fill=tk.X)
        self._input_box.insert("1.0", "R26BK01347086\nR26BK01349817\nR26BK01336135")

        # ── 버튼 / 상태 ──────────────────────────────────────
        ctrl = ttk.Frame(self)
        ctrl.pack(fill=tk.X, padx=8, pady=2)

        self._run_btn = ttk.Button(
            ctrl, text="▶  분류 실행", command=self._run, width=14
        )
        self._run_btn.pack(side=tk.LEFT)

        ttk.Button(ctrl, text="결과 지우기", command=self._clear, width=10).pack(
            side=tk.LEFT, padx=6
        )

        self._status_var = tk.StringVar(value="준비")
        ttk.Label(ctrl, textvariable=self._status_var, anchor=tk.E).pack(
            side=tk.RIGHT
        )

        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.pack(fill=tk.X, padx=8, pady=(2, 4))

        # ── 결과 표시 (Treeview 표) ──────────────────────────
        res_frame = ttk.LabelFrame(self, text=" 분류 결과 ", padding=8)
        res_frame.pack(fill=tk.BOTH, expand=True, **pad)

        # 컬럼 정의: (id, 헤더명, 너비, 정렬)
        self._COLS = [
            ("분류",       "분류",       54,  "center"),
            ("공고번호",   "공고번호",   115, "center"),
            ("공고명",     "공고명",     280, "w"),
            ("공사위치",   "공사위치",   110, "w"),
            ("주공종",     "주공종",     110, "w"),
            ("기초금액",   "기초금액",   100, "e"),
            ("추정가격",   "추정가격",   100, "e"),
            ("낙찰하한율", "낙찰하한율",  72, "e"),
            ("A값",        "A값",         95, "e"),
            ("순공사원가", "순공사원가", 100, "e"),
            ("적격심사",   "적격심사기준", 110, "w"),
            ("특이사항",   "특이사항",   160, "w"),
        ]
        col_ids = [c[0] for c in self._COLS]

        self._tree = ttk.Treeview(
            res_frame, columns=col_ids, show="headings", selectmode="browse"
        )
        for cid, hdr, w, anchor in self._COLS:
            self._tree.heading(cid, text=hdr)
            self._tree.column(cid, width=w, minwidth=40, anchor=anchor, stretch=False)

        vsb = ttk.Scrollbar(res_frame, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(res_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)

        # 행 색상 태그
        self._tree.tag_configure("special", foreground="#922b21", background="#fff0f0")
        self._tree.tag_configure("normal",  foreground="#1b2631")
        self._tree.tag_configure("error",   foreground="#7f8c8d", background="#f8f8f8")

    # ── 이벤트 핸들러 ──────────────────────────────────────────

    def _toggle_key(self):
        self._show_key = not self._show_key
        self._api_entry.config(show="" if self._show_key else "*")
        self._toggle_btn.config(text="숨기기" if self._show_key else "보기")

    def _save_api_key(self):
        key = self._api_var.get().strip()
        self.config["api_key"] = key
        self._save_config()
        messagebox.showinfo("저장 완료", "API 인증키가 저장되었습니다.")

    def _clear(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._status_var.set("준비")

    def _run(self):
        api_key = self._api_var.get().strip()
        if not api_key:
            messagebox.showwarning("경고", "API 인증키를 입력하고 [저장]을 눌러주세요.")
            return

        raw = self._input_box.get("1.0", tk.END).strip()
        bid_numbers = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not bid_numbers:
            messagebox.showwarning("경고", "공고번호를 입력하세요.")
            return

        self._run_btn.config(state=tk.DISABLED)
        self._progress.start(12)
        self._clear()

        threading.Thread(
            target=self._classify_thread,
            args=(api_key, bid_numbers),
            daemon=True,
        ).start()

    # ── 백그라운드 스레드 ──────────────────────────────────────

    def _classify_thread(self, api_key: str, bid_numbers: list):
        results = []
        total = len(bid_numbers)
        for i, no in enumerate(bid_numbers, 1):
            self.after(0, self._status_var.set, f"처리 중 ({i}/{total}): {no}")
            res = g2b_api.classify_bid(api_key, no, self.config)
            results.append(res)
        self.after(0, self._show_results, results)

    # ── 결과 렌더링 ─────────────────────────────────────────────

    def _fmt_won(self, val: float) -> str:
        return f"{val:,.0f}원" if val else "미확인"

    def _show_results(self, results: list):
        self._progress.stop()
        self._run_btn.config(state=tk.NORMAL)

        specials = [r for r in results if r["is_special"] and not r["error"]]
        normals  = [r for r in results if not r["is_special"] and not r["error"]]
        errors   = [r for r in results if r["error"]]

        self._status_var.set(
            f"완료 — 특이 {len(specials)}건 / 일반 {len(normals)}건 / 오류 {len(errors)}건"
        )

        for r in specials:
            a_str = self._fmt_won(r["a_value"]) if r["a_value"] else "미해당/미공개"
            tags_str = "  ".join(f"[{t}]" for t in r["special_tags"])
            self._tree.insert("", tk.END, values=(
                "특이",
                r["bid_no"],
                r["name"],
                r["cnstwk_loc"],
                r["main_cnstty"],
                self._fmt_won(r["bssamt"]),
                self._fmt_won(r["presmpt_prce"]),
                f"{r['lwlt_rate']}%" if r["lwlt_rate"] else "-",
                a_str,
                self._fmt_won(r["pure_const_cost"]),
                r["qual_criteria"],
                tags_str,
            ), tags=("special",))

        for r in normals:
            a_str = self._fmt_won(r["a_value"]) if r["a_value"] else "미해당/미공개"
            tags_str = "  ".join(f"[{t}]" for t in r["special_tags"])
            self._tree.insert("", tk.END, values=(
                "일반",
                r["bid_no"],
                r["name"],
                r["cnstwk_loc"],
                r["main_cnstty"],
                self._fmt_won(r["bssamt"]),
                self._fmt_won(r["presmpt_prce"]),
                f"{r['lwlt_rate']}%" if r["lwlt_rate"] else "-",
                a_str,
                self._fmt_won(r["pure_const_cost"]),
                r["qual_criteria"],
                tags_str,
            ), tags=("normal",))

        for r in errors:
            self._tree.insert("", tk.END, values=(
                "오류",
                r["bid_no"],
                r.get("name", ""),
                "", "", "", "", "", "", "", "",
                r["error"],
            ), tags=("error",))


if __name__ == "__main__":
    app = App()
    app.mainloop()
