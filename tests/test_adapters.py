import base64
from types import SimpleNamespace
from unittest import TestCase

from screenshot_organizer.adapters import (
    AnthropicMessagesAdapter,
    EncodedImage,
    OpenAICompatibleAdapter,
)


class FakeCreate:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class AdapterTests(TestCase):
    def setUp(self):
        self.image = EncodedImage(
            media_type="image/jpeg",
            base64_data=base64.b64encode(b"image").decode(),
        )

    def test_openai_compatible_builds_image_request_and_maps_usage(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"name":"测试"}'),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=12, completion_tokens=7, total_tokens=19),
        )
        create = FakeCreate(response)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create.create)))
        provider = SimpleNamespace(
            model="vision-model",
            max_tokens=300,
            request_options={"temperature": 0.1, "extra_body": {"thinking": False}},
        )

        result = OpenAICompatibleAdapter(provider, client=client).generate(
            "system", "user", self.image)

        self.assertEqual(result.content, '{"name":"测试"}')
        self.assertEqual(result.usage["total_tokens"], 19)
        self.assertEqual(
            create.kwargs["messages"][1]["content"][1]["image_url"]["url"],
            self.image.data_uri,
        )
        self.assertEqual(create.kwargs["extra_body"], {"thinking": False})

    def test_anthropic_builds_native_image_request_and_maps_usage(self):
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"name":"Claude"}')],
            usage=SimpleNamespace(input_tokens=11, output_tokens=5),
            stop_reason="end_turn",
        )
        create = FakeCreate(response)
        client = SimpleNamespace(
            messages=SimpleNamespace(create=create.create))
        provider = SimpleNamespace(
            model="claude-sonnet-4-6",
            max_tokens=300,
            request_options={"temperature": 0.1},
        )

        result = AnthropicMessagesAdapter(provider, client=client).generate(
            "system", "user", self.image)

        image_block = create.kwargs["messages"][0]["content"][1]
        self.assertEqual(image_block["source"]["data"], self.image.base64_data)
        self.assertEqual(result.usage, {
            "prompt_tokens": 11,
            "completion_tokens": 5,
            "total_tokens": 16,
        })
