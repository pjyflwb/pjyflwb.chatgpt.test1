/** 功能使用独立的模型选择，名单以服务器配置为准。 */
let modelCatalog = {text:[], image:[], video:[]};
const selectedModels = {};
function fillModels(select, models) {
  select.replaceChildren();
  models.forEach(model => { const option = document.createElement('option'); option.value = model; option.textContent = model; select.append(option); });
}
function updateModelOptions() {
  const select = document.querySelector('#tool-model');
  const category = currentTab === 'videos' ? 'video' : ['images','vision'].includes(currentTab) ? 'image' : 'text';
  fillModels(select, modelCatalog[category]);
  if (selectedModels[currentTab]) select.value = selectedModels[currentTab];
  document.querySelector('#tool-note').textContent = currentTab === 'videos' ? '视频需配置服务商异步任务接口；未配置密钥时仅展示演示提示。' : currentTab === 'vision' ? '所列图片模型的视觉识别能力需由服务商确认。' : '';
}
/** 浏览器交互：切换工具、提交请求、展示错误及回收下载 URL。 */
let currentTab = 'images';
let downloadUrl = null;
const titles = {images:'图片生成', vision:'图片识别', files:'文件生成', videos:'视频制作', chat:'AI 聊天'};
const result = document.querySelector('#result');
const submit = document.querySelector('#submit');
document.querySelectorAll('[data-tab]').forEach(button => {
  button.addEventListener('click', () => {
    currentTab = button.dataset.tab;
    document.querySelector('.workspace').hidden = currentTab === 'chat';
    document.querySelector('#chat-panel').hidden = currentTab !== 'chat';
    document.querySelectorAll('[data-tab]').forEach(item => item.classList.toggle('active', item === button));
    updateModelOptions();
    document.querySelector('#format-wrap').hidden = currentTab !== 'files';
    document.querySelector('#title').textContent = titles[currentTab];
    document.querySelector('#upload').hidden = currentTab !== 'vision';
    document.querySelector('#file').required = currentTab === 'vision';
    document.querySelector('#pages-wrap').hidden = currentTab !== 'files' || document.querySelector('#file-format').value !== 'pptx';
    document.querySelector('#prompt').placeholder = currentTab === 'vision' ? '你想了解图片中的哪些内容？' : '描述你的创作主题与要求…';
  });
});
fetch('/api/status').then(r => r.json()).then(data => {
  modelCatalog = data.models; updateModelOptions();
  fillModels(document.querySelector('#chat-model'), modelCatalog.text);
  document.querySelector('#mode').textContent = data.demo ? '● 演示模式 · 尚未配置密钥' : '● API 已配置';
}).catch(() => { document.querySelector('#mode').textContent = '连接失败，请刷新'; });
document.querySelector('#form').addEventListener('submit', async event => {
  event.preventDefault();
  // 固定本次请求的工具类型，避免等待期间切换造成响应错配。
  const tab = currentTab;
  const format = document.querySelector('#file-format').value;
  document.querySelectorAll('[data-tab]').forEach(button => button.disabled = true);
  submit.disabled = true;
  result.textContent = '正在处理，请稍候…';
  if (downloadUrl) { URL.revokeObjectURL(downloadUrl); downloadUrl = null; }
  try {
    const prompt = document.querySelector('#prompt').value.trim();
    if (!prompt) throw new Error('请输入有效的提示词。');
    let options;
    if (tab === 'vision') {
      const file = document.querySelector('#file').files[0];
      if (!file || file.size > 8 * 1024 * 1024) throw new Error('请选择不超过 8 MB 的图片。');
      const body = new FormData(); body.append('file', file); body.append('prompt', prompt); body.append('model', document.querySelector('#tool-model').value);
      options = {method:'POST', body};
    } else {
      options = {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt, model:document.querySelector('#tool-model').value, format:document.querySelector('#file-format').value, pages:Number(document.querySelector('#pages').value)})};
    }
    const response = await fetch(`/api/${tab}`, options);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === 'string' ? error.detail : '输入参数无效，请检查后重试。');
    }
    result.replaceChildren();
    if (tab === 'files') {
      downloadUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = downloadUrl; link.download = `ai-document.${format}`; link.textContent = `✓ ${format === 'pptx' ? 'PPT' : 'Word'} 已生成，点击下载`; result.append(link);
    } else {
      const data = await response.json();
      if (tab === 'videos') { await showVideoTask(data); }
      else if (tab === 'images') {
        const image = document.createElement('img'); image.src = data.url; image.alt = '生成结果'; result.append(image);
        const tip = document.createElement('p'); tip.textContent = data.demo ? '演示占位图：配置密钥后将生成真实图片。' : '图片已生成，可右键保存。'; result.append(tip);
      } else { result.textContent = data.text; result.append(copyButton(() => data.text)); }
    }
  } catch (error) { result.textContent = `处理失败：${error.message}`; }
  finally { submit.disabled = false; document.querySelectorAll('[data-tab]').forEach(button => button.disabled = false); }
});


