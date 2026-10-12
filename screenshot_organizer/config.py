"""Configuration loading and validation."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

SUPPORTED_ADAPTERS = {"mock", "openai_compatible", "anthropic_messages", "host_pipe"}

_DEFAULTS = {
    "max_image_px": 1568,
    "name_max_len": 30,
    "workers": 2,
    "categories": ["代码", "报错", "聊天记录", "网页文章", "文档", "设计图", "数据图表",
                   "购物订单", "设置页面", "社交媒体", "视频截图", "游戏", "地图", "其他"],
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Pricing:
    input_per_million_cny: float
    output_per_million_cny: float
    context_window: int
    updated_at: str


@dataclass(frozen=True)
class Provider:
    name: str
    adapter: str
    base_url: str
    model: str
    api_key_env: str
    api_key: str | None
    api_key_required: bool
    max_tokens: int
    request_options: dict[str, Any] = field(default_factory=dict)
    pricing: Pricing | None = None
    max_estimated_request_cost_cny: float | None = None
    fallback_status_codes: tuple[int, ...] = (401, 403, 404)
    quota_exhausted_markers: tuple[str, ...] = ()


@dataclass
class Config:
    path: Path
    watch_dir: Path
    output_dir: Path
    provider_order: list[str]
    providers: dict[str, dict[str, Any]]
    max_image_px: int
    name_max_len: int
    workers: int
    categories: list[str]
    environment: dict[str, str]

    def provider(self, name: str) -> Provider:
        if name not in self.providers:
            raise ConfigError(
                f"未找到 provider '{name}'，可选: {', '.join(self.providers)}")
        raw = self.providers[name] or {}
        pricing_raw = raw.get("pricing")
        pricing = None
        if pricing_raw:
            pricing = Pricing(
                input_per_million_cny=float(
                    pricing_raw["input_per_million_cny"]),
                output_per_million_cny=float(
                    pricing_raw["output_per_million_cny"]),
                context_window=int(pricing_raw["context_window"]),
                updated_at=str(pricing_raw["updated_at"]),
            )
        key_env = str(raw.get("api_key_env") or "")
        return Provider(
            name=name,
            adapter=str(raw.get("adapter") or ""),
            base_url=str(raw.get("base_url") or ""),
            model=str(raw.get("model") or ""),
            api_key_env=key_env,
            api_key=self.environment.get(key_env) if key_env else None,
            api_key_required=bool(raw.get("api_key_required", bool(key_env))),
            max_tokens=int(raw.get("max_tokens", 300)),
            request_options=dict(raw.get("request_options") or {}),
            pricing=pricing,
            max_estimated_request_cost_cny=(
                float(raw["max_estimated_request_cost_cny"])
                if raw.get("max_estimated_request_cost_cny") is not None else None),
            fallback_status_codes=tuple(
                int(value) for value in raw.get(
                    "fallback_status_codes", (401, 403, 404))),
            quota_exhausted_markers=tuple(
                str(value).lower()
                for value in raw.get("quota_exhausted_markers", ())),
        )


def _find_config(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise ConfigError(f"找不到配置文件：{path}")
        return path
    search_dirs = [Path.cwd()]
    if getattr(sys, 'frozen', False):
        search_dirs.append(Path(sys.executable).parent)
    search_dirs.append(Path(__file__).resolve().parent.parent)
    search_dirs.append(Path.home() / ".ai_screenshot_organizer")
    
    for directory in search_dirs:
        for candidate in ("config.yaml", "config.example.yaml"):
            path = directory / candidate
            if path.exists():
                return path
    raise ConfigError("找不到 config.yaml 或 config.example.yaml。")


def _validate(data: dict[str, Any]) -> None:
    for key in ("watch_dir", "output_dir", "providers"):
        if key not in data:
            raise ConfigError(f"配置缺少必填项：{key}")
    providers = data.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        raise ConfigError("providers 必须至少包含一个模型配置。")
    order = data.get("provider_order") or []
    if not order:
        raise ConfigError("provider_order 不能为空。")
    unknown = [name for name in order if name not in providers]
    if unknown:
        raise ConfigError(f"provider_order 包含未定义项：{', '.join(unknown)}")
    for name, raw in providers.items():
        raw = raw or {}
        adapter = raw.get("adapter")
        if adapter not in SUPPORTED_ADAPTERS:
            raise ConfigError(
                f"provider '{name}' adapter 无效：{adapter!r}")
        if adapter != "mock" and not raw.get("model"):
            raise ConfigError(f"provider '{name}' 缺少 model。")
        pricing = raw.get("pricing")
        if pricing:
            required = {
                "input_per_million_cny", "output_per_million_cny",
                "context_window", "updated_at",
            }
            missing = required - set(pricing)
            if missing:
                raise ConfigError(
                    f"provider '{name}' pricing 缺少：{', '.join(sorted(missing))}")


def load_config(path: str | None = None, *, load_environment: bool = True) -> Config:
    if load_environment:
        load_dotenv()
    config_path = _find_config(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    _validate(data)
    return Config(
        path=config_path,
        watch_dir=Path(data["watch_dir"]).expanduser(),
        output_dir=Path(data["output_dir"]).expanduser(),
        provider_order=[str(value) for value in data["provider_order"]],
        providers=dict(data["providers"]),
        max_image_px=int(data.get("max_image_px", _DEFAULTS["max_image_px"])),
        name_max_len=int(data.get("name_max_len", _DEFAULTS["name_max_len"])),
        workers=int(data.get("workers", _DEFAULTS["workers"])),
        categories=list(data.get("categories", _DEFAULTS["categories"])),
        environment=dict(os.environ),
    )
