# AI Screenshot Organizer

[中文](README.md)

Understand screenshots with vision AI, generate useful filenames, and organize
them into category folders.

## Highlights

- Offline, free `mock` provider by default.
- Presets for OpenAI, Claude, Gemini, GLM, MiMo, Kimi, Qwen, Doubao, and Ollama.
- Ordered provider routing with missing-key skipping.
- Fallback only for explicit daily quota or balance exhaustion. Minute rate
  limits do not silently trigger a paid provider.
- Dry runs, collision-safe moves, manifests, and undo.
- Token usage and public list-price estimates.

> List-price estimates are not cash charges. They do not account for resource
> packs, free grants, cache discounts, or promotions.

## Install

Python 3.10+ is required.

```powershell
python -m pip install -e .
screenshot-organizer config init
Copy-Item .env.example .env
```

Edit `config.yaml`, then set the API keys you use in `.env`.

## Commands

```powershell
screenshot-organizer config validate
screenshot-organizer providers list
screenshot-organizer providers test --provider gemini
screenshot-organizer batch --dry-run --limit 5
screenshot-organizer batch
screenshot-organizer watch
screenshot-organizer undo --last
```

The public config starts with `provider_order: [mock]`, so a first run makes no
network request and incurs no cost.

## Custom OpenAI-compatible Provider

```yaml
providers:
  custom:
    adapter: openai_compatible
    base_url: "https://example.com/v1"
    model: "vision-model"
    api_key_env: CUSTOM_API_KEY
    max_tokens: 300
    request_options:
      temperature: 0.2
```

Model names are editable presets. DeepSeek is not included because its official
public API is not configured here as a screenshot image-input provider.

Cloud providers receive screenshot contents. Use `mock` or local Ollama for
sensitive images. Never commit `.env` or `config.yaml`.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
python scripts/scan_secrets.py
python -m build
```

## License

MIT
