# Contributing

感谢你为 ai-screenshot-organizer 做贡献。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
```

## Provider 贡献要求

- 只接受官方支持图片输入的模型服务。
- 优先复用 `openai_compatible` 或 `anthropic_messages` 适配器。
- 模型差异应通过配置中的 `request_options` 和错误标识表达。
- 不得提交真实 API key、个人路径或供应商账单。
- 新 provider 必须包含配置加载和请求结构测试。

## Pull Request

- 保持改动聚焦。
- 更新 README 中的模型表。
- 确保测试、静态检查和密钥扫描通过。
