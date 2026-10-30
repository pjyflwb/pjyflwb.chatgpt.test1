"""聊天上下文与附件校验测试，不调用真实模型。"""
import unittest
from io import BytesIO
from unittest.mock import patch, AsyncMock
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

class ChatTests(unittest.TestCase):
    """验证聊天闭环与不可信上传的处理。"""
    def setUp(self):
        self.client = TestClient(app)
        patcher = patch('app.config.API_KEY', '')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_demo_and_text_upload(self):
        response = self.client.post('/api/chat', data={'prompt':'总结'}, files={'files':('notes.md','会议记录'.encode(),'text/plain')})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['demo'])
        self.assertIn('会议记录', response.json()['user_context'])

    def test_empty_and_invalid_history(self):
        self.assertEqual(self.client.post('/api/chat').status_code, 422)
        self.assertEqual(self.client.post('/api/chat', data={'prompt':'你好','history':'{}'}).status_code, 422)
        self.assertEqual(self.client.post('/api/chat', data={'prompt':'你好','history':'[{"role":"system","content":"x"}]'}).status_code, 422)

    def test_reject_unsupported_and_fake_image(self):
        for name, raw in [('test.exe',b'test'), ('fake.png',b'bad'), ('test.txt',b'\xff')]:
            self.assertEqual(self.client.post('/api/chat', files={'files':(name,raw)}).status_code, 422)

    def test_image_and_history_forwarded(self):
        image = BytesIO()
        Image.new('RGB',(10,10)).save(image,format='PNG')
        mock = AsyncMock(return_value='识别结果')
        with patch('app.config.API_KEY','test'), patch('app.conversation.chat',mock):
            response = self.client.post('/api/chat', data={'prompt':'分析','history':'[{"role":"user","content":"你好"},{"role":"assistant","content":"你好！"}]'}, files={'files':('test.png',image.getvalue(),'image/png')})
        self.assertEqual(response.status_code, 200)
        messages = mock.call_args.kwargs['messages']
        self.assertEqual(len(messages),3)
        self.assertEqual(messages[-1]['content'][1]['type'],'image_url')

    def test_too_many_files(self):
        response = self.client.post('/api/chat',files=[('files',(f'{i}.txt',b'a')) for i in range(4)])
        self.assertEqual(response.status_code,422)
