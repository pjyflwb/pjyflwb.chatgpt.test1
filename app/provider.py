"""OpenAI 兼容接口适配层，统一处理超时及服务商错误。"""
import httpx
from fastapi import HTTPException
from app import config

async def request_ai(endpoint: str, payload: dict | None, *, method: str = "POST") -> dict:
    """调用服务端配置的 API；错误信息不暴露上游响应或密钥。"""
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.request(
                method,
                f"{config.BASE_URL}/{endpoint}", json=payload,
                headers={"Authorization": f"Bearer {config.API_KEY}"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "模型响应超时，请稍后重试。") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "模型接口调用失败，请检查密钥、模型名称及服务商配置。") from exc

async def chat(content: str | list, *, json_mode: bool = False, messages: list | None = None, model: str | None = None) -> str:
    """发送文本或带图片的消息，可要求模型输出 JSON。"""
    payload = {"model": model or config.TEXT_MODEL, "messages": messages if messages is not None else [{"role": "user", "content": content}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = await request_ai("chat/completions", payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "模型返回的数据格式不符合预期。") from exc

async def stream_chat(messages: list, model: str):
    """逐条解析兼容接口的 SSE；断流视为错误，取消时自动关闭连接。"""
    import json
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream('POST', f'{config.BASE_URL}/chat/completions',
                                     json={'model': model, 'messages': messages, 'stream': True},
                                     headers={'Authorization': f'Bearer {config.API_KEY}', 'Accept': 'text/event-stream'}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    value = line[5:].strip()
                    if value == '[DONE]':
                        return
                    if not value:
                        continue
                    data = json.loads(value)
                    if 'error' in data:
                        raise ValueError('Upstream error')
                    choices = data.get('choices', [])
                    if choices:
                        text = choices[0].get('delta', {}).get('content')
                        if text:
                            if not isinstance(text, str):
                                raise ValueError('Invalid delta')
                            yield text
                raise ValueError('Incomplete stream')
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(502, '流式回复中断或接口调用失败，请检查模型配置后重试。') from exc
