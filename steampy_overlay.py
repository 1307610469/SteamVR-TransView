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
try:
    import openvr  # pyright: ignore[reportMissingImports]
except Exception:
    openvr = None
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
            if openvr is None:
                raise ModuleNotFoundError("openvr 未安装或未被打包到运行环境")
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
    BG = "#f5f5f7"
    SURFACE = "#ffffff"
    SURFACE_SOFT = "#fbfbfd"
    BORDER = "#d2d2d7"
    TEXT = "#1d1d1f"
    MUTED = "#6e6e73"
    ACCENT = "#0071e3"
    ACCENT_SOFT = "#e8f2ff"
    GREEN = "#34c759"
    RED = "#ff3b30"
    SHADOW = "#ececf2"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SteamVR TransView")
        self.root.geometry("1040x720")
        self.root.minsize(940, 640)
        self.root.configure(bg=self.BG)

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("Apple.TFrame", background=self.SURFACE)
        self.style.configure("AppleSoft.TFrame", background=self.SURFACE_SOFT)
        self.style.configure("Apple.TLabel", background=self.BG, foreground=self.TEXT)
        self.style.configure("AppleMuted.TLabel", background=self.BG, foreground=self.MUTED)
        self.style.configure("AppleCard.TLabel", background=self.SURFACE, foreground=self.TEXT)
        self.style.configure("Accent.TButton", padding=(18, 10), background=self.ACCENT, foreground="#ffffff")
        self.style.map("Accent.TButton", background=[("active", "#0a84ff")])
        self.style.configure("Neutral.TButton", padding=(18, 10), background="#f2f2f7", foreground=self.TEXT)
        self.style.map("Neutral.TButton", background=[("active", "#e5e5ea")])
        self.style.configure("Danger.TButton", padding=(18, 10), background=self.RED, foreground="#ffffff")
        self.style.map("Danger.TButton", background=[("active", "#ff453a")])
        self.style.configure("Apple.TEntry", fieldbackground="#ffffff", foreground=self.TEXT, insertcolor=self.TEXT)

        self.log_queue = queue.Queue()
        self.overlay = None
        self.worker_thread = None
        self.is_running = False
        self.closing = False
        self.status_phase = 0
        self.main_ready = False
        self.startup_checks = []
        self.check_rows = []

        default_db = r"D:\livecap\translation_history.db"
        self.db_path_var = tk.StringVar(value=default_db)
        self.status_var = tk.StringVar(value="待启动")
        self.detail_var = tk.StringVar(value="选择数据库路径后启动后台叠加")
        self.preview_var = tk.StringVar(value="等待翻译数据...")
        self.startup_status_var = tk.StringVar(value="正在执行启动自检...")

        self._build_startup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._run_startup_checks)
        self.root.after(80, self._drain_logs)
        self.root.after(160, self._animate_status)
        self.root.after(220, self._refresh_snapshot)
        self.root.after(320, self._watch_worker)

    def _startup_font_path(self):
        return str(get_runtime_dir() / "font" / "gnuunifontfull-pm9p.ttf")

    def _startup_dll_path(self):
        return str(get_runtime_dir() / "libopenvr_api_64.dll")

    def _check_font_resource(self):
        return (get_runtime_dir() / "font" / "gnuunifontfull-pm9p.ttf").exists()

    def _check_openvr_dll(self):
        return (get_runtime_dir() / "libopenvr_api_64.dll").exists()

    def _build_startup_ui(self):
        self.startup_frame = tk.Frame(self.root, bg=self.BG)
        self.startup_frame.pack(fill="both", expand=True)

        shell = tk.Frame(self.startup_frame, bg=self.BG)
        shell.place(relx=0.5, rely=0.5, anchor="center")

        card = tk.Frame(shell, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        card.configure(width=660, height=460)
        card.pack_propagate(False)
        card.pack()

        header = tk.Frame(card, bg=self.SURFACE)
        header.pack(fill="x", padx=30, pady=(28, 8))
        tk.Label(header, text="SteamVR TransView", bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI", 28, "bold")).pack(anchor="w")
        tk.Label(header, text="Apple-inspired lightweight control surface", bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))
        tk.Frame(card, bg=self.BORDER, height=1).pack(fill="x", padx=30, pady=(16, 18))

        self.check_list = tk.Frame(card, bg=self.SURFACE)
        self.check_list.pack(fill="x", padx=30)
        self._add_check_row("界面框架", "等待检查")
        self._add_check_row("字体资源", "等待检查")
        self._add_check_row("OpenVR DLL", "等待检查")
        self._add_check_row("数据库路径", "等待检查")
        self._add_check_row("OpenVR 模块", "等待检查")

        bottom = tk.Frame(card, bg=self.SURFACE)
        bottom.pack(fill="both", expand=True, padx=30, pady=(20, 26))
        self.startup_detail = tk.Label(bottom, text="", bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 10), wraplength=570, justify="left")
        self.startup_detail.pack(anchor="w", pady=(0, 14))
        tk.Label(bottom, textvariable=self.startup_status_var, bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI Semibold", 12)).pack(anchor="w")

        action = tk.Frame(bottom, bg=self.SURFACE)
        action.pack(side="bottom", fill="x")
        self.enter_button = ttk.Button(action, text="继续进入", command=self._enter_main_ui, style="Accent.TButton", state="disabled")
        self.enter_button.pack(anchor="e")

    def _add_check_row(self, title, status):
        row = tk.Frame(self.check_list, bg=self.SURFACE)
        row.pack(fill="x", pady=7)
        indicator = tk.Canvas(row, width=18, height=18, bg=self.SURFACE, highlightthickness=0)
        indicator.pack(side="left")
        dot = indicator.create_oval(4, 4, 14, 14, fill="#c7c7cc", outline="#c7c7cc")
        label = tk.Label(row, text=f"{title} · {status}", bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI", 11))
        label.pack(side="left", padx=12)
        self.check_rows.append((indicator, dot, label, title))

    def _set_check_row(self, index, status_text, color):
        indicator, dot, label, title = self.check_rows[index]
        indicator.itemconfig(dot, fill=color, outline=color)
        label.configure(text=f"{title} · {status_text}")

    def _run_startup_checks(self):
        self.startup_checks = [
            ("界面框架", True, "Tkinter 已加载，当前为轻量 Apple 风格界面。"),
            ("字体资源", self._check_font_resource(), f"字体路径：{self._startup_font_path()}"),
            ("OpenVR DLL", self._check_openvr_dll(), f"DLL 路径：{self._startup_dll_path()}"),
            ("数据库路径", Path(self.db_path_var.get()).exists(), f"当前路径：{self.db_path_var.get()}"),
            ("OpenVR 模块", openvr is not None, "openvr 模块可用。" if openvr is not None else "openvr 尚未加载，启动后会提示。"),
        ]

        all_ok = True
        for index, (_, ok, detail) in enumerate(self.startup_checks):
            self._set_check_row(index, "通过" if ok else "未通过", self.GREEN if ok else self.RED)
            if not ok:
                all_ok = False
            self.startup_detail.configure(text=detail)

        self.startup_status_var.set("自检完成，点击继续进入主界面" if all_ok else "自检完成，存在可选项未通过，但仍可继续")
        self.enter_button.configure(state="normal")

    def _enter_main_ui(self):
        if self.main_ready:
            return
        self.main_ready = True
        self.startup_frame.destroy()
        self._build_main_ui()

    def _build_main_ui(self):
        main = tk.Frame(self.root, bg=self.BG)
        main.pack(fill="both", expand=True, padx=24, pady=22)

        top = tk.Frame(main, bg=self.BG)
        top.pack(fill="x")
        tk.Label(top, text="SteamVR TransView", bg=self.BG, fg=self.TEXT, font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(top, text="A clean, lightweight control surface for VR translation overlay", bg=self.BG, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        status_pill = tk.Frame(top, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        status_pill.pack(anchor="e")
        tk.Label(status_pill, textvariable=self.status_var, bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI Semibold", 10)).pack(side="left", padx=(12, 10), pady=6)
        self.status_canvas = tk.Canvas(status_pill, width=18, height=18, bg=self.SURFACE, highlightthickness=0)
        self.status_canvas.pack(side="left", padx=(0, 12))
        self.status_dot = self.status_canvas.create_oval(4, 4, 14, 14, fill="#c7c7cc", outline="#c7c7cc")

        content = tk.Frame(main, bg=self.BG)
        content.pack(fill="both", expand=True, pady=(18, 0))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=0)

        left = tk.Frame(content, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = tk.Frame(content, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        right.grid(row=0, column=1, sticky="nsew")
        log_card = tk.Frame(content, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        log_card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))

        tk.Label(left, text="实时状态", bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=22, pady=(20, 8))
        tk.Label(left, textvariable=self.detail_var, bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 10), wraplength=570, justify="left").pack(anchor="w", padx=22)

        preview = tk.Frame(left, bg=self.SURFACE_SOFT, highlightthickness=1, highlightbackground=self.BORDER)
        preview.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(preview, text="最新翻译", bg=self.SURFACE_SOFT, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(preview, textvariable=self.preview_var, bg=self.SURFACE_SOFT, fg=self.TEXT, font=("Segoe UI", 14), wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(10, 16))

        tk.Label(right, text="控制", bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=22, pady=(20, 8))
        tk.Label(right, text="数据库路径", bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=22)
        path_row = tk.Frame(right, bg=self.SURFACE)
        path_row.pack(fill="x", padx=22, pady=(8, 14))
        self.path_entry = ttk.Entry(path_row, textvariable=self.db_path_var, style="Apple.TEntry")
        self.path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="浏览", command=self._choose_db_path, style="Neutral.TButton").pack(side="left", padx=(10, 0))

        action_row = tk.Frame(right, bg=self.SURFACE)
        action_row.pack(fill="x", padx=22, pady=(6, 14))
        self.start_button = ttk.Button(action_row, text="启动", command=self._start_overlay, style="Accent.TButton")
        self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(action_row, text="停止", command=self._stop_overlay, style="Danger.TButton", state="disabled")
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(10, 0))

        notes = (
            "先启动 SteamVR 和 LiveCaptions-Translator。\n"
            "选择 translation_history.db 后再启动。\n"
            "界面采用低负载刷新，不做重动画。"
        )
        tk.Label(right, text=notes, bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 10), justify="left", wraplength=300).pack(anchor="w", padx=22, pady=(6, 20))

        tk.Label(log_card, text="运行日志", bg=self.SURFACE, fg=self.TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=22, pady=(16, 8))
        self.log_text = tk.Text(log_card, height=8, bg="#fbfbfd", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", borderwidth=0, highlightthickness=0, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        self.log_text.configure(state="disabled")

        self.root.after(80, self._drain_logs)
        self.root.after(160, self._animate_status)
        self.root.after(220, self._refresh_snapshot)
        self.root.after(320, self._watch_worker)

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
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(80, self._drain_logs)

    def _animate_status(self):
        if hasattr(self, "status_canvas") and hasattr(self, "status_dot"):
            if self.is_running:
                palette = [self.ACCENT, self.GREEN, "#5ac8fa", "#64d2ff"]
                fill = palette[self.status_phase % len(palette)]
                self.status_phase += 1
            else:
                fill = "#c7c7cc"
            self.status_canvas.itemconfig(self.status_dot, fill=fill, outline=fill)
        if not self.closing:
            self.root.after(180, self._animate_status)

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
            self.root.after(220, self._refresh_snapshot)

    def _watch_worker(self):
        if self.worker_thread and not self.worker_thread.is_alive():
            self.is_running = False
            self.worker_thread = None
            if hasattr(self, "start_button"):
                self.start_button.configure(state="normal")
            if hasattr(self, "stop_button"):
                self.stop_button.configure(state="disabled")
            self.overlay = None
        if not self.closing:
            self.root.after(320, self._watch_worker)

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
