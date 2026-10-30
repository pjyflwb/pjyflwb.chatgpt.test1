"""集中读取服务端配置；密钥永远不返回浏览器。"""
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("AI_API_KEY", "").strip()
BASE_URL = os.getenv("AI_BASE_URL", "https://maas.qianwenaiapi.com/compatible-mode/v1").rstrip("/")
TEXT_MODEL = os.getenv("AI_TEXT_MODEL", "deepseek-v4.1-flash")
IMAGE_MODEL = os.getenv("AI_IMAGE_MODEL", "qwen-image-3.0")

TEXT_MODELS = ['deepseek-v4.1-flash', 'qwen3.8-flash', 'qwen3.7-flashl']
IMAGE_MODELS = ['qwen-image-3.0', 'qwen-image-2.1-pro']
VIDEO_MODELS = ['MiniMax/MiniMax-H3']
# 视频协议需依据服务商文档确认；空路径时拒绝真实调用，避免请求错误接口。
VIDEO_PATH = os.getenv('AI_VIDEO_PATH', '').strip('/')

def select_model(model: str | None, category: str) -> str:
    """只允许选择服务器公开的模型，防止任意模型调用。"""
    from fastapi import HTTPException
    options = {'text': TEXT_MODELS, 'image': IMAGE_MODELS, 'video': VIDEO_MODELS}[category]
    selected = model or options[0]
    if selected not in options:
        raise HTTPException(422, '所选模型不在可用列表中。')
    return selected
