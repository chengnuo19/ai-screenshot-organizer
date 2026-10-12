from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from screenshot_organizer.config import Pricing
from screenshot_organizer.llm import (
    BudgetExceededError,
    LabelCall,
    Labeler,
    ProviderRouter,
)


def provider(name, **overrides):
    values = {
        "name": name,
        "model": name,
        "api_key": "test",
        "api_key_required": True,
        "fallback_status_codes": (401, 403, 404),
        "quota_exhausted_markers": (),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ApiError(Exception):
    def __init__(self, status_code, message=""):
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code
        self.body = {"message": message}


class RouterTests(TestCase):
    def test_skips_provider_with_missing_required_key(self):
        providers = [
            provider("openai", api_key=None),
            provider("ollama", api_key=None, api_key_required=False),
        ]
        ollama = Mock()
        expected = LabelCall({"name": "ok"}, providers[1], {}, 0.0, None)
        ollama.label_call.return_value = expected

        with patch("screenshot_organizer.llm.Labeler", side_effect=[ollama]):
            result = ProviderRouter(SimpleNamespace(), providers).label(Path("x.png"))

        self.assertIs(result, expected)

    def test_falls_back_only_for_declared_daily_quota_marker(self):
        providers = [
            provider("gemini", quota_exhausted_markers=("perday",)),
            provider("glm"),
        ]
        gemini = Mock()
        gemini.label_call.side_effect = ApiError(429, "GenerateRequestsPerDay")
        glm = Mock()
        expected = LabelCall({"name": "ok"}, providers[1], {}, 0.0, None)
        glm.label_call.return_value = expected

        with patch("screenshot_organizer.llm.Labeler", side_effect=[gemini, glm]):
            with self.assertLogs("organizer", level="WARNING"):
                result = ProviderRouter(
                    SimpleNamespace(), providers).label(Path("x.png"))

        self.assertIs(result, expected)

    def test_minute_rate_limit_does_not_switch_to_paid_provider(self):
        providers = [
            provider("gemini", quota_exhausted_markers=("perday",)),
            provider("glm"),
        ]
        gemini = Mock()
        gemini.label_call.side_effect = ApiError(429, "RequestsPerMinute")
        glm = Mock()

        with patch("screenshot_organizer.llm.Labeler", side_effect=[gemini, glm]):
            with self.assertRaises(ApiError):
                ProviderRouter(SimpleNamespace(), providers).label(Path("x.png"))

        glm.label_call.assert_not_called()

    def test_bad_request_does_not_fallback(self):
        providers = [provider("first"), provider("second")]
        first = Mock()
        first.label_call.side_effect = ApiError(400)
        second = Mock()

        with patch("screenshot_organizer.llm.Labeler", side_effect=[first, second]):
            with self.assertRaises(ApiError):
                ProviderRouter(SimpleNamespace(), providers).label(Path("x.png"))

        second.label_call.assert_not_called()

    def test_rejects_provider_when_list_price_maximum_exceeds_cap(self):
        expensive = provider(
            "expensive",
            pricing=Pricing(
                input_per_million_cny=10,
                output_per_million_cny=10,
                context_window=1_000_000,
                updated_at="2026-06-11",
            ),
            max_tokens=500_000,
            max_estimated_request_cost_cny=5,
        )

        with self.assertRaises(BudgetExceededError):
            Labeler(SimpleNamespace(), expensive)