/** 聊天记录仅保存在本页内存中，使用 textContent 防止模型文本注入 HTML。 */
let chatHistory = [];
let chatBusy = false;
const chatMessages = document.querySelector('#chat-messages');
const chatFiles = document.querySelector('#chat-files');
const chatStatus = document.querySelector('#chat-status');
function addMessage(role, text, files = []) {
  const bubble = document.createElement('article');
  bubble.className = `message ${role}`;
  const label = document.createElement('strong');
  label.textContent = role === 'user' ? '你' : 'AI 助手';
  const body = document.createElement('div'); body.textContent = text;
  bubble.append(label, body);
  files.forEach(file => {
    const name = document.createElement('p'); name.className = 'hint'; name.textContent = `附件：${file.name}`; bubble.append(name);
    if (['image/png','image/jpeg','image/webp'].includes(file.type)) {
      const img = document.createElement('img');
      const url = URL.createObjectURL(file); img.src = url; img.alt = file.name;
      img.onload = img.onerror = () => URL.revokeObjectURL(url);
      bubble.append(img);
    }
  });
  chatMessages.append(bubble); bubble.scrollIntoView({block:'nearest'});
  return {bubble, body};
}
chatFiles.addEventListener('change', () => {
  const list = document.querySelector('#attachment-list'); list.replaceChildren();
  Array.from(chatFiles.files).forEach((file, index) => {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = `${file.name} ×`;
    button.addEventListener('click', () => {
      const selection = new DataTransfer();
      Array.from(chatFiles.files).forEach((item, i) => { if (i !== index) selection.items.add(item); });
      chatFiles.files = selection.files; chatFiles.dispatchEvent(new Event('change'));
    });
    list.append(button);
  });
});
document.querySelector('#clear-chat').addEventListener('click', () => {
  if (chatBusy) return;
  chatHistory = []; chatMessages.replaceChildren(); chatStatus.textContent = '';
});
document.querySelector('#chat-form').addEventListener('submit', async event => {
  event.preventDefault(); if (chatBusy) return;
  const input = document.querySelector('#chat-prompt');
  const prompt = input.value.trim(); const files = Array.from(chatFiles.files);
  if (!prompt && !files.length) { chatStatus.textContent = '请输入消息或添加附件。'; return; }
  if (files.length > 3 || files.some(file => file.size > 8 * 1024 * 1024)) {
    chatStatus.textContent = '最多上传 3 个附件，每个不能超过 8 MB。'; return;
  }
  chatBusy = true;
  document.querySelector('#chat-send').disabled = true;
  document.querySelector('#clear-chat').disabled = true;
  input.disabled = true; chatFiles.disabled = true;
  chatStatus.textContent = 'AI 正在思考…';
  const body = new FormData(); body.append('prompt', prompt); body.append('history', JSON.stringify(chatHistory)); body.append('model', document.querySelector('#chat-model').value);
  files.forEach(file => body.append('files', file));
  try {
    body.append('stream', 'true');
    const response = await fetch('/api/chat', {method:'POST', body});
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === 'string' ? error.detail : '提交失败，请检查输入。');
    }
    addMessage('user', prompt || '请分析上传的附件。', files);
    const assistant = addMessage('assistant', '');
    let metadata = null; let answer = ''; let completed = false;
    try {
      await consumeEvents(response, (kind, data) => {
        if (kind === 'meta') metadata = data;
        if (kind === 'delta') {
          answer += data.text; renderAssistantContent(assistant.body, answer);
          chatStatus.textContent = '正在生成回复…';
          assistant.bubble.scrollIntoView({block:'nearest'});
        }
        if (kind === 'error') throw new Error(data.message);
        if (kind === 'done') completed = true;
      });
      if (!completed || !metadata || !answer) throw new Error('回复未完整接收，请重试。');
      renderAssistantContent(assistant.body, answer, true);
      assistant.bubble.append(copyButton(() => answer));
    } catch (error) {
      const note = document.createElement('p'); note.textContent = '回复中断，未加入对话上下文。'; assistant.bubble.append(note);
      throw error;
    }
    chatHistory.push({role:'user', content:metadata.user_context}, {role:'assistant', content:answer});
    input.value = ''; chatFiles.value = ''; chatFiles.dispatchEvent(new Event('change'));
    chatStatus.textContent = metadata.demo ? '演示模式：尚未调用真实模型。' : '回复完成';
  } catch (error) { chatStatus.textContent = `发送失败：${error.message}（输入已保留，可重试）`; }
  finally {
    chatBusy = false; input.disabled = false; chatFiles.disabled = false;
    document.querySelector('#chat-send').disabled = false;
    document.querySelector('#clear-chat').disabled = false;
  }
});

