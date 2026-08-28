# Melodio Demo 上线部署说明

这套 demo 是一个 FastAPI 服务，前端静态页面和后端接口在同一个进程里。上线时只需要部署 `melodio_demo_clone` 目录，模型 Key 放在云平台环境变量里，不要提交 `.env`。

## 推荐部署方式

优先用支持 Docker 的云平台或公司内网服务器部署一个容器：

1. 构建镜像：读取 `Dockerfile`。
2. 启动服务：容器内监听 `PORT`，默认 `8010`。
3. 配置 HTTPS 域名：平台或 Nginx 反代到容器端口。
4. 在平台后台填写环境变量。

FastAPI 官方也推荐用容器镜像部署，便于把代码、依赖和启动命令一起打包。

## 必填环境变量

至少配置 Gemini 或 DeepSeek 其中一个。建议两个都配，页面模型下拉就能同时测试。

```text
GEMINI_API_KEY=你的 Gemini API Key
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODEL=gemini-3.5-flash

DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

DEFAULT_PROVIDER=deepseek
```

DeepSeek 官方当前模型名是 `deepseek-v4-flash` / `deepseek-v4-pro`；旧的 `deepseek-chat` 和 `deepseek-reasoner` 会在 2026-07-24 15:59 UTC 停用兼容名。Gemini 官方 OpenAI 兼容示例使用 `gemini-3.5-flash` 和 `https://generativelanguage.googleapis.com/v1beta/openai/`。

## 建议环境变量

给同事和领导测试时建议加一个简单账号密码，避免公开链接被外部访问导致 API 费用失控：

```text
DEMO_BASIC_AUTH_USER=demo
DEMO_BASIC_AUTH_PASSWORD=换成一个强密码
```

如果前端和后端分开部署，再把跨域限制收紧到你的正式域名：

```text
CORS_ALLOW_ORIGINS=https://你的域名
```

当前 demo 是前后端同域部署，通常保持默认即可。

## 本地容器验证

```bash
cd melodio_demo_clone
docker build -t melodio-demo .
docker run --env-file .env -p 8010:8010 melodio-demo
```

打开：

```text
http://127.0.0.1:8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/healthz
```

正常会返回 `ok: true`，并显示已配置的线上模型。

## 上线后的检查清单

1. 访问 `/healthz`，确认服务在线、模型已配置。
2. 打开首页，确认模型下拉里 Gemini / DeepSeek 不是“未配置”。
3. 用 `适合深夜一个人开车的伤感华语歌` 测推荐。
4. 用 `许嵩什么时候生日` 测音乐百科不出歌。
5. 用 `换一首` 测播放器控制意图。
6. 看平台日志，确认没有 401、模型 Key 错误、额度不足或超时。

## 官方参考

- Gemini OpenAI 兼容接口：https://ai.google.dev/gemini-api/docs/openai
- DeepSeek 模型和价格：https://api-docs.deepseek.com/quick_start/pricing
- DeepSeek Chat Completion API：https://api-docs.deepseek.com/api/create-chat-completion
- FastAPI Docker 部署：https://fastapi.tiangolo.com/deployment/docker/
