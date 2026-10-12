import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from screenshot_organizer.organizer import process_file, undo


class ManifestTests(TestCase):
    def test_writes_list_price_fields_and_keeps_legacy_alias_out(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "shot.png"
            source.write_bytes(b"png")
            cfg = SimpleNamespace(output_dir=root / "out", name_max_len=30)
            provider = SimpleNamespace(name="glm", model="glm-4.6v")

            process_file(
                source,
                {"name": "测试", "category": "代码", "summary": "summary"},
                cfg,
                batch_id="batch-1",
                provider=provider,
                dry_run=False,
                usage={"total_tokens": 10},
                estimated_list_cost_cny=0.01,
                pricing_updated_at="2026-06-11",
            )

            record = json.loads(
                (cfg.output_dir / "manifest.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["estimated_list_cost_cny"], 0.01)
            self.assertEqual(record["pricing_updated_at"], "2026-06-11")
            self.assertNotIn("estimated_cost_cny", record)

    def test_undo_accepts_legacy_manifest_cost_field(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "out"
            output.mkdir()
            original = root / "watch" / "old.png"
            destination = output / "代码" / "moved.png"
            destination.parent.mkdir()
            destination.write_bytes(b"image")
            record = {
                "batch_id": "old-batch",
                "original": str(original),
                "dest": str(destination),
                "estimated_cost_cny": 0.1,
            }
            (output / "manifest.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8")
            cfg = SimpleNamespace(output_dir=output)

            with redirect_stdout(StringIO()):
                count = undo(cfg, last_only=True)

            self.assertEqual(count, 1)
            self.assertTrue(original.exists())
