# Security Policy

## API Keys

API key 只能放在本机 `.env` 或 CI Secrets 中。不要写入 YAML、源码、日志、
issue、截图或提交历史。

如果密钥曾被提交或公开：

1. 立即在供应商控制台吊销并重新生成。
2. 清理 Git 历史，而不只是删除当前文件。
3. 检查供应商账单和调用记录。

## Reporting

请通过 GitHub Security Advisory 私下报告安全问题，不要先创建公开 issue。

## Data Privacy

除 `mock` 和本地 Ollama 外，截图会发送到所选云模型服务。使用者应自行确认
截图内容、所在地区和组织政策允许上传。
