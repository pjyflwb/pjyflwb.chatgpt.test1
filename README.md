# AI Studio

基于 Python FastAPI 的本地 AI 网页工作台，包含图片生成、图片识别（含文字识别）、PPTX 生成。模块、函数和关键流程均配有中文说明。

## 启动（Windows PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器访问 http://127.0.0.1:8000 ，接口文档访问 /docs。建议 Python 3.11 或更高版本。

## 接入模型

编辑 `.env`，填写 `AI_API_KEY`，重启服务。`AI_BASE_URL` 必须是受信任的 OpenAI 兼容服务地址（包含 /v1）；文字、视觉模型共用 `AI_TEXT_MODEL`，图片模型使用 `AI_IMAGE_MODEL`。服务商必须分别支持 chat/completions、视觉图片输入、JSON 输出及 images/generations。不同供应商模型名称和兼容程度不同，后续可以扩展 provider.py 适配。密钥只保存在本机 `.env`，不要提交至版本库。

未填写密钥：图片生成返回纯色占位图，图片识别仅检查文件并提示演示，PPT 下载包含演示文案的真实可编辑 PPTX。演示结果不冒充模型生成。

## 目录

- app/config.py：环境配置
- app/provider.py：异步模型服务适配、超时和错误处理
- app/slides.py：结构化大纲校验及可编辑 PPTX 排版
- app/main.py：路由和上传校验
- app/static/：响应式界面、样式、浏览器交互
- tests/test_app.py：演示流程、文件有效性及接口适配测试

## 验证

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

当前版本为单用户本地应用，无登录和持久化历史。上传图片及生成文件在内存处理。配置密钥后，提示词和图片会发送至配置的模型服务商。若要开放公网，需要补充身份认证、限流、HTTPS 及网关请求体限制。PPT 采用统一宽屏主题，复杂图表与逐页编辑可后续扩展。未接入真实密钥时无法验证供应商端到端调用。

## AI 聊天与附件

侧边栏「AI 聊天」支持多轮对话、图片预览、附件移除和新建聊天。每次最多 3 个附件，每个不超过 8 MB。支持 PNG/JPEG/WebP，以及 UTF-8 编码的 TXT、MD、CSV、JSON、PY、LOG；文本单文件最多 16000 字符，单轮含附件文本最多 24000 字符。暂不支持 PDF、Word 或压缩文件。

聊天记录只在当前页面内存保存，刷新即清空。后续轮次会携带之前的文本附件和助手回复；历史图片仅保留名称与分析结果，需要重新查看原图时请再次上传。上下文最多 30 条消息、60000 字符，超出后请新建聊天。API 为 `POST /api/chat`，使用 multipart 的 prompt、history（JSON 数组）和 files 字段。无密钥时仅验证附件并返回演示提示。

## 文件生成、视频制作与模型选择

五类工具均可选择模型。聊天及文件生成支持 deepseek-v4.1-flash、qwen3.8-flash、qwen3.7-flashl；图片生成与识别支持 qwen-image-3.0、qwen-image-2.1-pro；视频支持 MiniMax/MiniMax-H3。名称按用户提供原样保存，其可用性、视觉输入能力及图片接口兼容性需要在获得密钥后联调。

文件生成页面可选 PPTX 或 DOCX。Word 使用标准 OOXML 生成可编辑文档，包含标题、章节和正文。原 /api/presentations 保留兼容，新 /api/files 使用 format=pptx 或 docx。

默认 base URL 已调整为 https://maas.qianwenaiapi.com/compatible-mode/v1，API Key 留空。填写本机 .env 的 AI_API_KEY 后重启。不要将真实密钥填入网页或提交到仓库。

### 视频接口的待确认事项

尚未获得该服务商 MiniMax H3 的视频协议文档，因此 AI_VIDEO_PATH 默认留空，真实调用将返回明确的配置提示。当前适配器约定 POST <base>/<AI_VIDEO_PATH> 接收 model、prompt，返回 id（或 task_id）和 status；GET <base>/<AI_VIDEO_PATH>/<id> 返回状态和完成后的 HTTPS url（或 video_url）。支持 queued、processing、completed、failed、cancelled，并兼容部分常见状态别名。确认服务商采用该协议后再设置路径（例如 videos）；若采用其他协议，需要调整 app/creation.py 中的视频适配。不能仅凭模型名称确认协议。

页面每 5 秒查询状态，最多查询 10 分钟，随后可继续查询；成功后提供视频播放器与打开/保存链接。未配置密钥时仅返回演示提示，不生成虚构视频。真实接口、账户模型权限以及生成文件视觉排版仍需后续联调和实际预览。

## 流式聊天与复制
聊天页面默认通过 SSE 逐步显示回复，保留附件和多轮上下文。每条完整回复及图片识别文本提供复制按钮。未完整接收的回复保留展示但不写入上下文，输入保留以便重试。原 /api/chat 默认 JSON 响应仍兼容；传入 multipart 字段 stream=true 启用 meta、delta、done、error 事件。上游须支持 OpenAI 兼容 stream=true 和 data: [DONE]。反向代理部署时需关闭响应缓冲。


聊天回复支持 Markdown 围栏代码块（反引号或波浪线），代码以独立深色背景显示、保留缩进并可横向滚动。回复完成后，每个代码块均可单独复制，整条回复仍可复制。流式生成时提前展示代码背景；代码仅作为文本展示，不执行。解析验证：node tests/test_code_blocks.cjs。