document.querySelector('#tool-model').addEventListener('change', event => { selectedModels[currentTab] = event.target.value; });
document.querySelector('#file-format').addEventListener('change', event => {
  document.querySelector('#pages-wrap').hidden = currentTab !== 'files' || event.target.value !== 'pptx';
});
/** 异步视频任务最多查询 120 次，超时保留任务 ID 供手动继续查询。 */
async function showVideoTask(task) {
  if (task.demo) { result.textContent = task.message; return; }
  for (let attempt = 0; attempt < 120; attempt++) {
    result.textContent = `视频任务 ${task.id}：${task.status}`;
    if (task.status === 'completed') {
      const video = document.createElement('video'); video.controls = true; video.src = task.url; video.style.maxWidth = '100%';
      const link = document.createElement('a'); link.href = task.url; link.textContent = '打开视频 / 保存视频'; link.target = '_blank'; link.rel = 'noopener';
      result.append(document.createElement('br'), video, link); return;
    }
    if (['failed','cancelled'].includes(task.status)) throw new Error('视频任务失败或已取消，请检查服务商任务记录。');
    await new Promise(resolve => setTimeout(resolve, 5000));
    const response = await fetch(`/api/videos/${encodeURIComponent(task.id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '视频状态查询失败');
    task = data;
  }
  result.textContent = `任务 ${task.id} 仍在生成。`;
  const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '继续查询';
  retry.onclick = async () => { retry.disabled = true; try { await showVideoTask(task); } catch(error) { result.textContent = error.message; } };
  result.append(retry);
}


/** 按 SSE 事件边界解码，支持中文字符与事件跨网络分片。 */
async function consumeEvents(response, onEvent) {
  const reader = response.body.getReader(); const decoder = new TextDecoder();
  let buffer = '';
  function dispatch(frame) {
    let kind = 'message'; const lines = [];
    frame.split('\n').forEach(line => {
      if (line.startsWith('event:')) kind = line.slice(6).trim();
      if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
    });
    if (lines.length) onEvent(kind, JSON.parse(lines.join('\n')));
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        dispatch(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  } finally { await reader.cancel(); reader.releaseLock(); }
}

/** 仅复制正文；不支持剪贴板 API 时提供手动复制窗口。 */
function copyButton(getText) {
  const button = document.createElement('button'); button.type = 'button';
  button.className = 'copy-button'; button.textContent = '复制内容';
  button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(getText()); button.textContent = '已复制'; }
    catch { window.prompt('请复制以下内容：', getText()); }
    setTimeout(() => { button.textContent = button.closest('.code-panel') ? '复制代码' : '复制内容'; }, 2000);
  });
  return button;
}
/** 安全解析 Markdown 围栏代码块，不使用 innerHTML 或执行模型输出。 */
function splitCodeBlocks(source) {
  const blocks = [];
  const lines = source.split('\n');
  let prose = []; let code = []; let fence = null; let language = '';
  function flushText() {
    if (prose.length) blocks.push({type:'text', text:prose.join('\n')});
    prose = [];
  }
  for (const line of lines) {
    if (!fence) {
      const opening = line.match(/^ {0,3}(`{3,}|~{3,})([^\r]*)\r?$/);
      if (opening) {
        flushText(); fence = opening[1]; language = opening[2].trim(); code = [];
      } else prose.push(line);
    } else {
      const closing = line.match(/^ {0,3}(`{3,}|~{3,})\s*$/);
      if (closing && closing[1][0] === fence[0] && closing[1].length >= fence.length) {
        blocks.push({type:'code', text:code.join('\n'), language, complete:true});
        fence = null; code = [];
      } else code.push(line);
    }
  }
  // 流式生成尚未收到闭合围栏时，也提前展示代码背景。
  if (fence) blocks.push({type:'code', text:code.join('\n'), language, complete:false});
  else flushText();
  return blocks;
}

function renderAssistantContent(container, source, finished = false) {
  container.replaceChildren();
  splitCodeBlocks(source).forEach(block => {
    if (block.type === 'text') {
      const text = document.createElement('div'); text.className = 'reply-text';
      text.textContent = block.text; container.append(text); return;
    }
    const panel = document.createElement('section'); panel.className = 'code-panel';
    const header = document.createElement('div'); header.className = 'code-header';
    const label = document.createElement('span'); label.textContent = block.language || '代码';
    const button = copyButton(() => block.text);
    button.textContent = '复制代码';
    button.disabled = !finished;
    button.title = finished ? '复制此代码块' : '回复完成后可复制';
    header.append(label, button);
    const pre = document.createElement('pre'); const code = document.createElement('code');
    code.textContent = block.text; pre.append(code); panel.append(header, pre); container.append(panel);
  });
}
