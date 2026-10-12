"""核心：单图处理、命名清洗、移动、manifest、undo。"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("organizer")

MANIFEST_NAME = "manifest.jsonl"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_lock = threading.Lock()


def sanitize_name(name: str, max_len: int) -> str:
    name = _ILLEGAL.sub("", name or "")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > max_len:
        name = name[:max_len].strip()
    return name or "截图"


def timestamp_for(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d_%H%M%S")


def unique_dest(output_dir: Path, category: str, stem: str, ext: str) -> Path:
    cat_dir = output_dir / sanitize_name(category, 20)
    dest = cat_dir / f"{stem}{ext}"
    i = 1
    while dest.exists():
        dest = cat_dir / f"{stem}_{i}{ext}"
        i += 1
    return dest


def manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_NAME


def append_manifest(output_dir: Path, record: dict) -> None:
    mp = manifest_path(output_dir)
    with _lock:
        mp.parent.mkdir(parents=True, exist_ok=True)
        with mp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def plan_dest(path: Path, label: dict, cfg) -> Path:
    name = sanitize_name(label.get("name", ""), cfg.name_max_len)
    stem = f"{timestamp_for(path)}_{name}"
    category = label.get("category") or "其他"
    return unique_dest(cfg.output_dir, category, stem, path.suffix.lower())


def process_file(path: Path, label: dict, cfg, *, batch_id: str, provider,
                 dry_run: bool, usage: dict | None = None,
                 estimated_list_cost_cny: float = 0.0,
                 pricing_updated_at: str | None = None) -> dict:
    dest = plan_dest(path, label, cfg)
    result = {
        "original": str(path), "dest": str(dest), "category": dest.parent.name,
        "name": label.get("name", ""), "summary": label.get("summary", ""),
        "provider": provider.name, "model": provider.model,
        "usage": usage or {},
        "estimated_list_cost_cny": estimated_list_cost_cny,
        "pricing_updated_at": pricing_updated_at,
    }
    if dry_run:
        result["status"] = "dry-run"
        return result
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    append_manifest(cfg.output_dir, {
        "batch_id": batch_id,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "original": str(path), "dest": str(dest), "category": dest.parent.name,
        "name": label.get("name", ""), "summary": label.get("summary", ""),
        "provider": provider.name, "model": provider.model,
        "usage": usage or {},
        "estimated_list_cost_cny": estimated_list_cost_cny,
        "pricing_updated_at": pricing_updated_at,
    })
    result["status"] = "moved"
    return result


def undo(cfg, last_only: bool) -> int:
    mp = manifest_path(cfg.output_dir)
    if not mp.exists():
        print("没有 manifest，无可回滚。")
        return 0
    lines = [json.loads(s) for s in mp.read_text(encoding="utf-8").splitlines() if s.strip()]
    if not lines:
        print("manifest 为空。")
        return 0

    target_batch = lines[-1]["batch_id"] if last_only else None
    kept: list[dict] = []
    undone = 0
    for rec in lines:
        if last_only and rec.get("batch_id") != target_batch:
            kept.append(rec)
            continue
        dest = Path(rec["dest"])
        original = Path(rec["original"])
        if not dest.exists():
            log.warning("跳过（目标不存在）：%s", dest)
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        tgt = original
        i = 1
        while tgt.exists():
            tgt = original.with_name(f"{original.stem}_restored{i}{original.suffix}")
            i += 1
        shutil.move(str(dest), str(tgt))
        undone += 1

    with _lock:
        if kept:
            mp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + "\n",
                          encoding="utf-8")
        else:
            mp.unlink(missing_ok=True)

    # 清理空的分类文件夹
    if cfg.output_dir.exists():
        for sub in cfg.output_dir.iterdir():
            if sub.is_dir():
                try:
                    sub.rmdir()
                except OSError:
                    pass

    print(f"已回滚 {undone} 个文件。")
    return undone
