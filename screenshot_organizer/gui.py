"""Desktop GUI for AI Screenshot Organizer using Flet and Claude design system."""
import flet as ft
import logging
import threading
import json
import time
import yaml
import sys
import traceback
import tkinter
import tkinter.filedialog
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import load_config, ConfigError, _find_config
from .llm import ProviderRouter
from .cli import _list_images, _setup_logging
from . import organizer
from watchdog.observers import Observer
from .watcher import Handler

# Claude Design Tokens
CANVAS = "#faf9f5"
INK = "#141413"
PRIMARY = "#cc785c"
PRIMARY_ACTIVE = "#a9583e"
ON_PRIMARY = "#ffffff"
SURFACE_CARD = "#efe9de"
SURFACE_DARK = "#1e1c19"  # Warm dark brown-grey
ON_DARK = "#faf9f5"
ON_DARK_SOFT = "#a09d96"
HAIRLINE = "#e6dfd8"
MUTED = "#7c7a72"

# Robust System Fonts (no blocked Google Font downloads)
FONT_SANS = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"
FONT_SERIF = "Georgia, STSong, STHeiti, 'Times New Roman', serif"
FONT_MONO = "Consolas, 'Courier New', monospace"

log = logging.getLogger("organizer.gui")

class StdoutRedirector:
    def __init__(self, output_control, page):
        self.output_control = output_control
        self.page = page

    def write(self, text):
        if text.strip():
            self.output_control.value += text + "\n"
            self.page.update()

    def flush(self):
        pass


def get_writeable_config_path() -> Path:
    # 1. 尝试当前工作目录
    try:
        test_file = Path("config_test_write")
        test_file.touch()
        test_file.unlink()
        return Path("config.yaml")
    except Exception:
        pass

    # 2. 如果是打包运行，尝试可执行文件所在目录
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).parent
            test_file = exe_dir / "config_test_write"
            test_file.touch()
            test_file.unlink()
            return exe_dir / "config.yaml"
        except Exception:
            pass

    # 3. 兜底使用用户主目录下的专用文件夹
    user_dir = Path.home() / ".ai_screenshot_organizer"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "config.yaml"


