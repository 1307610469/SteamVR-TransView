import ctypes
import queue
import sqlite3
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def get_runtime_dir():
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).parent
        internal_dir = base_dir / "_internal"
        if internal_dir.exists():
            return internal_dir
        return base_dir
    return Path(__file__).parent


def load_openvr_dll():
    dll_dir = get_runtime_dir()
    dll_path = dll_dir / "libopenvr_api_64.dll"
    if not dll_path.exists():
        raise FileNotFoundError(f"未找到DLL：{dll_path}")
    ctypes.CDLL(str(dll_path))

load_openvr_dll()
import openvr  # pyright: ignore[reportMissingImports]
from PIL import Image, ImageDraw, ImageFont  # pyright: ignore[reportMissingImports]


class SteamVRTranslationOverlay:
    def __init__(self, db_path=None, log_callback=None):
        self.script_dir = get_runtime_dir()
        self.db_path = Path(db_path) if db_path else Path(r"D:\livecap\translation_history.db")
        self.font_path = self.script_dir / "font" / "gnuunifontfull-pm9p.ttf"
        self.temp_texture = self.script_dir / "temp_texture.png"
        self.log_callback = log_callback or print

        self.hmd_position = {
            "x": 0.0,
            "y": 0.18,
            "z": -0.45,
            "width": 0.35
        }

        self.max_chars_per_line = 25
        self.current_text = "等待翻译数据..."
        self.last_rowid = 0
        self.db_updated = False

        self.overlay_handle = None
        self.vr_overlay = None
        self.vr_system = None
        self.hmd_index = None

        self.running = True
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._cleanup_done = False

        self.table_name = "TranslationHistory"
        self.target_field = "TranslatedText"
        self.actual_field = None

        self._check_resources()

    def _log(self, message):
        try:
            self.log_callback(message)
        except Exception:
            print(message)

    def _check_resources(self):
        if not self.font_path.exists():
            raise FileNotFoundError(f"字体缺失：{self.font_path}")
        if not self.db_path.exists():
            self._log(f"警告：数据库未找到({self.db_path})")

    def stop(self):
        self.running = False
        self._stop_event.set()
        self._log("收到停止请求，正在退出...")

    def snapshot(self):
        with self._state_lock:
            return {
                "running": self.running,
                "db_path": str(self.db_path),
                "current_text": self.current_text,
                "last_rowid": self.last_rowid,
                "db_updated": self.db_updated,
            }

    def _get_hmd_index(self):
        for i in range(openvr.k_unMaxTrackedDeviceCount):
            if self.vr_system.isTrackedDeviceConnected(i):
                if self.vr_system.getTrackedDeviceClass(i) == openvr.TrackedDeviceClass_HMD:
                    return i
        return openvr.k_unTrackedDeviceIndexInvalid

    def _init_steamvr(self):
        try:
            openvr.init(openvr.VRApplication_Overlay)
            self.vr_system = openvr.VRSystem()
            self.vr_overlay = openvr.IVROverlay()

            overlay_key = "translation_overlay.db_triggered"
            overlay_name = "翻译显示（数据库触发更新）"
            self.overlay_handle = self.vr_overlay.createOverlay(overlay_key, overlay_name)

            self.hmd_index = self._get_hmd_index()
            if self.hmd_index == openvr.k_unTrackedDeviceIndexInvalid:
                print("错误：未检测到头显")
                openvr.shutdown()
                return False

            # 设置头显相对位置
            transform = openvr.HmdMatrix34_t()
            transform[0][0] = transform[1][1] = transform[2][2] = 1.0
            transform[0][3] = self.hmd_position["x"]
            transform[1][3] = self.hmd_position["y"]
            transform[2][3] = self.hmd_position["z"]
            self.vr_overlay.setOverlayWidthInMeters(self.overlay_handle, self.hmd_position["width"])

            self.vr_overlay.setOverlayTransformTrackedDeviceRelative(
                self.overlay_handle, self.hmd_index, transform
            )

            self.vr_overlay.showOverlay(self.overlay_handle)
            self._log("字幕已固定在头显水平正前方（数据库变化时更新）")
            return True

        except Exception as e:
            self._log(f"SteamVR初始化失败：{e}")
            try:
                openvr.shutdown()
            except Exception:
                pass
            return False

    def _wrap_text(self, text):
        """文本自动换行处理"""
        wrapped_lines = []
        for i in range(0, len(text), self.max_chars_per_line):
            wrapped_lines.append(text[i:i + self.max_chars_per_line])
        return '\n'.join(wrapped_lines)

    def _render_text(self, text, font_size=36):
        """渲染文本为图像"""
        try:
            font = ImageFont.truetype(str(self.font_path), font_size)
        except IOError as e:
            raise RuntimeError(f"字体加载失败：{e}")

        wrapped_text = self._wrap_text(text)
        temp_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp_img)
        bbox = draw.textbbox((0, 0), wrapped_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        padding = 15
        img = Image.new(
            "RGBA",
            (text_width + 2 * padding, text_height + 2 * padding),
            (0, 0, 0, 200)
        )
        draw = ImageDraw.Draw(img)
        draw.text(
            (padding - bbox[0], padding - bbox[1]),
            wrapped_text,
            font=font,
            fill=(255, 255, 255, 255)
        )
        return img

    def _update_overlay(self):
        if self._stop_event.is_set() or not self.overlay_handle:
            return

        if self.db_updated:
            try:
                with self._state_lock:
                    text = self.current_text
                text_img = self._render_text(text)
                text_img.save(self.temp_texture)
                self.vr_overlay.setOverlayFromFile(self.overlay_handle, str(self.temp_texture))
                self._log(f"VR显示已更新：{text[:30]}...")
                with self._state_lock:
                    self.db_updated = False
            except Exception as e:
                self._log(f"Overlay更新失败：{e}")

    def _validate_database(self, cursor):
        try:
            cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            if self.target_field not in columns:
                self._log(f"错误：表 {self.table_name} 缺少字段 {self.target_field}")
                self._log(f"当前字段：{columns}")
                return False
            self.actual_field = self.target_field
            return True
        except Exception as e:
            self._log(f"数据库验证失败：{e}")
            return False

    def _load_latest(self):
        """初始加载最新记录"""
        if not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            if not self._validate_database(cursor):
                conn.close()
                return

            cursor.execute(f"""
                SELECT Id, {self.actual_field} 
                FROM {self.table_name} 
                ORDER BY Id DESC 
                LIMIT 1
            """)
            latest = cursor.fetchone()
            if latest:
                with self._state_lock:
                    self.last_rowid, self.current_text = latest
                    self.db_updated = True
                self._log(f"初始加载最新翻译：{self.current_text}")
            conn.close()
        except Exception as e:
            self._log(f"加载数据失败：{e}")

    def _monitor_db(self):
        while self.running and not self._stop_event.is_set():
            if not self.db_path.exists():
                time.sleep(2)
                continue
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()

                if not self.actual_field and not self._validate_database(cursor):
                    conn.close()
                    time.sleep(5)
                    continue

                with self._state_lock:
                    last_rowid = self.last_rowid
                cursor.execute(f"""
                    SELECT Id, {self.actual_field} 
                    FROM {self.table_name} 
                    WHERE Id > ? 
                    ORDER BY Id DESC 
                    LIMIT 1
                """, (last_rowid,))
                new_row = cursor.fetchone()

                if new_row:
                    with self._state_lock:
                        self.last_rowid, self.current_text = new_row
                        self.db_updated = True
                    self._log(f"检测到新翻译（ID: {self.last_rowid}）：{self.current_text}")

                conn.close()
            except Exception as e:
                self._log(f"数据库监听错误：{e}")
                time.sleep(3)
            time.sleep(1)

    def start(self):
        self.running = True
        self._stop_event.clear()
        if not self._init_steamvr():
            return

        self._load_latest()
        self._update_overlay()

        db_thread = threading.Thread(target=self._monitor_db, daemon=True)
        db_thread.start()

        try:
            self._log("Overlay启动（数据库变化时自动更新），按停止按钮或 Ctrl+C 退出...")
            while self.running and not self._stop_event.is_set():
                self._update_overlay()
                time.sleep(0.1)
        except KeyboardInterrupt:
            self._log("退出中...")
        finally:
            self.running = False
            self._stop_event.set()
            db_thread.join(timeout=2)
            self._shutdown()

    def _shutdown(self):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        if self.vr_overlay and self.overlay_handle:
            try:
                self.vr_overlay.hideOverlay(self.overlay_handle)
                self.vr_overlay.destroyOverlay(self.overlay_handle)
            except Exception:
                pass
        try:
            openvr.shutdown()
        except Exception:
            pass
        self._log("程序退出")


class SteamVRTransViewApp:
    BG = "#0f172a"
    PANEL = "#111827"
    PANEL_2 = "#0b1220"
    BORDER = "#243047"
    TEXT = "#e5eef9"
    MUTED = "#94a3b8"
    ACCENT = "#38bdf8"
    ACCENT_2 = "#22c55e"
    WARN = "#f59e0b"
    ERROR = "#fb7185"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SteamVR TransView")
        self.root.geometry("980x660")
        self.root.minsize(900, 620)
        self.root.configure(bg=self.BG)

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("Root.TLabel", background=self.BG, foreground=self.TEXT)
        self.style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED)
        self.style.configure("Card.TFrame", background=self.PANEL)
        self.style.configure("Accent.TButton", padding=(16, 10), background=self.ACCENT, foreground="#00111f")
        self.style.map("Accent.TButton", background=[("active", "#7dd3fc")])
        self.style.configure("Ghost.TButton", padding=(16, 10), background=self.PANEL_2, foreground=self.TEXT)
        self.style.map("Ghost.TButton", background=[("active", "#1f2937")])
        self.style.configure("Danger.TButton", padding=(16, 10), background=self.ERROR, foreground="#1f0a0f")
        self.style.map("Danger.TButton", background=[("active", "#fda4af")])
        self.style.configure("Path.TEntry", fieldbackground="#0b1220", foreground=self.TEXT, insertcolor=self.TEXT)

        self.log_queue = queue.Queue()
        self.overlay = None
        self.worker_thread = None
        self.is_running = False
        self.closing = False
        self.status_phase = 0

        default_db = r"D:\livecap\translation_history.db"
        self.db_path_var = tk.StringVar(value=default_db)
        self.status_var = tk.StringVar(value="待启动")
        self.detail_var = tk.StringVar(value="选择数据库路径后启动后台叠加")
        self.preview_var = tk.StringVar(value="等待翻译数据...")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_logs)
        self.root.after(160, self._animate_status)
        self.root.after(200, self._refresh_snapshot)
        self.root.after(300, self._watch_worker)

    def _build_ui(self):
        main = tk.Frame(self.root, bg=self.BG)
        main.pack(fill="both", expand=True, padx=22, pady=18)

        header = tk.Frame(main, bg=self.BG)
        header.pack(fill="x")
        tk.Label(header, text="SteamVR TransView", bg=self.BG, fg=self.TEXT, font=("Segoe UI Semibold", 24)).pack(anchor="w")
        tk.Label(header, text="轻量化翻译悬浮控制台 · 标准库界面 · 后台实时监控", bg=self.BG, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 12))
        tk.Frame(header, bg=self.ACCENT, height=2).pack(fill="x")

        body = tk.Frame(main, bg=self.BG)
        body.pack(fill="both", expand=True, pady=(18, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        status_card = tk.Frame(body, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)
        status_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        control_card = tk.Frame(body, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)
        control_card.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
        log_card = tk.Frame(body, bg=self.PANEL_2, highlightthickness=1, highlightbackground=self.BORDER)
        log_card.grid(row=1, column=0, columnspan=2, sticky="nsew")

        tk.Label(status_card, text="实时状态", bg=self.PANEL, fg=self.TEXT, font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(18, 8))
        status_row = tk.Frame(status_card, bg=self.PANEL)
        status_row.pack(fill="x", padx=18)
        self.status_canvas = tk.Canvas(status_row, width=24, height=24, bg=self.PANEL, highlightthickness=0)
        self.status_canvas.pack(side="left")
        self.status_dot = self.status_canvas.create_oval(4, 4, 20, 20, fill=self.MUTED, outline=self.MUTED)
        tk.Label(status_row, textvariable=self.status_var, bg=self.PANEL, fg=self.TEXT, font=("Segoe UI Semibold", 12)).pack(side="left", padx=10)
        tk.Label(status_card, textvariable=self.detail_var, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10), wraplength=520, justify="left").pack(anchor="w", padx=18, pady=(10, 14))

        preview_box = tk.Frame(status_card, bg=self.PANEL_2, highlightthickness=1, highlightbackground=self.BORDER)
        preview_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tk.Label(preview_box, text="最新翻译", bg=self.PANEL_2, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(12, 0))
        tk.Label(preview_box, textvariable=self.preview_var, bg=self.PANEL_2, fg=self.TEXT, font=("Segoe UI", 12), wraplength=500, justify="left").pack(anchor="w", padx=14, pady=(8, 14))

        tk.Label(control_card, text="控制面板", bg=self.PANEL, fg=self.TEXT, font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(18, 8))
        tk.Label(control_card, text="数据库路径", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        path_row = tk.Frame(control_card, bg=self.PANEL)
        path_row.pack(fill="x", padx=18, pady=(8, 12))
        self.path_entry = ttk.Entry(path_row, textvariable=self.db_path_var, style="Path.TEntry")
        self.path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="浏览", command=self._choose_db_path, style="Ghost.TButton").pack(side="left", padx=(10, 0))

        action_row = tk.Frame(control_card, bg=self.PANEL)
        action_row.pack(fill="x", padx=18, pady=(4, 12))
        self.start_button = ttk.Button(action_row, text="启动", command=self._start_overlay, style="Accent.TButton")
        self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(action_row, text="停止", command=self._stop_overlay, style="Danger.TButton", state="disabled")
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(10, 0))

        tips = (
            "1. 先启动 SteamVR 和 LiveCaptions-Translator\n"
            "2. 选中 translation_history.db 后点击启动\n"
            "3. 界面会保持轻量轮询，不做重型动画"
        )
        tk.Label(control_card, text=tips, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10), justify="left").pack(anchor="w", padx=18, pady=(2, 18))

        tk.Label(log_card, text="运行日志", bg=self.PANEL_2, fg=self.TEXT, font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=18, pady=(14, 8))
        self.log_text = tk.Text(log_card, height=8, bg="#08111f", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", borderwidth=0, highlightthickness=0, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.log_text.configure(state="disabled")

    def _enqueue_log(self, message):
        self.log_queue.put(message)

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_logs(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._append_log(message)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(80, self._drain_logs)

    def _animate_status(self):
        if self.is_running:
            palette = ["#38bdf8", "#22c55e", "#67e8f9", "#34d399"]
            fill = palette[self.status_phase % len(palette)]
            self.status_phase += 1
        else:
            fill = self.MUTED
        self.status_canvas.itemconfig(self.status_dot, fill=fill, outline=fill)
        if not self.closing:
            self.root.after(160, self._animate_status)

    def _refresh_snapshot(self):
        if self.overlay:
            snap = self.overlay.snapshot()
            self.preview_var.set(snap["current_text"])
            if snap["running"]:
                self.status_var.set("运行中")
                self.detail_var.set(f"数据库：{snap['db_path']} · 最新行号：{snap['last_rowid']}")
            else:
                self.status_var.set("已停止")
                self.detail_var.set(f"数据库：{snap['db_path']}")
        else:
            self.status_var.set("待启动")
            self.detail_var.set("选择数据库路径后启动后台叠加")
            self.preview_var.set("等待翻译数据...")
        if not self.closing:
            self.root.after(200, self._refresh_snapshot)

    def _watch_worker(self):
        if self.worker_thread and not self.worker_thread.is_alive():
            self.is_running = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.worker_thread = None
            if self.overlay:
                self.overlay = None
        if not self.closing:
            self.root.after(300, self._watch_worker)

    def _choose_db_path(self):
        selected = filedialog.askopenfilename(
            title="选择 translation_history.db",
            filetypes=[("SQLite 数据库", "*.db;*.sqlite;*.sqlite3"), ("所有文件", "*.*")],
        )
        if selected:
            self.db_path_var.set(selected)

    def _start_overlay(self):
        if self.is_running:
            return
        db_path = self.db_path_var.get().strip()
        if not db_path:
            messagebox.showwarning("提示", "请先选择数据库路径")
            return
        try:
            self.overlay = SteamVRTranslationOverlay(db_path=db_path, log_callback=self._enqueue_log)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))
            return

        self.is_running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("启动中")
        self.detail_var.set("正在初始化 SteamVR 和数据库监听...")
        self.worker_thread = threading.Thread(target=self.overlay.start, daemon=True)
        self.worker_thread.start()

    def _stop_overlay(self):
        if self.overlay:
            self.overlay.stop()
            self.status_var.set("停止中")
            self.detail_var.set("正在关闭 SteamVR 叠加层...")

    def _on_close(self):
        self.closing = True
        if self.overlay:
            self.overlay.stop()

        deadline = time.time() + 2.5

        def finish_close():
            if self.worker_thread and self.worker_thread.is_alive() and time.time() < deadline:
                self.root.after(100, finish_close)
                return
            try:
                self.root.destroy()
            except Exception:
                pass

        finish_close()

    def run(self):
        self.root.mainloop()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        try:
            app = SteamVRTranslationOverlay()
            app.start()
        except Exception as e:
            print(f"启动失败：{e}")
            input("按任意键关闭...")
            sys.exit(1)
        return

    app = SteamVRTransViewApp()
    app.run()


if __name__ == "__main__":
    main()
