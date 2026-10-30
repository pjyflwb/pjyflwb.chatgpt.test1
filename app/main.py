"""HTTP 路由：参数校验、演示模式、文件上传及 PPT 下载。"""
import base64
import json
from io import BytesIO
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from app import config
from app.provider import chat, request_ai
from app.slides import Outline, render_ppt

app = FastAPI(title="AI Studio", version="1.0.0")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

class Prompt(BaseModel):
    """公用提示词输入，拒绝空文本及过长请求。"""
    model: str | None = None
    prompt: str = Field(min_length=1, max_length=4000, pattern=r"\S")

class PresentationInput(Prompt):
    """PPT 生成参数。"""
    pages: int = Field(default=6, ge=3, le=12)

@app.get("/")
def index():
    """返回工作台首页。"""
    return FileResponse(STATIC / "index.html")

@app.get("/api/status")
def status():
    """仅公开运行模式，不公开服务端凭据。"""
    return {"demo": not bool(config.API_KEY), "models": {"text": config.TEXT_MODELS, "image": config.IMAGE_MODELS, "video": config.VIDEO_MODELS}}

@app.post("/api/images")
async def generate_image(body: Prompt):
    """生成图片；无密钥时返回明确标注的本地占位图。"""
    model = config.select_model(body.model, "image")
    if not config.API_KEY:
        image = Image.new("RGB", (1024, 1024), "#193b47")
        output = BytesIO()
        image.save(output, format="PNG")
        return {"demo": True, "url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}
    data = await request_ai("images/generations", {"model": model, "prompt": body.prompt, "n": 1, "size": "1024x1024"})
    try:
        item = data["data"][0]
        url = "data:image/png;base64," + item["b64_json"] if item.get("b64_json") else item["url"]
        if not url.startswith(("https://", "data:image/")):
            raise ValueError("Invalid image URL")
        return {"demo": False, "url": url}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(502, "图片接口返回格式无效。") from exc

@app.post("/api/vision")
async def recognize(file: UploadFile = File(...), prompt: str = Form("请详细描述图片内容，并识别其中的文字。"), model: str | None = Form(None)):
    """验证真实图片并限制上传大小，再发送至视觉模型。"""
    model = config.select_model(model, "image")
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 8 MB。")
    if not prompt.strip() or len(prompt) > 4000:
        raise HTTPException(422, "问题须为 1–4000 个字符。")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported format")
            mime = Image.MIME[image.format]
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "请上传有效的 PNG、JPEG 或 WebP 图片。") from exc
    if not config.API_KEY:
        return {"demo": True, "text": "演示模式：图片验证通过。配置 API Key 后可获得真实的图片描述和文字识别结果。"}
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(raw).decode()}}]
    return {"demo": False, "text": await chat(content, model=model)}

@app.post("/api/presentations")
async def presentation(body: PresentationInput):
    """生成结构化大纲并导出 PPTX，不在磁盘保存用户内容。"""
    model = config.select_model(body.model, "text")
    if not config.API_KEY:
        outline = Outline(slides=[{"title": f"{body.prompt[:35]} · {i + 1}", "bullets": ["演示模板：请配置 API Key 生成主题相关内容", "背景与目标", "关键观点与后续行动"]} for i in range(body.pages)])
    else:
        raw = await chat(f"请为以下主题生成中文演示文稿：{body.prompt}。输出 JSON，格式为 {{slides: [{{title: 字符串, bullets: [字符串]}}]}}。恰好 {body.pages} 页，每页标题不超过 60 字，1 至 5 个要点，每个要点不超过 100 字。", json_mode=True, model=model)
        try:
            outline = Outline.model_validate(json.loads(raw))
            if len(outline.slides) != body.pages or any(len(p) > 100 for s in outline.slides for p in s.bullets):
                raise ValueError("Invalid outline length")
        except (ValidationError, ValueError, TypeError) as exc:
            raise HTTPException(502, "模型大纲格式无效，请重新生成。") from exc
    return Response(render_ppt(outline), media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": 'attachment; filename="ai-presentation.pptx"'})


from app.conversation import router as conversation_router
app.include_router(conversation_router)

from app.creation import router as creation_router
app.include_router(creation_router)
