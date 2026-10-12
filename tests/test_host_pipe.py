"""Unit tests for HostPipeAdapter."""
from __future__ import annotations

import json
import queue
import threading
import time
import unittest
from types import SimpleNamespace

from screenshot_organizer.adapters import (
    EncodedImage,
    HostPipeAdapter,
    PIPE_PREFIX,
    _PipeHub,
)


class QueueStdin:
    """用 Queue 模拟支持 readline() 的 stdin，支持 EOF。"""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._eof = False

    def isatty(self) -> bool:
        return False

    def write_line(self, line: str) -> None:
        self._queue.put(line)

    def close(self) -> None:
        self._eof = True
        self._queue.put("")

    def readline(self) -> str:
        if self._eof and self._queue.empty():
            return ""
        return self._queue.get()


class TtyStdin:
    """模拟终端标准输入（isatty() 返回 True）。"""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        # 若被误调用，不应死锁
        time.sleep(10.0)
        return ""


class QueueStdout:
    """用 Queue 模拟 stdout，便于测试端按序或实时读取协议输出。"""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def write(self, s: str) -> None:
        with self._lock:
            self._lines.append(s)
        self._queue.put(s)

    def flush(self) -> None:
        pass

    def get_line(self, timeout: float = 3.0) -> str:
        return self._queue.get(timeout=timeout)

    @property
    def all_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


