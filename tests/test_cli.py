import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase

import yaml
from PIL import Image

from screenshot_organizer.cli import main


class CliTests(TestCase):
    def test_config_init_creates_private_config_without_overwriting(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "config.yaml"
            out = StringIO()
            with redirect_stdout(out):
                main(["config", "init", "--output", str(target)])

            self.assertTrue(target.exists())
            with self.assertRaises(SystemExit):
                main(["config", "init", "--output", str(target)])

    def test_config_validate_reports_valid_example(self):
        out = StringIO()
        with redirect_stdout(out):
            main(["config", "validate", "--config", "config.example.yaml"])

        self.assertIn("配置有效", out.getvalue())

    def test_providers_list_shows_all_presets(self):
        out = StringIO()
        with redirect_stdout(out):
            main(["providers", "list", "--config", "config.example.yaml"])

        text = out.getvalue()
        self.assertIn("openai", text)
        self.assertIn("claude", text)
        self.assertIn("ollama", text)

    def test_providers_test_mock_does_not_need_network(self):
        out = StringIO()
        with redirect_stdout(out):
            main([
                "providers", "test",
                "--config", "config.example.yaml",
                "--provider", "mock",
            ])

        self.assertIn("mock: 成功", out.getvalue())

    def test_batch_dry_run_with_mock_does_not_move_image(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch = root / "watch"
            output = root / "output"
            watch.mkdir()
            image = watch / "shot.png"
            Image.new("RGB", (20, 20), "white").save(image)
            config = {
                "watch_dir": str(watch),
                "output_dir": str(output),
                "provider_order": ["mock"],
                "providers": {
                    "mock": {
                        "adapter": "mock",
                        "model": "mock",
                        "api_key_required": False,
                    }
                },
            }
            config_path = root / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(config), encoding="utf-8")
            out = StringIO()

            with redirect_stdout(out), redirect_stderr(StringIO()):
                main([
                    "batch", "--config", str(config_path),
                    "--dry-run", "--limit", "1",
                ])

            self.assertTrue(image.exists())
            self.assertFalse(output.exists())
            self.assertIn("成功 1，失败 0", out.getvalue())
