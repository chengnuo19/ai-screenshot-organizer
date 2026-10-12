"""Vision model adapter interfaces."""
from __future__ import annotations

import json
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Protocol

PIPE_PREFIX = "@@QUIZFORGE-AI@@ "


@dataclass(frozen=True)
class EncodedImage:
    media_type: str
    base64_data: str

    @property
    def data_uri(self) -> str:
        return f"data:{self.media_type};base64,{self.base64_data}"


@dataclass(frozen=True)
class ModelResponse:
    content: str
    usage: dict[str, int]
    finish_reason: str | None


class VisionProvider(Protocol):
    def generate(
        self, system_prompt: str, user_prompt: str, image: EncodedImage
    ) -> ModelResponse:
        ...


class OpenAICompatibleAdapter:
    def __init__(self, provider, *, client=None):
        self.provider = provider
        if client is None:
            from openai import OpenAI
            client = OpenAI(
                base_url=provider.base_url or None,
                api_key=provider.api_key or "local-no-key",
                timeout=60.0,
                max_retries=2,
            )
        self.client = client

    def generate(
        self, system_prompt: str, user_prompt: str, image: EncodedImage
    ) -> ModelResponse:
        request = {
            "model": self.provider.model,
            "max_tokens": self.provider.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url",
                     "image_url": {"url": image.data_uri}},
                ]},
            ],
        }
        request.update(self.provider.request_options)
        response = self.client.chat.completions.create(**request)
        usage = response.usage
        return ModelResponse(
            content=response.choices[0].message.content or "",
            usage={
                "prompt_tokens": int(usage.prompt_tokens or 0) if usage else 0,
                "completion_tokens": int(usage.completion_tokens or 0) if usage else 0,
                "total_tokens": int(usage.total_tokens or 0) if usage else 0,
            },
            finish_reason=getattr(response.choices[0], "finish_reason", None),
        )


class AnthropicMessagesAdapter:
    def __init__(self, provider, *, client=None):
        self.provider = provider
        if client is None:
            from anthropic import Anthropic
            client = Anthropic(
                api_key=provider.api_key,
                base_url=provider.base_url or None,
                timeout=60.0,
                max_retries=2,
            )
        self.client = client

    def generate(
        self, system_prompt: str, user_prompt: str, image: EncodedImage
    ) -> ModelResponse:
        request = {
            "model": self.provider.model,
            "max_tokens": self.provider.max_tokens,
            "system": system_prompt,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.base64_data,
                    }},
                ],
            }],
        }
        request.update(self.provider.request_options)
        response = self.client.messages.create(**request)
        content = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text")
        prompt_tokens = int(response.usage.input_tokens or 0)
        completion_tokens = int(response.usage.output_tokens or 0)
        return ModelResponse(
            content=content,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            finish_reason=getattr(response, "stop_reason", None),
        )


class _PendingRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: Optional[dict[str, Any]] = None
        self.exception: Optional[Exception] = None


class _PipeHub:
    """管道通信管理单例，在同一进程内负责线程安全的 stdout 写入与唯一的 stdin 监听线程。"""
    _instance: Optional["_PipeHub"] = None
    _instance_lock = threading.Lock()

    def __init__(self, stdin=None, stdout=None) -> None:
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.write_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending: dict[str, _PendingRequest] = {}

        # 检查 stdin 是否是交互式终端；若是终端则直接进入 eof 状态，避免卡在 readline
        is_tty = False
        if hasattr(self.stdin, "isatty"):
            try:
                is_tty = bool(self.stdin.isatty())
            except Exception:
                is_tty = False

        if is_tty:
            self.eof = True
            self.reader_thread = None
        else:
            self.eof = False
            self.reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="HostPipeReader"
            )
            self.reader_thread.start()

    @classmethod
    def get_default_hub(cls) -> "_PipeHub":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _reader_loop(self) -> None:
        while True:
            try:
                line = self.stdin.readline()
            except Exception:
                line = ""

            if not line:  # 读到 EOF
                with self.pending_lock:
                    self.eof = True
                    eof_err = RuntimeError("host_pipe 只能在 QuizForge 中使用")
                    for req in list(self.pending.values()):
                        req.exception = eof_err
                        req.event.set()
                break

            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except Exception:
                continue

            req_id = data.get("id")
            if not req_id:
                continue

            with self.pending_lock:
                req = self.pending.get(req_id)
                if req:
                    req.response = data
                    req.event.set()

    def send_and_wait(self, payload: dict[str, Any], timeout: float) -> str:
        req_id = payload["id"]
        req = _PendingRequest()

        with self.pending_lock:
            if self.eof:
                raise RuntimeError("host_pipe 只能在 QuizForge 中使用")
            self.pending[req_id] = req

        protocol_line = f"\n{PIPE_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"
        with self.write_lock:
            self.stdout.write(protocol_line)
            self.stdout.flush()

        signaled = req.event.wait(timeout=timeout)
        with self.pending_lock:
            self.pending.pop(req_id, None)

        if not signaled:
            raise TimeoutError("等待 QuizForge AI 响应超时")

        if req.exception is not None:
            raise req.exception

        resp = req.response or {}
        if not resp.get("ok"):
            err_msg = resp.get("error") or "未知错误"
            raise RuntimeError(err_msg)

        return str(resp.get("content", ""))


class HostPipeAdapter:
    """通过管道（标准输入输出）与 QuizForge 宿主通信的 Vision 模型适配器。"""

    def __init__(
        self,
        provider,
        *,
        stdin=None,
        stdout=None,
        timeout: float = 360.0,
        hub: Optional[_PipeHub] = None,
    ) -> None:
        self.provider = provider
        self.timeout = timeout
        if hub is not None:
            self.hub = hub
        elif stdin is not None or stdout is not None:
            self.hub = _PipeHub(stdin=stdin, stdout=stdout)
        else:
            self.hub = _PipeHub.get_default_hub()

    def generate(
        self, system_prompt: str, user_prompt: str, image: EncodedImage
    ) -> ModelResponse:
        req_id = str(uuid.uuid4())
        payload = {
            "id": req_id,
            "system": system_prompt,
            "user": user_prompt,
            "image": {
                "mimeType": image.media_type,
                "data": image.base64_data,
            },
        }
        content = self.hub.send_and_wait(payload, timeout=self.timeout)
        return ModelResponse(
            content=content,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
        )


def build_adapter(provider) -> VisionProvider:
    if provider.adapter == "openai_compatible":
        return OpenAICompatibleAdapter(provider)
    if provider.adapter == "anthropic_messages":
        return AnthropicMessagesAdapter(provider)
    if provider.adapter == "host_pipe":
        return HostPipeAdapter(provider)
    raise ValueError(f"不支持的 adapter：{provider.adapter}")