def show_init_error(page: ft.Page, message: str):
    page.controls.clear()
    
    error_card = ft.Container(
        content=ft.Column([
            ft.Text("启动初始化失败", font_family=FONT_SERIF, size=24, weight=ft.FontWeight.BOLD, color=INK),
            ft.Container(height=4),
            ft.Text(message, font_family=FONT_MONO, color=MUTED, size=14, selectable=True),
            ft.Container(height=12),
            ft.ElevatedButton(
                "退出程序",
                bgcolor=PRIMARY,
                color=ON_PRIMARY,
                on_click=lambda _: page.window_close()
            )
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
        bgcolor=SURFACE_CARD,
        padding=32,
        border_radius=16,
        border=ft.Border.all(1, HAIRLINE),
        width=550,
        alignment=ft.alignment.Alignment(0, 0)
    )
    
    page.add(
        ft.Container(
            content=error_card,
            alignment=ft.alignment.Alignment(0, 0),
            expand=True
        )
    )
    page.update()


def build_gui(page: ft.Page):
    log.info("GUI build started")
    page.title = "AI 截图自动整理"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = CANVAS
    page.padding = 0

    # Configure modern theme and default font
    page.theme = ft.Theme(
        font_family=FONT_SANS,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )

    # 查找或生成配置文件
    try:
        config_file = _find_config(None)
    except ConfigError:
        config_file = get_writeable_config_path()
        if not config_file.exists():
            try:
                from importlib.resources import files
                template = files("screenshot_organizer").joinpath("default_config.yaml").read_text(encoding="utf-8")
                config_file.write_text(template, encoding="utf-8")
            except Exception as e:
                show_init_error(page, f"创建默认配置文件失败: {e}\n配置文件目标路径: {config_file}")
                return

    try:
        cfg = load_config(str(config_file))
        router = ProviderRouter(cfg, [cfg.provider(n) for n in cfg.provider_order])
        log.info("GUI config loaded: %s", config_file)
    except Exception as e:
        show_init_error(page, f"加载配置或初始化 AI 路由失败: {e}\n配置文件路径: {config_file}")
        return

    # === COMPONENTS ===

    # 1. Console Output
    console_text = ft.Text(
        "", 
        color=ON_DARK, 
        font_family=FONT_MONO, 
        size=13, 
        selectable=True
    )
    
    console_view = ft.Container(
        content=ft.Column([console_text], scroll=ft.ScrollMode.AUTO, auto_scroll=True),
        bgcolor=SURFACE_DARK,
        padding=20,
        border_radius=12,
        border=ft.Border.all(1, "#2c2824"),
        expand=True
    )

    def log_msg(msg: str):
        console_text.value += f"{datetime.now().strftime('%H:%M:%S')} - {msg}\n"
        page.update()

    def clear_console(e):
        console_text.value = ""
        page.update()

    console_header = ft.Row([
        ft.Row([
            ft.Text("运行日志 (Console Output)", font_family=FONT_SANS, size=16, color=INK, weight=ft.FontWeight.W_500),
        ], spacing=8),
        ft.TextButton(
            "清空",
            tooltip="清空日志",
            on_click=clear_console
        )
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    # 2. Dashboard
    def get_pending_count():
        try:
            return len(_list_images(cfg.watch_dir))
        except:
            return 0

    pending_count_number = ft.Text(
        str(get_pending_count()), 
        color=PRIMARY, 
        font_family=FONT_SERIF, 
        size=48,
        weight=ft.FontWeight.BOLD
    )
    
    pending_count_label = ft.Text(
        " 张截图待处理", 
        color=INK, 
        font_family=FONT_SANS, 
        size=16
    )

    progress_bar = ft.ProgressBar(width=450, color=PRIMARY, bgcolor=HAIRLINE, visible=False, height=6)
    progress_text = ft.Text("", color=MUTED, font_family=FONT_SANS, size=13)

    def run_batch(dry_run: bool):
        images = _list_images(cfg.watch_dir)
        if not images:
            log_msg("没有找到待处理截图。")
            return
        
        btn_batch.disabled = True
        btn_batch_dry.disabled = True
        progress_bar.visible = True
        progress_bar.value = 0
        progress_text.value = f"0 / {len(images)}"
        page.update()

        batch_id = "batch-" + datetime.now().strftime("%Y%m%d_%H%M%S")
        
        def work(path: Path) -> dict:
            call = router.label(path)
            return organizer.process_file(
                path, call.label, cfg, batch_id=batch_id,
                provider=call.provider, dry_run=dry_run, usage=call.usage,
                estimated_list_cost_cny=call.estimated_list_cost_cny,
                pricing_updated_at=call.pricing_updated_at
            )

        def task():
            ok = fail = 0
            with ThreadPoolExecutor(max_workers=cfg.workers) as executor:
                futures = {executor.submit(work, p): p for p in images}
                done_count = 0
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        result = future.result()
                        ok += 1
                        log_msg(f"{'[预览] ' if dry_run else ''}{path.name} -> {result['category']}/{Path(result['dest']).name}")
                    except Exception as exc:
                        fail += 1
                        log_msg(f"失败 {path.name}: {exc}")
                    
                    done_count += 1
                    progress_bar.value = done_count / len(images)
                    progress_text.value = f"{done_count} / {len(images)}"
                    page.update()
            
            log_msg(f"完成！成功 {ok}，失败 {fail}")
            btn_batch.disabled = False
            btn_batch_dry.disabled = False
            progress_bar.visible = False
            progress_text.value = ""
            refresh_dashboard()

        threading.Thread(target=task, daemon=True).start()

    btn_batch = ft.ElevatedButton(
        "开始批量整理",
        bgcolor=PRIMARY,
        color=ON_PRIMARY,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=20, vertical=15),
        ),
        on_click=lambda _: run_batch(False)
    )
    
    btn_batch_dry = ft.OutlinedButton(
        "预览分类 (Dry Run)",
        style=ft.ButtonStyle(
            color=INK,
            shape=ft.RoundedRectangleBorder(radius=10),
            side=ft.BorderSide(1.5, PRIMARY),
            padding=ft.Padding.symmetric(horizontal=20, vertical=15),
        ),
        on_click=lambda _: run_batch(True)
    )

    # Watch Mode
    watch_observer = [None]
    
    def toggle_watch(e):
        if e.control.value:
            # Start watch
            log_msg(f"开始监听: {cfg.watch_dir}")
            batch_id = "watch-" + datetime.now().strftime("%Y%m%d_%H%M%S")
            class GuiHandler(Handler):
                def _handle(self, src: str):
                    path = Path(src)
                    log_msg(f"检测到新文件: {path.name}")
                    super()._handle(src)
                    refresh_dashboard()
            
            handler = GuiHandler(cfg, router, batch_id)
            obs = Observer()
            obs.schedule(handler, str(cfg.watch_dir), recursive=False)
            obs.start()
            watch_observer[0] = obs
        else:
            stop_watch()

    def stop_watch():
        if watch_observer[0]:
            try:
                watch_observer[0].stop()
                watch_observer[0].join()
            except:
                pass
            watch_observer[0] = None
        log_msg("已停止监听。")

    def restart_watch_if_active():
        if watch_switch.value and watch_observer[0]:
            try:
                watch_observer[0].stop()
                watch_observer[0].join()
            except:
                pass
            watch_observer[0] = None
            
            log_msg(f"重启监听目录: {cfg.watch_dir}")
            batch_id = "watch-" + datetime.now().strftime("%Y%m%d_%H%M%S")
            class GuiHandler(Handler):
                def _handle(self, src: str):
                    path = Path(src)
                    log_msg(f"检测到新文件: {path.name}")
                    super()._handle(src)
                    refresh_dashboard()
            
            handler = GuiHandler(cfg, router, batch_id)
            obs = Observer()
            obs.schedule(handler, str(cfg.watch_dir), recursive=False)
            obs.start()
            watch_observer[0] = obs

    watch_switch = ft.Switch(
        label="后台监听模式", 
        value=False, 
        active_color=PRIMARY, 
        on_change=toggle_watch
    )

    status_card = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("当前目录状态", font_family=FONT_SANS, size=16, color=MUTED, weight=ft.FontWeight.W_500),
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                pending_count_number,
                pending_count_label
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=4),
            ft.Row([btn_batch, btn_batch_dry], spacing=12),
            ft.Container(height=4),
            ft.Column([progress_bar, progress_text], spacing=4),
            ft.Divider(height=24, color=HAIRLINE),
            ft.Row([
                watch_switch,
                ft.Text("（监测到新截图时将自动使用最高优先级 AI 进行分类整理）", color=MUTED, size=12, font_family=FONT_SANS)
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ], spacing=12),
        bgcolor=SURFACE_CARD,
        padding=24,
        border_radius=16,
        border=ft.Border.all(1, HAIRLINE),
    )

    dashboard_view = ft.Container(
        content=ft.Column([
            ft.Text("仪表盘 (Dashboard)", font_family=FONT_SERIF, size=32, weight=ft.FontWeight.BOLD, color=INK),
            ft.Container(height=8),
            status_card,
            ft.Container(height=12),
            console_header,
            console_view
        ], expand=True, spacing=10),
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        expand=True
    )

    def refresh_dashboard():
        count = get_pending_count()
        pending_count_number.value = str(count)
        page.update()

    # === History View ===
    history_table = ft.DataTable(
        heading_row_color="#0d141413",
        divider_thickness=1,
        horizontal_lines=ft.BorderSide(1, HAIRLINE),
        columns=[
            ft.DataColumn(ft.Text("时间", font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK)),
            ft.DataColumn(ft.Text("分类", font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK)),
            ft.DataColumn(ft.Text("整理后名称", font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK)),
            ft.DataColumn(ft.Text("所用模型", font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK)),
            ft.DataColumn(ft.Text("原文件名", font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK)),
        ],
        rows=[]
    )
    
    def refresh_history():
        mp = organizer.manifest_path(cfg.output_dir)
        history_table.rows.clear()
        if mp.exists():
            lines = [json.loads(s) for s in mp.read_text(encoding="utf-8").splitlines() if s.strip()]
            for idx, rec in enumerate(reversed(lines[-50:])): # Show last 50
                ts_str = rec.get("ts", "")
                try:
                    dt = datetime.fromisoformat(ts_str)
                    ts_display = dt.strftime("%m-%d %H:%M:%S")
                except:
                    ts_display = ts_str
                
                row_color = "#05cc785c" if idx % 2 == 1 else None
                
                history_table.rows.append(
                    ft.DataRow(
                        color=row_color,
                        cells=[
                            ft.DataCell(ft.Text(ts_display, color=INK, size=13)),
                            ft.DataCell(ft.Text(rec.get("category", ""), color=PRIMARY, weight=ft.FontWeight.BOLD, size=13)),
                            ft.DataCell(ft.Text(rec.get("name", ""), color=INK, weight=ft.FontWeight.W_500, size=13)),
                            ft.DataCell(ft.Text(rec.get("model", rec.get("provider", "unknown")), color=MUTED, size=12)),
                            ft.DataCell(ft.Text(Path(rec.get("original", "")).name, color=MUTED, size=12)),
                        ]
                    )
                )
        page.update()

    def undo_last(e):
        undone = organizer.undo(cfg, last_only=True)
        log_msg(f"已撤销 {undone} 个文件。")
        refresh_history()
        refresh_dashboard()

    btn_undo = ft.OutlinedButton(
        "撤销上一次整理操作",
        style=ft.ButtonStyle(
            color=PRIMARY,
            shape=ft.RoundedRectangleBorder(radius=8),
            side=ft.BorderSide(1.5, PRIMARY),
            padding=ft.Padding.all(12),
        ),
        on_click=undo_last
    )

    history_view = ft.Container(
        content=ft.Column([
            ft.Text("历史记录 (History)", font_family=FONT_SERIF, size=32, weight=ft.FontWeight.BOLD, color=INK),
            ft.Container(height=8),
            ft.Row([btn_undo]),
            ft.Container(height=12),
            ft.Container(
                content=ft.Column([history_table], scroll=ft.ScrollMode.ALWAYS, expand=True),
                bgcolor=SURFACE_CARD,
                padding=16,
                border_radius=12,
                border=ft.Border.all(1, HAIRLINE),
                expand=True
            )
        ], expand=True, spacing=10),
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        expand=True,
        visible=False
    )

    # === Settings View ===
    # Use tkinter filedialog (native, works in Flet 0.85.3 without FilePicker)
    def _pick_dir(initial: str, title: str, callback):
        """Open a native folder-picker in a background thread, then call callback(path)."""
        def _run():
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = tkinter.filedialog.askdirectory(title=title, initialdir=initial)
            root.destroy()
            if path:
                callback(path)
                page.update()
        threading.Thread(target=_run, daemon=True).start()

    def select_watch_dir(e):
        _pick_dir(
            initial=watch_dir_field.value,
            title="选择截图监听目录",
            callback=lambda p: setattr(watch_dir_field, "value", p)
        )

    def select_output_dir(e):
        _pick_dir(
            initial=output_dir_field.value,
            title="选择输出整理目录",
            callback=lambda p: setattr(output_dir_field, "value", p)
        )

    watch_dir_field = ft.TextField(
        label="监听目录 (watch_dir)", 
        value=str(cfg.watch_dir), 
        expand=True,
        bgcolor=CANVAS, 
        color=INK,
        border_radius=8,
        border_color=HAIRLINE,
        read_only=True
    )
    
    output_dir_field = ft.TextField(
        label="输出目录 (output_dir)", 
        value=str(cfg.output_dir), 
        expand=True,
        bgcolor=CANVAS, 
        color=INK,
        border_radius=8,
        border_color=HAIRLINE,
        read_only=True
    )

    watch_row = ft.Row([
        watch_dir_field,
        ft.TextButton(
            "浏览",
            tooltip="浏览文件夹",
            on_click=select_watch_dir
        )
    ])
    
    output_row = ft.Row([
        output_dir_field,
        ft.TextButton(
            "浏览",
            tooltip="浏览文件夹",
            on_click=select_output_dir
        )
    ])

    # Model providers state management
    providers_state = []
    provider_list_container = ft.Column(spacing=8)

    def init_providers_state():
        nonlocal providers_state
        providers_state = []
        # Active ones in order
        for p in cfg.provider_order:
            if p in cfg.providers:
                providers_state.append({'name': p, 'active': True})
        # Inactive ones at the end
        for p in cfg.providers:
            if p not in cfg.provider_order:
                providers_state.append({'name': p, 'active': False})

    def render_providers_list(update_page: bool = True):
        provider_list_container.controls.clear()
        for idx, p in enumerate(providers_state):
            name = p['name']
            active = p['active']
            
            provider_config = cfg.providers.get(name, {})
            model_name = provider_config.get("model", "unknown")
            adapter_name = provider_config.get("adapter", "unknown")
            
            up_btn = ft.TextButton(
                "上移",
                disabled=idx == 0,
                tooltip="上移优先级",
                on_click=lambda _, i=idx: move_provider(i, -1)
            )
            down_btn = ft.TextButton(
                "下移",
                disabled=idx == len(providers_state) - 1,
                tooltip="下移优先级",
                on_click=lambda _, i=idx: move_provider(i, 1)
            )
            
            switch = ft.Switch(
                value=active,
                active_color=PRIMARY,
                on_change=lambda e, i=idx: toggle_provider(i, e.control.value)
            )
            
            item = ft.Container(
                content=ft.Row([
                    ft.Row([
                        ft.Column([
                            ft.Text(name.upper(), font_family=FONT_SANS, weight=ft.FontWeight.BOLD, color=INK if active else MUTED, size=14),
                            ft.Text(f"模型: {model_name} ({adapter_name})", font_family=FONT_SANS, color=MUTED, size=11),
                        ], spacing=2)
                    ], spacing=12, expand=True),
                    ft.Row([
                        up_btn,
                        down_btn,
                        switch
                    ], spacing=2)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                bgcolor=CANVAS if active else "#4defe9de",
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                border_radius=10,
                border=ft.Border.all(1, HAIRLINE if active else "#80e6dfd8")
            )
            provider_list_container.controls.append(item)
        if update_page:
            page.update()

    def move_provider(index: int, direction: int):
        new_index = index + direction
        if 0 <= new_index < len(providers_state):
            providers_state[index], providers_state[new_index] = providers_state[new_index], providers_state[index]
            render_providers_list()
            
    def toggle_provider(index: int, value: bool):
        providers_state[index]['active'] = value
        render_providers_list()

    init_providers_state()

    def save_settings(e):
        nonlocal cfg, router
        watch = watch_dir_field.value
        output = output_dir_field.value
        
        # Calculate new order
        order = [p['name'] for p in providers_state if p['active']]
        if not order:
            page.show_snack_bar(ft.SnackBar(content=ft.Text("错误：必须至少启用一个模型！"), bgcolor=ft.Colors.RED_800))
            return
            
        config_file = cfg.path
        try:
            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            data["watch_dir"] = watch
            data["output_dir"] = output
            data["provider_order"] = order
            
            # Write settings to file
            config_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            
            # Reload configuration
            cfg = load_config(str(config_file))
            router = ProviderRouter(cfg, [cfg.provider(n) for n in cfg.provider_order])
            
            # Refresh local variables and UI
            refresh_dashboard()
            restart_watch_if_active()
            
            page.show_snack_bar(ft.SnackBar(content=ft.Text("配置已成功保存！"), bgcolor=PRIMARY))
        except Exception as ex:
            log.error(f"保存配置失败: {ex}")
            page.show_snack_bar(ft.SnackBar(content=ft.Text(f"保存失败: {ex}"), bgcolor=ft.Colors.RED_800))

    btn_save_settings = ft.ElevatedButton(
        "保存配置",
        bgcolor=PRIMARY,
        color=ON_PRIMARY,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
        ),
        on_click=save_settings
    )

    settings_view = ft.Container(
        content=ft.Column([
            ft.Text("配置设置 (Settings)", font_family=FONT_SERIF, size=32, weight=ft.FontWeight.BOLD, color=INK),
            ft.Container(height=8),
            ft.Column([
                # Card 1: Directories
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("目录路径配置", font_family=FONT_SANS, size=16, weight=ft.FontWeight.BOLD, color=INK),
                        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Container(height=2),
                        watch_row,
                        output_row,
                        ft.Text("提示：修改路径后，请点击下方的“保存配置”按钮生效。", color=MUTED, font_family=FONT_SANS, size=12)
                    ], spacing=12),
                    bgcolor=SURFACE_CARD,
                    padding=20,
                    border_radius=12,
                    border=ft.Border.all(1, HAIRLINE),
                ),
                
                # Card 2: Models
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("AI 模型调用优先级", font_family=FONT_SANS, size=16, weight=ft.FontWeight.BOLD, color=INK),
                        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text("通过右侧的上下箭头调整调用优先级顺序，通过开关选择是否启用该模型。", color=MUTED, font_family=FONT_SANS, size=12),
                        ft.Container(height=2),
                        provider_list_container
                    ], spacing=12),
                    bgcolor=SURFACE_CARD,
                    padding=20,
                    border_radius=12,
                    border=ft.Border.all(1, HAIRLINE),
                ),
                
                ft.Row([btn_save_settings], alignment=ft.MainAxisAlignment.END)
            ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
        ], expand=True, spacing=10),
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        expand=True,
        visible=False
    )

    # Render providers in Settings on initialization
    render_providers_list(update_page=False)

    # === Navigation ===
    
    def nav_change(e):
        idx = e.control.selected_index
        dashboard_view.visible = (idx == 0)
        history_view.visible = (idx == 1)
        settings_view.visible = (idx == 2)
        if idx == 1:
            refresh_history()
        elif idx == 2:
            # Refresh directory inputs with loaded values
            watch_dir_field.value = str(cfg.watch_dir)
            output_dir_field.value = str(cfg.output_dir)
            init_providers_state()
            render_providers_list()
        page.update()

    nav_buttons = []

    def switch_tab(idx: int):
        dashboard_view.visible = (idx == 0)
        history_view.visible = (idx == 1)
        settings_view.visible = (idx == 2)
        content_host.content = [dashboard_view, history_view, settings_view][idx]
        if idx == 1:
            refresh_history()
        elif idx == 2:
            watch_dir_field.value = str(cfg.watch_dir)
            output_dir_field.value = str(cfg.output_dir)
            init_providers_state()
            render_providers_list()
        for i, button in enumerate(nav_buttons):
            button.bgcolor = SURFACE_CARD if i == idx else CANVAS
        page.update()

    def make_nav_button(label: str, idx: int):
        button = ft.Container(
            content=ft.Text(
                label,
                color=PRIMARY if idx == 0 else MUTED,
                font_family=FONT_SANS,
                size=13,
                weight=ft.FontWeight.BOLD if idx == 0 else ft.FontWeight.NORMAL,
            ),
            bgcolor=SURFACE_CARD if idx == 0 else CANVAS,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            on_click=lambda _: switch_tab(idx),
        )
        nav_buttons.append(button)
        return button

    sidebar = ft.Container(
        content=ft.Column(
            [
                make_nav_button("Dashboard", 0),
                make_nav_button("History", 1),
                make_nav_button("Settings", 2),
            ],
            spacing=8,
        ),
        bgcolor=CANVAS,
        padding=ft.Padding.symmetric(horizontal=12, vertical=24),
        width=130,
    )
    content_host = ft.Container(content=dashboard_view, expand=True)

    page.add(
        ft.Row(
            [
                sidebar,
                ft.VerticalDivider(width=1, color=HAIRLINE),
                content_host,
            ],
            expand=True,
        )
    )
    page.update()
    log.info("GUI main view rendered")

def setup_gui_logging():
    log_dir = Path.home() / ".ai_screenshot_organizer"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gui.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
        log.info(f"GUI 日志系统初始化成功，日志写入: {log_file}")
    except Exception as e:
        log.warning(f"无法初始化 GUI 文件日志系统: {e}")


def main():
    _setup_logging()
    setup_gui_logging()
    
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        log.critical("未捕获的异常", exc_info=(exc_type, exc_value, exc_traceback))
        sys.stderr.write("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

    sys.excepthook = handle_exception

    try:
        ft.app(target=build_gui)
    except Exception as e:
        log.critical(f"Flet App 启动失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
