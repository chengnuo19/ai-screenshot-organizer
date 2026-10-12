# AI Screenshot Organizer

[English](README_EN.md)

用视觉大模型理解截图内容，自动生成文件名并按类别整理到文件夹。支持批处理、
实时监听和 manifest 回滚。

## 特性

- 默认 `mock`，首次运行不联网、不收费。
- 支持 OpenAI、Claude、Gemini、GLM、MiMo、Kimi、Qwen、豆包和 Ollama。
- provider 按配置顺序使用，缺少密钥自动跳过。
- 只有明确的每日额度或余额耗尽才切换模型；每分钟限流不会触发付费后备。
- `--dry-run` 预览、冲突文件不覆盖、manifest 可回滚。
- 记录 token 和公开单价估算。

> 公开单价估算不代表现金实扣，也不考虑资源包、赠送额度、缓存折扣或活动价格。
> 实际费用以供应商账单为准。

## 安装

需要 Python 3.10 或更高版本。

```powershell
python -m pip install -e .
screenshot-organizer config init
Copy-Item .env.example .env
```

编辑 `config.yaml` 的截图目录、输出目录和 `provider_order`，并在 `.env` 中填写
所需密钥。公开模板默认：

```yaml
provider_order: [mock]
```

## 快速使用

```powershell
# 检查配置与模型
screenshot-organizer config validate
screenshot-organizer providers list
screenshot-organizer providers test --provider gemini

# 预览，不移动文件
screenshot-organizer batch --dry-run --limit 5

# 正式整理
screenshot-organizer batch

# 监听新增截图
screenshot-organizer watch

# 回滚最近一批
screenshot-organizer undo --last
```

运行源码时也可以使用：

```powershell
python -m screenshot_organizer batch --dry-run
```

## 模型预设

| Provider | 默认模型 | 适配器 | 密钥变量 |
|---|---|---|---|
| OpenAI | `gpt-4.1-mini` | OpenAI-compatible | `OPENAI_API_KEY` |
| Claude | `claude-sonnet-4-6` | Anthropic Messages | `ANTHROPIC_API_KEY` |
| Gemini | `gemini-2.5-flash` | OpenAI-compatible | `GEMINI_API_KEY` |
| GLM | `glm-4.6v` | OpenAI-compatible | `ZHIPU_API_KEY` |
| MiMo | `mimo-v2.5` | OpenAI-compatible | `MIMO_API_KEY` |
| Kimi | `kimi-k2.6` | OpenAI-compatible | `MOONSHOT_API_KEY` |
| Qwen | `qwen3-vl-flash` | OpenAI-compatible | `DASHSCOPE_API_KEY` |
| 豆包 | `YOUR_ENDPOINT_ID` | OpenAI-compatible | `ARK_API_KEY` |
| Ollama | `llama3.2-vision` | OpenAI-compatible | 无 |

模型名只是可覆盖的预设。供应商调整模型后，只需修改 YAML，不需要改源码。
DeepSeek 官方开放平台当前未作为图片输入 provider 集成。

## 自定义 Provider

大多数兼容服务只需要增加：

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

可选的 `pricing` 和 `max_estimated_request_cost_cny` 用于调用前的保守预算检查。
价格变化时应同步更新 `updated_at`。

## 输出和隐私

输出文件形如：

```text
OrganizedScreenshots/
├─ 代码/2026-06-11_120000_Python报错信息.png
├─ 文档/2026-06-11_120100_项目需求说明.png
└─ manifest.jsonl
```

云 provider 会收到截图内容。敏感截图请使用 `mock` 或本地 Ollama。API key 只能
放在被忽略的 `.env` 中，不要提交到 Git。

## 开发

```powershell
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
python scripts/scan_secrets.py
python -m build
```

官方能力参考：
[OpenAI](https://developers.openai.com/api/docs/models/gpt-4.1-mini) ·
[Claude](https://platform.claude.com/docs/en/about-claude/models/overview) ·
[Kimi](https://platform.moonshot.cn/docs/guide/use-kimi-vision-model) ·
[Qwen-VL](https://help.aliyun.com/zh/model-studio/vision) ·
[豆包](https://www.volcengine.com/docs/82379/1362931) ·
[Ollama](https://docs.ollama.com/api/openai-compatibility)

## License

MIT
