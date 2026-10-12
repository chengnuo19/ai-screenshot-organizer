"""监听截图目录，新图到达即整理。"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import organizer

log = logging.getLogger("organizer")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def wait_until_stable(path: Path, timeout: float = 15.0) -> bool:
    """等待文件写完：size 连续两次不变且可打开。"""
    last = -1
    waited = 0.0
    while waited < timeout:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size > 0 and size == last:
            try:
                with path.open("rb"):
                    return True
            except OSError:
                pass
        last = size
        time.sleep(0.5)
        waited += 0.5
    return False


class Handler(FileSystemEventHandler):
    def __init__(self, cfg, router, batch_id):
        self.cfg = cfg
        self.router = router
        self.batch_id = batch_id
        self._seen: set[str] = set()

    def _handle(self, src: str) -> None:
        path = Path(src)
        if path.suffix.lower() not in IMAGE_EXT:
            return
        if str(path) in self._seen:
            return
        self._seen.add(str(path))
        if not wait_until_stable(path):
            log.warning("文件未就绪，跳过：%s", path.name)
            return
        try:
            call = self.router.label(path)
            res = organizer.process_file(
                path, call.label, self.cfg, batch_id=self.batch_id,
                provider=call.provider, dry_run=False, usage=call.usage,
                estimated_list_cost_cny=call.estimated_list_cost_cny,
                pricing_updated_at=call.pricing_updated_at)
        except Exception as e:
            log.error("处理失败 %s: %s", path.name, e)
            return
        print(f"已整理 {path.name} -> {res['category']}/{Path(res['dest']).name}")

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def run_watch(cfg, router) -> None:
    batch_id = "watch-" + datetime.now().strftime("%Y%m%d_%H%M%S")
    handler = Handler(cfg, router, batch_id)
    obs = Observer()
    obs.schedule(handler, str(cfg.watch_dir), recursive=False)
    obs.start()
    print(f"正在监听：{cfg.watch_dir}  （Ctrl+C 退出）")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()
    print("已停止监听。")
