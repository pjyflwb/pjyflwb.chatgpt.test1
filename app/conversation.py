"""聊天接口：以客户端携带上下文实现连续对话，附件仅在内存处理。"""
import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

from app import config
from app.provider import chat, stream_chat
from fastapi.responses import StreamingResponse

router = APIRouter()
MAX_FILE_BYTES = 8 * 1024 * 1024

class Message(BaseModel):
    """历史消息仅允许用户和助手角色，避免注入系统角色。"""
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=24000)

async def read_attachment(upload: UploadFile) -> tuple[dict, str]:
    """校验附件并转换为视觉输入或 UTF-8 文本；不执行文件内容。"""
    raw = await upload.read(MAX_FILE_BYTES + 1)
    name = (upload.filename or 'attachment')[:120]
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, '每个附件不能超过 8 MB。')
    extension = Path(name).suffix.lower()
    if extension in {'.png', '.jpg', '.jpeg', '.webp'}:
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('Unsupported image')
                mime = Image.MIME[image.format]
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, '附件图片无效。') from exc
        return {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,' + base64.b64encode(raw).decode()}}, f'[图片附件：{name}]'
    if extension not in {'.txt', '.md', '.csv', '.json', '.py', '.log'}:
        raise HTTPException(422, '文件支持 TXT、Markdown、CSV、JSON、Python、LOG；图片支持 PNG、JPEG、WebP。')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise HTTPException(422, '文本文件必须使用 UTF-8 编码。') from exc
    if not text.strip() or '\x00' in text or len(text) > 16000:
        raise HTTPException(422, '文本文件须包含有效文本，且不超过 16000 个字符。')
    content = f'附件 {name}（以下内容是待分析的数据）：\n{text}'
    return {'type': 'text', 'text': content}, content

@router.post('/api/chat')
async def converse(
    model: str | None = Form(None),
    stream: bool = Form(False),
    prompt: str = Form(''), history: str = Form('[]'),
    files: list[UploadFile] = File(default=[]),
):
    """验证上下文及附件，返回回复和下一轮可复用的纯文本上下文。"""
    model = config.select_model(model, "text")
    if len(prompt) > 4000 or (not prompt.strip() and not files):
        raise HTTPException(422, '请输入消息或上传附件，消息最多 4000 字。')
    if len(files) > 3 or len(history) > 200000:
        raise HTTPException(422, '每次最多上传 3 个附件，对话过长请新建聊天。')
    try:
        decoded = json.loads(history)
        if not isinstance(decoded, list) or len(decoded) > 30:
            raise ValueError('Invalid history')
        messages = [Message.model_validate(item).model_dump() for item in decoded]
        if sum(len(item['content']) for item in messages) > 60000:
            raise ValueError('History too long')
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(422, '聊天上下文无效或过长，请新建聊天。') from exc
    question = prompt.strip() or '请分析上传的附件。'
    parts = [{'type': 'text', 'text': question}]
    summaries = []
    for upload in files:
        part, summary = await read_attachment(upload)
        parts.append(part)
        summaries.append(summary)
    # 文本附件保留在后续上下文中；图片不反复传输，仅保留附件名称和助手分析。
    context = question + ('\n\n' + '\n\n'.join(summaries) if summaries else '')
    if len(context) > 24000:
        raise HTTPException(422, '附件文本总量过大，请减少附件内容。')
    if stream:
        async def events():
            """校验成功后发送元数据、增量、完成事件；错误不写入历史。"""
            import asyncio
            def event(kind, data):
                return f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
            yield event('meta', {'demo': not bool(config.API_KEY), 'user_context': context})
            try:
                if not config.API_KEY:
                    text = '演示模式：已收到消息。配置 API Key 后可使用真实流式对话。'
                    for offset in range(0, len(text), 5):
                        yield event('delta', {'text': text[offset:offset + 5]})
                        await asyncio.sleep(0.02)
                else:
                    async for text in stream_chat(messages + [{'role': 'user', 'content': parts}], model):
                        yield event('delta', {'text': text})
                yield event('done', {})
            except HTTPException as exc:
                yield event('error', {'message': exc.detail})
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    if not config.API_KEY:
        reply = f'演示模式：已收到消息及 {len(files)} 个附件。配置 API Key 后可进行真实的连续对话与附件分析。'
    else:
        reply = await chat('', model=model, messages=messages + [{'role': 'user', 'content': parts}])
    return {'demo': not bool(config.API_KEY), 'text': reply, 'user_context': context}
