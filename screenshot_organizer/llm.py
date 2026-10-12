"""Vision labeling and provider routing."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .adapters import EncodedImage, build_adapter

log = logging.getLogger("organizer")

_SYSTEM = "你是截图整理助手。只输出一个 JSON 对象，不要任何多余文字或代码块标记。"
_FALLBACK = {"name": "截图", "category": "其他", "summary": ""}


class ProviderUnavailableError(RuntimeError):
    pass


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class LabelCall:
    label: dict
    provider: object
    usage: dict
    estimated_list_cost_cny: float
    pricing_updated_at: str | None


def _user_prompt(categories: list, name_max_len: int) -> str:
    cats = "、".join(categories)
    return (
        '请阅读这张截图，输出 JSON：{"name": ..., "category": ..., "summary": ...}。\n'
        f"- name：用不超过 {name_max_len} 个汉字概括截图主题，便于做文件名；"
        "不要包含标点、换行、表情或文件后缀。\n"
        f"- category：优先从以下分类中选一个：{cats}；"
        "都不合适时给一个简洁的新分类（2-6 字）。\n"
        "- summary：一句话描述截图内容。\n"
        "只返回 JSON。"
    )


def encode_image(path: Path, max_px: int) -> EncodedImage:
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        scale = min(1.0, max_px / max(width, height))
        if scale < 1.0:
            image = image.resize((
                max(1, int(width * scale)),
                max(1, int(height * scale)),
            ))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
    return EncodedImage(
        media_type="image/jpeg",
        base64_data=base64.b64encode(buffer.getvalue()).decode(),
    )


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = text.rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


class Labeler:
    def __init__(self, config, provider, *, adapter=None):
        self.cfg = config
        self.provider = provider
        self._validate_budget()
        self.adapter = adapter

    def _validate_budget(self) -> None:
        provider = self.provider
        if not provider.pricing or provider.max_estimated_request_cost_cny is None:
            return
        pricing = provider.pricing
        maximum = (
            pricing.context_window * pricing.input_per_million_cny
            + provider.max_tokens * pricing.output_per_million_cny
        ) / 1_000_000
        if maximum > provider.max_estimated_request_cost_cny:
            raise BudgetExceededError(
                f"provider '{provider.name}' 单次公开单价估算最高约 "
                f"{maximum:.4f} 元，超过 "
                f"{provider.max_estimated_request_cost_cny:.2f} 元限制。")

    def label(self, path: Path) -> dict:
        return self.label_call(path).label

    def label_call(self, path: Path) -> LabelCall:
        if self.provider.adapter == "mock":
            return LabelCall(
                self._mock(path), self.provider, {}, 0.0, None)
        if self.provider.api_key_required and not self.provider.api_key:
            raise ProviderUnavailableError(
                f"provider '{self.provider.name}' 缺少 "
                f"{self.provider.api_key_env}。")
        if self.adapter is None:
            self.adapter = build_adapter(self.provider)
        response = self.adapter.generate(
            _SYSTEM,
            _user_prompt(self.cfg.categories, self.cfg.name_max_len),
            encode_image(path, self.cfg.max_image_px),
        )
        parsed = _parse_json(response.content)
        if not parsed or not str(parsed.get("name", "")).strip():
            log.warning("解析失败，回退默认：%s -> %r",
                        path.name, response.content[:120])
            label = dict(_FALLBACK)
        else:
            label = {
                "name": str(parsed.get("name", "")).strip(),
                "category": str(parsed.get("category") or "其他").strip(),
                "summary": str(parsed.get("summary") or "").strip(),
            }
        cost, updated_at = self._list_cost(response.usage)
        return LabelCall(
            label, self.provider, response.usage, cost, updated_at)

    def _list_cost(self, usage: dict) -> tuple[float, str | None]:
        pricing = self.provider.pricing
        if not pricing or not usage:
            return 0.0, None
        cost = (
            usage.get("prompt_tokens", 0) * pricing.input_per_million_cny
            + usage.get("completion_tokens", 0) * pricing.output_per_million_cny
        ) / 1_000_000
        return cost, pricing.updated_at

    def _mock(self, path: Path) -> dict:
        digest = int(hashlib.md5(
            str(path).encode("utf-8")).hexdigest(), 16)
        category = self.cfg.categories[digest % len(self.cfg.categories)]
        digits = re.findall(r"\d{6}", path.stem)
        tail = digits[-1] if digits else f"{digest % 10000:04d}"
        return {
            "name": f"样例截图{tail}",
            "category": category,
            "summary": "mock 占位结果",
        }


def _provider_unavailable(provider, exc: Exception) -> bool:
    if isinstance(exc, ProviderUnavailableError):
        return True
    status = getattr(exc, "status_code", None)
    if status in provider.fallback_status_codes:
        return True
    if status != 429:
        return False
    details = f"{exc} {getattr(exc, 'body', '')}".lower()
    return any(marker in details for marker in provider.quota_exhausted_markers)


class ProviderRouter:
    def __init__(self, config, providers):
        available = [
            provider for provider in providers
            if not provider.api_key_required or provider.api_key
        ]
        if not available:
            raise ProviderUnavailableError("没有可用 provider：请配置 API key。")
        self.providers = available
        self._labelers = [Labeler(config, provider) for provider in available]
        self._active = 0
        self._lock = threading.Lock()

    @property
    def active_provider(self):
        with self._lock:
            return self.providers[self._active]

    def label(self, path: Path) -> LabelCall:
        while True:
            with self._lock:
                index = self._active
            provider = self.providers[index]
            try:
                return self._labelers[index].label_call(path)
            except Exception as exc:
                if not _provider_unavailable(provider, exc):
                    raise
                with self._lock:
                    if index == self._active and self._active < len(self.providers) - 1:
                        self._active += 1
                        next_provider = self.providers[self._active]
                        log.warning(
                            "provider %s 不可用，切换到 %s：%s",
                            provider.name, next_provider.name, exc)
                        continue
                    if index < self._active:
                        continue
                raise
