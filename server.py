import json
import asyncio
from typing import AsyncIterator
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv(override=True)

from vietnam_legal_agent.api.routes import stream_chat_events
from vietnam_legal_agent.infra.llm_instances import get_embeddings

app = FastAPI(title="Vietnam Legal Agent API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    user_id: str | None = "web_user"

@app.on_event("startup")
async def startup_event():
    print("🔥 Đang khởi động trước embedding model trên GPU CUDA...")
    try:
        emb = get_embeddings()
        emb.embed_query("warmup legal agent")
        print(f"✅ Embedding model sẵn sàng trên: {getattr(emb, 'device', 'unknown')}")
    except Exception as exc:
        print(f"⚠️ Warmup embedding cảnh báo: {exc}")

@app.get("/health")
def health_check():
    return {"status": "ok", "app": "Vietnam Legal Agent", "version": "4.0"}

async def sse_generator(query: str, user_id: str, conv_id: str) -> AsyncIterator[str]:
    try:
        async for ev in stream_chat_events(
            query=query,
            user_id=user_id,
            conversation_id=conv_id,
        ):
            ev_json = json.dumps(ev, ensure_ascii=False)
            yield f"data: {ev_json}\n\n"
    except Exception as exc:
        err_json = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
        yield f"data: {err_json}\n\n"

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    conv_id = req.conversation_id or f"web_conv_{int(asyncio.get_event_loop().time())}"
    user_id = req.user_id or "web_user"
    return StreamingResponse(
        sse_generator(req.query, user_id, conv_id),
        media_type="text/event-stream",
    )

HTML_CHAT_UI = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trợ Lý Pháp Luật Việt Nam</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 flex flex-col h-screen">
    <!-- Header -->
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur px-6 py-4 flex items-center justify-between">
        <div class="flex items-center space-x-3">
            <div class="w-9 h-9 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center font-bold text-lg border border-amber-500/30">⚖️</div>
            <div>
                <h1 class="font-bold text-base text-slate-100">Vietnam Legal Agent</h1>
                <p class="text-xs text-slate-400">Trợ lý Pháp lý Thông minh • Căn cứ Luật Việt Nam</p>
            </div>
        </div>
        <div class="flex items-center space-x-2">
            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span class="w-1.5 h-1.5 mr-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Sẵn sàng
            </span>
        </div>
    </header>

    <!-- Chat Messages Container -->
    <main id="chatBox" class="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 max-w-4xl mx-auto w-full">
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 text-sm text-slate-300 leading-relaxed shadow-sm">
            Xin chào! Tôi là trợ lý pháp lý hỗ trợ tra cứu quy định pháp luật Việt Nam (Lao động, Dân sự, Giao thông, v.v.). Bạn có thể hỏi trực tiếp các tình huống bằng ngôn ngữ tự nhiên.
        </div>
    </main>

    <!-- Input Footer -->
    <footer class="border-t border-slate-800 bg-slate-900/80 p-4 max-w-4xl mx-auto w-full">
        <form id="chatForm" class="flex items-center gap-2">
            <input 
                id="queryInput" 
                type="text" 
                placeholder="Nhập tình huống hoặc câu hỏi pháp lý..." 
                class="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                required
            />
            <button 
                type="submit" 
                id="sendBtn"
                class="bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold px-5 py-3 rounded-xl text-sm transition shadow-sm flex items-center gap-1.5"
            >
                Gửi
            </button>
        </form>
    </footer>

    <script>
        const chatBox = document.getElementById('chatBox');
        const chatForm = document.getElementById('chatForm');
        const queryInput = document.getElementById('queryInput');
        const sendBtn = document.getElementById('sendBtn');
        const convId = "web_" + Math.random().toString(36).substring(2, 9);

        function appendMessage(role, text) {
            const div = document.createElement('div');
            div.className = role === 'user' 
                ? 'bg-amber-500/10 border border-amber-500/30 text-amber-200 self-end ml-auto rounded-2xl p-4 text-sm max-w-[85%] whitespace-pre-wrap'
                : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-2xl p-4 text-sm max-w-[90%] whitespace-pre-wrap leading-relaxed';
            div.innerText = text;
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
            return div;
        }

        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const query = queryInput.value.trim();
            if (!query) return;

            appendMessage('user', query);
            queryInput.value = '';
            queryInput.disabled = true;
            sendBtn.disabled = true;

            const aiBubble = appendMessage('assistant', 'Đang tra cứu cơ sở pháp lý...');

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query, conversation_id: convId })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';
                let fullAnswer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });

                    const lines = buffer.split('\\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const dataStr = line.replace('data: ', '').trim();
                            if (!dataStr) continue;
                            try {
                                const ev = JSON.parse(dataStr);
                                if (ev.type === 'response_chunk') {
                                    fullAnswer += (ev.chunk || ev.content || '');
                                    aiBubble.innerText = fullAnswer;
                                    chatBox.scrollTop = chatBox.scrollHeight;
                                } else if (ev.type === 'response_complete') {
                                    if (ev.text) {
                                        aiBubble.innerText = ev.text;
                                    }
                                } else if (ev.type === 'error') {
                                    aiBubble.innerText = 'Lỗi: ' + (ev.message || 'Không thể tải câu trả lời.');
                                }
                            } catch (err) {}
                        }
                    }
                }
            } catch (err) {
                aiBubble.innerText = 'Lỗi kết nối tới máy chủ.';
            } finally {
                queryInput.disabled = false;
                sendBtn.disabled = false;
                queryInput.focus();
            }
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_CHAT_UI

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
