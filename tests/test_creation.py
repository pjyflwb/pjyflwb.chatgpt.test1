"""验证文件生成、模型选择和可配置视频任务适配。"""
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree
from zipfile import ZipFile
from fastapi.testclient import TestClient
from app.main import app

class CreationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patcher = patch('app.config.API_KEY','')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_word_package(self):
        response = self.client.post('/api/files',json={'prompt':'项目说明','format':'docx','model':'qwen3.8-flash'})
        self.assertEqual(response.status_code,200)
        with ZipFile(BytesIO(response.content)) as archive:
            for name in archive.namelist():
                ElementTree.fromstring(archive.read(name))
            self.assertIn('项目说明',archive.read('word/document.xml').decode())

    def test_ppt_and_model_validation(self):
        response = self.client.post('/api/files',json={'prompt':'项目','format':'pptx','model':'deepseek-v4.1-flash'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/api/images',json={'prompt':'猫','model':'unknown'}).status_code,422)
        self.assertEqual(self.client.post('/api/chat',data={'prompt':'你好','model':'qwen-image-3.0'}).status_code,422)

    def test_video_demo_and_unconfigured(self):
        self.assertTrue(self.client.post('/api/videos',json={'prompt':'海浪','model':'MiniMax/MiniMax-H3'}).json()['demo'])
        with patch('app.config.API_KEY','test'),patch('app.config.VIDEO_PATH',''):
            self.assertEqual(self.client.post('/api/videos',json={'prompt':'海浪'}).status_code,503)

    def test_video_submission_and_poll(self):
        mock = AsyncMock(side_effect=[{'id':'job_1','status':'queued'},{'id':'job_1','status':'completed','url':'https://example.com/movie.mp4'}])
        with patch('app.config.API_KEY','test'),patch('app.config.VIDEO_PATH','videos'),patch('app.creation.request_ai',mock):
            response = self.client.post('/api/videos',json={'prompt':'海浪','model':'MiniMax/MiniMax-H3'})
            self.assertEqual(response.json()['status'],'queued')
            self.assertEqual(mock.call_args.args[1]['model'],'MiniMax/MiniMax-H3')
            self.assertEqual(self.client.get('/api/videos/job_1').json()['status'],'completed')

    def test_selected_text_model_forwarded(self):
        mock=AsyncMock(return_value='你好')
        with patch('app.config.API_KEY','test'),patch('app.conversation.chat',mock):
            self.assertEqual(self.client.post('/api/chat',data={'prompt':'你好','model':'qwen3.7-flashl'}).status_code,200)
            self.assertEqual(mock.call_args.kwargs['model'],'qwen3.7-flashl')
