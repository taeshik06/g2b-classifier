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

        # ── 결과 표시 ────────────────────────────────────────
        res_frame = ttk.LabelFrame(self, text=" 분류 결과 ", padding=8)
        res_frame.pack(fill=tk.BOTH, expand=True, **pad)

        self._out = scrolledtext.ScrolledText(
            res_frame,
            font=("맑은 고딕", 10),
            state=tk.DISABLED,
            relief=tk.SOLID,
            borderwidth=1,
        )
        self._out.pack(fill=tk.BOTH, expand=True)

        # 색상 태그
        self._out.tag_config("h_special", foreground="#c0392b", font=("맑은 고딕", 11, "bold"))
        self._out.tag_config("h_normal",  foreground="#1a5276", font=("맑은 고딕", 11, "bold"))
        self._out.tag_config("h_error",   foreground="#7f8c8d", font=("맑은 고딕", 11, "bold"))
        self._out.tag_config("item_s",    foreground="#922b21")
        self._out.tag_config("item_n",    foreground="#1b2631")
        self._out.tag_config("item_e",    foreground="#7f8c8d")
        self._out.tag_config("tag",       foreground="#e74c3c", font=("맑은 고딕", 9))
        self._out.tag_config("amount",    foreground="#1e8449")

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
        self._out.config(state=tk.NORMAL)
        self._out.delete("1.0", tk.END)
        self._out.config(state=tk.DISABLED)
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

    def _write(self, text: str, tag: str = ""):
        self._out.config(state=tk.NORMAL)
        if tag:
            self._out.insert(tk.END, text, tag)
        else:
            self._out.insert(tk.END, text)
        self._out.config(state=tk.DISABLED)
        self._out.see(tk.END)

    def _show_results(self, results: list):
        self._progress.stop()
        self._run_btn.config(state=tk.NORMAL)

        specials = [r for r in results if r["is_special"] and not r["error"]]
        normals  = [r for r in results if not r["is_special"] and not r["error"]]
        errors   = [r for r in results if r["error"]]

        self._status_var.set(
            f"완료 — 특이 {len(specials)}건 / 일반 {len(normals)}건 / 오류 {len(errors)}건"
        )

        # ── 특이 공고 ─────────────────────────────────────
        self._write(f"■ 특이 공고 ({len(specials)}건)\n", "h_special")
        self._write("─" * 60 + "\n")

        if specials:
            for r in specials:
                amt = f"{r['amount']:,.0f}원" if r["amount"] else "금액 미확인"
                pdf_note = f"  PDF {r['pdf_count']}건" if r["pdf_count"] else ""
                tags_str = "  " + "  ".join(f"[{t}]" for t in r["special_tags"])

                self._write(f"  {r['bid_no']}\n", "item_s")
                self._write(f"  {r['name']}\n", "item_s")
                self._write(f"  {r['institution']}\n", "item_s")
                self._write(f"  금액: {amt}  ({r['amount_label']}){pdf_note}\n", "amount")
                self._write(f"{tags_str}\n", "tag")
                self._write("\n")
        else:
            self._write("  (없음)\n\n")

        # ── 일반 공고 ─────────────────────────────────────
        self._write(f"■ 일반 공고 ({len(normals)}건)\n", "h_normal")
        self._write("─" * 60 + "\n")

        if normals:
            for r in normals:
                amt = f"{r['amount']:,.0f}원" if r["amount"] else "금액 미확인"
                self._write(f"  {r['bid_no']}\n", "item_n")
                self._write(f"  {r['name']}\n", "item_n")
                self._write(f"  {r['institution']}\n", "item_n")
                self._write(f"  금액: {amt}  ({r['amount_label']})\n", "amount")
                self._write("\n")
        else:
            self._write("  (없음)\n\n")

        # ── 오류 ──────────────────────────────────────────
        if errors:
            self._write(f"■ 오류 ({len(errors)}건)\n", "h_error")
            self._write("─" * 60 + "\n")
            for r in errors:
                self._write(f"  {r['bid_no']}  →  {r['error']}\n", "item_e")


if __name__ == "__main__":
    app = App()
    app.mainloop()
