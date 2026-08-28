# Melodio Demo Clone

这是对 `melodio_demo.zip` 的复刻版：保留自然语言找歌、两级意图识别、分组推荐、结果卡片和反馈入口。默认可本地兜底运行，也可以连接真实 Gemini 和 DeepSeek。

## 运行

```bash
cd melodio_demo_clone
pip install -r requirements.txt
python3 -m uvicorn app:app --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010
```

## 复刻范围

- `/providers`：返回本地演示模型选项
- `/recommend`：兼容源 demo 的请求和返回结构
- `static/index.html`：单页 Web UI
- 真实线上模型：
  - Gemini Flash
  - DeepSeek V4 Flash / Pro
  - 豆包 Doubao（火山方舟 OpenAI 兼容接口）
- 本地规则模拟：
  - 音乐实体精搜
  - 场景/情绪/风格推荐
  - 相似推荐
  - 音乐百科
  - 操作指令/创作编辑/闲聊分类

## 配置真实模型

```bash
cp .env.example .env
```

填写：

```text
GEMINI_API_KEY=你的 Gemini key
DEEPSEEK_API_KEY=你的 DeepSeek key
DOUBAO_API_KEY=你的豆包/火山方舟 key
DOUBAO_MODEL=你的推理接入点，例如 ep-xxxx
DEFAULT_PROVIDER=deepseek
```

重启服务后，页面模型下拉里选择 `Gemini Flash`、`DeepSeek Chat` 或 `豆包 Doubao` 即可验证线上效果。没有配置 key 的模型会显示“未配置”，请求时会返回明确错误。

线上模型采用两段式返回：

1. 先返回意图识别骨架，页面立即显示 domain / intent / reference / traits。
2. 后台等待 Gemini 或 DeepSeek 生成真实推荐歌单，完成后自动替换结果区。

选择 Gemini / DeepSeek 时不会用本地预置歌单冒充线上结果；如果线上模型失败，页面会显示错误。

## 部署上线

见 [DEPLOYMENT.md](./DEPLOYMENT.md)。线上部署建议使用 Docker，并通过云平台环境变量注入 Gemini / DeepSeek Key；不要把 `.env` 提交或打包进镜像。
