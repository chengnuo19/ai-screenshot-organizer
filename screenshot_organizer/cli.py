"""Command line interface."""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw

from . import organizer
from .config import ConfigError, load_config
from .llm import Labeler, ProviderRouter, ProviderUnavailableError
from .watcher import run_watch

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _list_images(watch_dir: Path) -> list[Path]:
    if not watch_dir.exists():
        raise SystemExit(f"监听目录不存在：{watch_dir}")
    return sorted(
        path for path in watch_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXT)


def cmd_config_init(args) -> None:
    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"配置已存在：{output}（使用 --force 覆盖）")
    template = files("screenshot_organizer").joinpath(
        "default_config.yaml").read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding="utf-8")
    print(f"已创建配置：{output}")


def cmd_config_validate(args) -> None:
    cfg = load_config(args.config)
    for name in cfg.providers:
        cfg.provider(name)
    print(f"配置有效：{cfg.path}")


def cmd_providers_list(args) -> None:
    cfg = load_config(args.config)
    for name in cfg.providers:
        provider = cfg.provider(name)
        if provider.api_key_required and not provider.api_key:
            status = f"缺少 {provider.api_key_env}"
        else:
            status = "可用"
        print(
            f"{name:10} {provider.adapter:20} "
            f"{provider.model:24} {status}")


def _test_image(directory: str) -> Path:
    path = Path(directory) / "provider-test.png"
    image = Image.new("RGB", (480, 240), "white")
    ImageDraw.Draw(image).text(
        (30, 100), "AI Screenshot Organizer Test", fill="black")
    image.save(path)
    return path


def cmd_providers_test(args) -> None:
    cfg = load_config(args.config)
    if args.all:
        names = list(cfg.providers)
    elif args.provider:
        names = [args.provider]
    else:
        names = cfg.provider_order
    failures = 0
    with tempfile.TemporaryDirectory() as directory:
        image = _test_image(directory)
        for name in names:
            provider = cfg.provider(name)
            if provider.api_key_required and not provider.api_key:
                print(f"{name}: 跳过（缺少 {provider.api_key_env}）")
                continue
            try:
                call = Labeler(cfg, provider).label_call(image)
                print(
                    f"{name}: 成功 model={provider.model} "
                    f"name={call.label['name']}")
            except Exception as exc:
                failures += 1
                print(f"{name}: 失败 {exc}")
    if failures:
        raise SystemExit(1)


def cmd_batch(cfg, providers, args) -> None:
    router = ProviderRouter(cfg, providers)
    images = _list_images(cfg.watch_dir)
    if args.limit:
        images = images[:args.limit]
    if not images:
        print("没有找到待处理截图。")
        return

    route = " -> ".join(provider.name for provider in router.providers)
    print(
        f"待处理 {len(images)} 张"
        f"（provider_order={route}, dry_run={args.dry_run}）")
    if not args.dry_run and not args.yes and not args.limit:
        answer = input(
            f"将移动 {len(images)} 个文件到 {cfg.output_dir}，继续？[y/N] "
        ).strip().lower()
        if answer != "y":
            print("已取消。")
            return

    batch_id = "batch-" + datetime.now().strftime("%Y%m%d_%H%M%S")
    workers = max(1, args.workers or cfg.workers)
    categories: Counter = Counter()
    provider_counts: Counter = Counter()
    list_costs: Counter = Counter()
    ok = fail = 0

    try:
        from tqdm import tqdm
    except Exception:
        def tqdm(iterator, **_):
            return iterator

    def work(path: Path) -> dict:
        call = router.label(path)
        return organizer.process_file(
            path,
            call.label,
            cfg,
            batch_id=batch_id,
            provider=call.provider,
            dry_run=args.dry_run,
            usage=call.usage,
            estimated_list_cost_cny=call.estimated_list_cost_cny,
            pricing_updated_at=call.pricing_updated_at,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(work, path): path for path in images}
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="整理中"
        ):
            path = futures[future]
            try:
                result = future.result()
                categories[result["category"]] += 1
                provider_counts[result["provider"]] += 1
                list_costs[result["provider"]] += result[
                    "estimated_list_cost_cny"]
                ok += 1
                if args.dry_run:
                    print(
                        f"[预览] {path.name} -> "
                        f"{result['category']}/{Path(result['dest']).name}")
            except Exception as exc:
                fail += 1
                logging.error("失败 %s: %s", path.name, exc)

    print("\n=== 完成 ===")
    print(f"成功 {ok}，失败 {fail}")
    for category, count in categories.most_common():
        print(f"  {category}: {count}")
    for name, count in provider_counts.items():
        print(
            f"  {name}: {count} 次，公开单价估算 "
            f"{list_costs[name]:.6f} 元")
    print("  注：估算不代表现金实扣，不含资源包、赠送额度或折扣。")
    if not args.dry_run:
        print(f"输出目录：{cfg.output_dir}")
        print("如需回滚：screenshot-organizer undo --last")


def cmd_watch(cfg, providers, args) -> None:
    run_watch(cfg, ProviderRouter(cfg, providers))


def cmd_undo(cfg, providers, args) -> None:
    organizer.undo(cfg, last_only=args.last)


def _runtime_config(args):
    cfg = load_config(args.config)
    names = [args.provider] if args.provider else cfg.provider_order
    providers = [cfg.provider(name) for name in names]
    return cfg, providers


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-organizer",
        description="AI 截图自动命名与分类",
    )
    commands = parser.add_subparsers(dest="cmd", required=True)

    config = commands.add_parser("config", help="配置管理")
    config_commands = config.add_subparsers(dest="config_cmd", required=True)
    init = config_commands.add_parser("init", help="创建安全的默认配置")
    init.add_argument("--output", default="config.yaml")
    init.add_argument("--force", action="store_true")
    init.set_defaults(handler=cmd_config_init)
    validate = config_commands.add_parser("validate", help="验证配置")
    validate.add_argument("--config", default="config.yaml")
    validate.set_defaults(handler=cmd_config_validate)

    providers = commands.add_parser("providers", help="模型服务管理")
    provider_commands = providers.add_subparsers(
        dest="providers_cmd", required=True)
    list_cmd = provider_commands.add_parser("list", help="列出模型")
    list_cmd.add_argument("--config", default="config.yaml")
    list_cmd.set_defaults(handler=cmd_providers_list)
    test_cmd = provider_commands.add_parser("test", help="真实测试模型接口")
    test_cmd.add_argument("--config", default="config.yaml")
    test_cmd.add_argument("--provider")
    test_cmd.add_argument("--all", action="store_true")
    test_cmd.set_defaults(handler=cmd_providers_test)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="config.yaml 路径")
    common.add_argument("--provider", help="只使用指定 provider")

    batch = commands.add_parser(
        "batch", parents=[common], help="批量整理存量截图")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--limit", type=int)
    batch.add_argument("--workers", type=int)
    batch.add_argument("--yes", action="store_true")
    batch.set_defaults(handler=cmd_batch)

    watch = commands.add_parser(
        "watch", parents=[common], help="监听并整理新增截图")
    watch.set_defaults(handler=cmd_watch)

    undo = commands.add_parser(
        "undo", parents=[common], help="按 manifest 回滚")
    undo.add_argument("--last", action="store_true")
    undo.set_defaults(handler=cmd_undo)
    return parser


def main(argv=None) -> None:
    _setup_logging()
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd in {"config", "providers"}:
            args.handler(args)
            return
        cfg, providers = _runtime_config(args)
        args.handler(cfg, providers, args)
    except (ConfigError, ProviderUnavailableError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
