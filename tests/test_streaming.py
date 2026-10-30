"""验证流式事件顺序、失败处理及上游增量解析。"""
import json
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.provider import stream_chat

class StreamingTests(unittest.TestCase):
    def test_demo_stream(self):
        with patch('app.config.API_KEY',''):
            response = TestClient(app).post('/api/chat',data={'prompt':'你好','stream':'true'})
        self.assertIn('text/event-stream',response.headers['content-type'])
        self.assertTrue(response.text.startswith('event: meta'))
        self.assertGreater(response.text.count('event: delta'),1)
        self.assertIn('event: done',response.text)

    def test_stream_failure_has_no_done(self):
        async def broken(*args):
            from fastapi import HTTPException
            yield '部分内容'
            raise HTTPException(502,'连接中断')
        with patch('app.config.API_KEY','test'),patch('app.conversation.stream_chat',broken):
            response = TestClient(app).post('/api/chat',data={'prompt':'你好','stream':'true'})
        self.assertIn('部分内容',response.text)
        self.assertIn('event: error',response.text)
        self.assertNotIn('event: done',response.text)

class ProviderStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_provider_protocol(self):
        def handler(request):
            self.assertTrue(json.loads(request.content)['stream'])
            return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: {"choices":[]}\n\ndata: [DONE]\n\n')
        factory = httpx.AsyncClient
        with patch('app.provider.httpx.AsyncClient',lambda **kwargs: factory(transport=httpx.MockTransport(handler),**kwargs)):
            chunks=[text async for text in stream_chat([{'role':'user','content':'hi'}],'test-model')]
        self.assertEqual(chunks,['你好'])
