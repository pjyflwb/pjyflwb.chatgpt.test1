"""文件与视频生成路由；文件在内存生成，视频使用可配置任务协议。"""
import json
import re
from io import BytesIO
from typing import Literal
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from app import config
from app.provider import chat, request_ai

router = APIRouter()

class CreationInput(BaseModel):
    """文件和视频的通用输入。"""
    prompt: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    model: str | None = None
    format: Literal['pptx', 'docx'] = 'pptx'
    pages: int = Field(default=6, ge=3, le=12)

class Section(BaseModel):
    """Word 章节结构，限制输出规模。"""
    title: str = Field(min_length=1, max_length=100)
    paragraphs: list[str] = Field(min_length=1, max_length=8)

class DocumentContent(BaseModel):
    """结构化 Word 内容契约。"""
    title: str = Field(min_length=1, max_length=100)
    sections: list[Section] = Field(min_length=1, max_length=12)

def render_word(content: DocumentContent) -> bytes:
    """以标准 OOXML 打包可编辑 DOCX，无额外运行依赖。"""
    def paragraph(text: str, style: str = 'Normal') -> str:
        # XML 1.0 不允许部分控制字符，先清理再转义。
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(clean)}</w:t></w:r></w:p>'
    body = paragraph(content.title, 'Title')
    for section in content.sections:
        body += paragraph(section.title, 'Heading1')
        body += ''.join(paragraph(text) for text in section.paragraphs)
    namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr('word/styles.xml', f'<w:styles xmlns:w="{namespace}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style></w:styles>')
        archive.writestr('word/document.xml', f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{namespace}"><w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    return output.getvalue()

@router.post('/api/files')
async def generate_file(body: CreationInput):
    """复用 PPT 生成器或生成 Word 文档。"""
    model = config.select_model(body.model, 'text')
    if body.format == 'pptx':
        from app.main import presentation, PresentationInput
        return await presentation(PresentationInput(prompt=body.prompt, model=model, pages=body.pages))
    if not config.API_KEY:
        content = DocumentContent(title=body.prompt[:100], sections=[Section(title='演示文档', paragraphs=['这是演示内容。配置 API Key 后将依据主题生成正文。'])])
    else:
        raw = await chat(f'围绕主题生成完整中文文档：{body.prompt}。返回 JSON 对象：title 字符串，sections 数组，每项包含 title 和 paragraphs 字符串数组。标题最多100字，1至12节，每节1至8段，每段最多2000字。', json_mode=True, model=model)
        try:
            content = DocumentContent.model_validate(json.loads(raw))
            if any(len(p) > 2000 for section in content.sections for p in section.paragraphs):
                raise ValueError('Paragraph too long')
        except (ValueError, TypeError, ValidationError) as exc:
            raise HTTPException(502, '模型文档格式无效，请重试。') from exc
    return Response(render_word(content), media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition': 'attachment; filename="ai-document.docx"'})

def normalize_video(data: dict) -> dict:
    """归一化兼容视频任务响应，不接受不安全的播放 URL。"""
    try:
        task_id = str(data.get('id') or data.get('task_id') or '')
        state = data.get('status', 'queued')
        state = {'succeeded':'completed', 'success':'completed', 'pending':'queued', 'running':'processing'}.get(state, state)
        url = data.get('url') or data.get('video_url')
        if state not in {'queued', 'processing', 'completed', 'failed', 'cancelled'}:
            raise ValueError('Unknown status')
        if url and (not isinstance(url, str) or not url.startswith('https://')):
            raise ValueError('Unsafe URL')
        if not task_id or (state == 'completed' and not url):
            raise ValueError('Incomplete response')
        return {'id':task_id, 'status':state, 'url':url, 'demo':False}
    except (AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(502, '视频响应不符合兼容协议，请依据服务商文档调整适配器。') from exc

@router.post('/api/videos')
async def create_video(body: CreationInput):
    """提交异步视频任务；演示模式不伪造视频成片。"""
    model = config.select_model(body.model, 'video')
    if not config.API_KEY:
        return {'demo':True, 'status':'demo', 'message':'演示模式：参数已验证。填写密钥并确认视频接口配置后可生成真实视频。'}
    if not config.VIDEO_PATH:
        raise HTTPException(503, '请先按服务商文档配置 AI_VIDEO_PATH，并确认视频请求与响应协议。')
    return normalize_video(await request_ai(config.VIDEO_PATH, {'model':model, 'prompt':body.prompt}))

@router.get('/api/videos/{task_id}')
async def query_video(task_id: str):
    """按任务 ID 查询状态，限制路径字符防止路径注入。"""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task_id):
        raise HTTPException(422, '视频任务 ID 无效。')
    if not config.API_KEY or not config.VIDEO_PATH:
        raise HTTPException(503, '视频服务尚未配置。')
    return normalize_video(await request_ai(f'{config.VIDEO_PATH}/{task_id}', None, method='GET'))