class TestHostPipeAdapter(unittest.TestCase):
    def setUp(self) -> None:
        _PipeHub.reset_for_tests()
        self.provider = SimpleNamespace(
            name="quizforge",
            adapter="host_pipe",
            model="gemini-3.8-flash-high",
            max_tokens=300,
        )

    def tearDown(self) -> None:
        _PipeHub.reset_for_tests()

    def test_protocol_line_format_and_fields(self) -> None:
        """测试 stdout 中协议行以 \\n + 前缀开头，且 JSON 字段都正确。"""
        fake_stdin = QueueStdin()
        fake_stdout = QueueStdout()
        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=2.0
        )

        test_image = EncodedImage(media_type="image/png", base64_data="iVBORw0KGgo=")

        # 启动一个后台线程回复
        def reply_worker() -> None:
            raw_line = fake_stdout.get_line(timeout=2.0)
            # 断言写入内容以 "\n" + PIPE_PREFIX 开头
            self.assertTrue(raw_line.startswith(f"\n{PIPE_PREFIX}"))
            json_str = raw_line[len(f"\n{PIPE_PREFIX}") :].strip()
            data = json.loads(json_str)
            self.assertIn("id", data)
            self.assertEqual(data["system"], "sys prompt")
            self.assertEqual(data["user"], "user prompt")
            self.assertEqual(
                data["image"],
                {"mimeType": "image/png", "data": "iVBORw0KGgo="},
            )

            # 回复正常结果
            resp = {"id": data["id"], "ok": True, "content": "分类结果：代码"}
            fake_stdin.write_line(json.dumps(resp) + "\n")

        t = threading.Thread(target=reply_worker, daemon=True)
        t.start()

        res = adapter.generate("sys prompt", "user prompt", test_image)
        t.join(timeout=2.0)

        self.assertEqual(res.content, "分类结果：代码")
        self.assertEqual(res.finish_reason, "stop")
        self.assertEqual(res.usage["prompt_tokens"], 0)

    def test_concurrent_requests_reverse_order_reply(self) -> None:
        """测试两个线程并发调用 generate，假宿主按相反顺序回复，两个线程各自拿到正确的 content。"""
        fake_stdin = QueueStdin()
        fake_stdout = QueueStdout()
        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=3.0
        )

        img1 = EncodedImage(media_type="image/jpeg", base64_data="data1")
        img2 = EncodedImage(media_type="image/jpeg", base64_data="data2")

        results: dict[str, str] = {}
        exceptions: list[Exception] = []

        def worker(key: str, img: EncodedImage) -> None:
            try:
                resp = adapter.generate(f"sys_{key}", f"user_{key}", img)
                results[key] = resp.content
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=worker, args=("req1", img1))
        t2 = threading.Thread(target=worker, args=("req2", img2))
        t1.start()
        t2.start()

        # 从 stdout 读取两个请求
        line1 = fake_stdout.get_line(timeout=2.0)
        line2 = fake_stdout.get_line(timeout=2.0)

        data1 = json.loads(line1.strip()[len(PIPE_PREFIX) :])
        data2 = json.loads(line2.strip()[len(PIPE_PREFIX) :])

        # 按照相反顺序回复：先回复请求 2，再回复请求 1
        resp2 = {"id": data2["id"], "ok": True, "content": f"回复：{data2['user']}"}
        resp1 = {"id": data1["id"], "ok": True, "content": f"回复：{data1['user']}"}

        fake_stdin.write_line(json.dumps(resp2) + "\n")
        time.sleep(0.02)
        fake_stdin.write_line(json.dumps(resp1) + "\n")

        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

        self.assertEqual(len(exceptions), 0)
        self.assertEqual(results["req1"], "回复：user_req1")
        self.assertEqual(results["req2"], "回复：user_req2")

    def test_error_response_raises_runtime_error(self) -> None:
        """测试收到 ok: false 时抛出 RuntimeError。"""
        fake_stdin = QueueStdin()
        fake_stdout = QueueStdout()
        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=2.0
        )

        img = EncodedImage(media_type="image/png", base64_data="data")

        def reply_error() -> None:
            raw_line = fake_stdout.get_line(timeout=2.0)
            data = json.loads(raw_line.strip()[len(PIPE_PREFIX) :])
            err_resp = {"id": data["id"], "ok": False, "error": "Antigravity 配额耗尽"}
            fake_stdin.write_line(json.dumps(err_resp) + "\n")

        t = threading.Thread(target=reply_error, daemon=True)
        t.start()

        with self.assertRaises(RuntimeError) as ctx:
            adapter.generate("sys", "user", img)

        self.assertIn("Antigravity 配额耗尽", str(ctx.exception))
        t.join(timeout=2.0)

    def test_stdin_eof_fails_immediately_without_hang(self) -> None:
        """测试 stdin 读到 EOF 时立即报错，不会卡住。"""
        fake_stdin = QueueStdin()
        fake_stdout = QueueStdout()

        fake_stdin.close()
        time.sleep(0.05)

        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=2.0
        )

        img = EncodedImage(media_type="image/png", base64_data="data")

        start_time = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            adapter.generate("sys", "user", img)
        elapsed = time.monotonic() - start_time

        self.assertLess(elapsed, 0.5)
        self.assertIn("host_pipe 只能在 QuizForge 中使用", str(ctx.exception))

    def test_tty_stdin_fails_immediately_without_hang(self) -> None:
        """测试用一个 isatty() 返回 True 的假 stdin 构造 hub，generate 立即抛错。"""
        fake_stdin = TtyStdin()
        fake_stdout = QueueStdout()
        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=2.0
        )

        img = EncodedImage(media_type="image/png", base64_data="data")

        start_time = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            adapter.generate("sys", "user", img)
        elapsed = time.monotonic() - start_time

        self.assertLess(elapsed, 0.5)
        self.assertIn("host_pipe 只能在 QuizForge 中使用", str(ctx.exception))

    def test_protocol_prefix_on_new_line_after_partial_log(self) -> None:
        """模拟另一个线程先向 stdout 写入不带换行的半行日志，断言协议前缀仍出现在新的一行行首。"""
        fake_stdin = QueueStdin()
        fake_stdout = QueueStdout()

        # 模拟主线程打印未换行的文本
        fake_stdout.write("[预览] 正在处理 1.png -> 代码/x.png")

        adapter = HostPipeAdapter(
            self.provider, stdin=fake_stdin, stdout=fake_stdout, timeout=2.0
        )
        test_image = EncodedImage(media_type="image/png", base64_data="data")

        def reply_worker() -> None:
            part1 = fake_stdout.get_line(timeout=2.0)
            part2 = fake_stdout.get_line(timeout=2.0)

            combined = part1 + part2
            lines = combined.split("\n")

            # 第一行是未换行的日志
            self.assertEqual(lines[0], "[预览] 正在处理 1.png -> 代码/x.png")
            # 协议前缀必须出现在新行行首
            proto_lines = [l for l in lines if l.startswith(PIPE_PREFIX)]
            self.assertEqual(len(proto_lines), 1)

            data = json.loads(proto_lines[0][len(PIPE_PREFIX) :])
            resp = {"id": data["id"], "ok": True, "content": "分类OK"}
            fake_stdin.write_line(json.dumps(resp) + "\n")

        t = threading.Thread(target=reply_worker, daemon=True)
        t.start()

        res = adapter.generate("sys", "user", test_image)
        t.join(timeout=2.0)
        self.assertEqual(res.content, "分类OK")


if __name__ == "__main__":
    unittest.main()
