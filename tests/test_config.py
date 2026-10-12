import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

from screenshot_organizer.config import ConfigError, load_config


class ConfigTests(TestCase):
    def test_public_example_contains_nine_vision_presets_and_defaults_to_mock(self):
        data = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))

        self.assertEqual(data["provider_order"], ["mock"])
        self.assertEqual(set(data["providers"]), {
            "mock", "openai", "claude", "gemini", "glm",
            "mimo", "kimi", "qwen", "doubao", "ollama",
        })
        self.assertEqual(data["providers"]["claude"]["adapter"], "anthropic_messages")
        self.assertEqual(data["providers"]["openai"]["adapter"], "openai_compatible")

    def test_loads_new_provider_schema_and_nested_pricing(self):
        data = {
            "watch_dir": ".",
            "output_dir": "./organized",
            "provider_order": ["custom"],
            "providers": {
                "custom": {
                    "adapter": "openai_compatible",
                    "base_url": "https://example.test/v1",
                    "model": "vision",
                    "api_key_env": "CUSTOM_KEY",
                    "request_options": {"temperature": 0},
                    "pricing": {
                        "input_per_million_cny": 1,
                        "output_per_million_cny": 2,
                        "context_window": 1000,
                        "updated_at": "2026-06-11",
                    },
                    "max_estimated_request_cost_cny": 5,
                }
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.yaml"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
            with patch.dict(os.environ, {"CUSTOM_KEY": "secret"}):
                cfg = load_config(str(path), load_environment=False)

        provider = cfg.provider("custom")
        self.assertEqual(provider.adapter, "openai_compatible")
        self.assertEqual(provider.request_options, {"temperature": 0})
        self.assertEqual(provider.pricing.updated_at, "2026-06-11")
        self.assertEqual(provider.api_key, "secret")

    def test_validate_rejects_unknown_adapter(self):
        data = {
            "watch_dir": ".",
            "output_dir": "./organized",
            "provider_order": ["bad"],
            "providers": {
                "bad": {
                    "adapter": "unknown",
                    "model": "x",
                    "api_key_required": False,
                }
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.yaml"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(str(path), load_environment=False)
