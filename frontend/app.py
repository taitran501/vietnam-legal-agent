"""
Streamlit frontend — Clean, minimal ChatGPT-style UI.

Features:
  - Conversation sidebar (list/load/delete)
  - Real-time SSE streaming
  - Stop generation button
  - Message timestamps
  - Copy / Thumbs up-down / Regenerate per message
  - Onboarding with suggested prompts
  - Export (PDF/TXT)
  - Auto-title from first query

Run:
    streamlit run frontend/app.py
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from io import BytesIO
from typing import List, Dict, Optional

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
CHAT_ENDPOINT = f"{BACKEND_URL}/api/v1/chat"
SESSIONS_ENDPOINT = f"{BACKEND_URL}/api/v1/sessions"
FEEDBACK_ENDPOINT = f"{BACKEND_URL}/api/v1/feedback"
TIMEOUT = 120

st.set_page_config(
    page_title="EPR Assistant",
    page_icon="⚖️",
    layout="centered",
)

# Minimal custom CSS for ChatGPT-style look
st.markdown(
    """
<style>
    /* Hide Streamlit branding & make UI minimal */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}

    /* Chat-like message styling */
    .stChatMessage {border: none; padding: 12px 0;}
    .stChatMessage .stMarkdown p {margin: 0 0 8px 0; line-height: 1.65;}

    /* Small caption for timestamps / sources */
    .msg-meta {color: #9ca3af; font-size: 0.75rem; margin-top: 2px;}

    /* Inline action buttons */
    .action-row button {
        padding: 2px 6px; font-size: 0.75rem;
        border: none; background: transparent; cursor: pointer;
        color: #6b7280;
    }
    .action-row button:hover {color: #111827;}

    /* Sidebar conversation items */
    .conv-item {
        padding: 6px 8px; border-radius: 6px;
        font-size: 0.85rem; cursor: pointer;
    }
    .conv-item:hover {background: #f3f4f6;}
    .conv-item.active {background: #e5e7eb; font-weight: 500;}

    /* Onboarding example prompts */
    .example-btn {
        width: 100%; text-align: left; padding: 10px 14px;
        border: 1px solid #e5e7eb; border-radius: 8px;
        background: white; cursor: pointer;
    }
    .example-btn:hover {border-color: #9ca3af; background: #f9fafb;}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _init():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "generating" not in st.session_state:
        st.session_state.generating = False
    if "conversations" not in st.session_state:
        st.session_state.conversations = []


def _reset_chat():
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.generating = False
    st.rerun()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

# Shared HTTP client with connection pooling (created once, reused)
def _get_http_client() -> httpx.Client:
    """Get or create HTTP client with connection pooling and proper timeouts."""
    if "_http_client" not in st.session_state:
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        st.session_state._http_client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=TIMEOUT, write=10.0, pool=10.0),
            limits=limits,
            http2=False,  # Use HTTP/1.1 for better compatibility
        )
    return st.session_state._http_client


class HTTPXError(Exception):
    """Custom exception with HTTP status code."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _handle_http_error(e: Exception, context: str = "Request") -> str:
    """Convert HTTP errors to user-friendly messages."""
    if isinstance(e, httpx.ConnectError):
        return "⚠️ Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng."
    elif isinstance(e, httpx.ConnectTimeout):
        return "⚠️ Kết nối quá hạn. Vui lòng thử lại sau."
    elif isinstance(e, httpx.ReadTimeout):
        return "⚠️ Yêu cầu quá thời gian chờ. Vui lòng thử lại với câu hỏi ngắn hơn."
    elif isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 429:
            return "⚠️ Quá nhiều yêu cầu. Vui lòng đợi một phút rồi thử lại."
        elif e.response.status_code == 503:
            return "⚠️ Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau."
        elif e.response.status_code == 500:
            return "⚠️ Lỗi máy chủ nội bộ. Vui lòng thử lại sau."
        elif e.response.status_code == 401:
            return "⚠️ Xác thực không thành công. Vui lòng kiểm tra API key."
        else:
            return f"⚠️ {context} thất bại (HTTP {e.response.status_code})."
    else:
        return f"⚠️ {context} thất bại: {str(e)}"


def _load_sessions() -> List[dict]:
    """Load session list with loading state and error handling."""
    try:
        client = _get_http_client()
        r = client.get(f"{SESSIONS_ENDPOINT}?limit=50")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.warning(_handle_http_error(e, "Tải danh sách chat"))
        return []
    except Exception as e:
        if "Không thể" in str(e) or "thất bại" in str(e):
            st.warning(str(e))
        return []


def _load_session(sid: str) -> Optional[dict]:
    try:
        client = _get_http_client()
        r = client.get(f"{SESSIONS_ENDPOINT}/{sid}")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(_handle_http_error(e, "Tải chat"))
        return None
    except Exception:
        return None


def _delete_session(sid: str) -> bool:
    try:
        client = _get_http_client()
        r = client.delete(f"{SESSIONS_ENDPOINT}/{sid}")
        r.raise_for_status()
        return True
    except Exception as e:
        st.error(_handle_http_error(e, "Xóa chat"))
        return False


def _submit_feedback(sid: str, idx: int, rating: int) -> bool:
    """Submit feedback with proper error handling."""
    try:
        client = _get_http_client()
        r = client.post(
            FEEDBACK_ENDPOINT,
            json={"session_id": sid, "message_index": idx, "rating": rating}
        )
        r.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 422:
            st.warning("⚠️ Dữ liệu phản hồi không hợp lệ.")
        else:
            st.error(_handle_http_error(e, "Gửi phản hồi"))
        return False
    except Exception as e:
        st.error(_handle_http_error(e, "Gửi phản hồi"))
        return False


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------

def _stream(query: str, sid: str, threshold: float):
    """Yield SSE events from backend with comprehensive error handling."""
    try:
        client = _get_http_client()
        with client.stream(
            "POST", CHAT_ENDPOINT,
            json={"query": query, "session_id": sid, "faq_threshold": threshold}
        ) as resp:
            # Handle HTTP errors
            if resp.status_code == 429:
                yield {"type": "response_complete", "text": "⚠️ Quá nhiều yêu cầu. Vui lòng đợi một phút rồi thử lại.", "documents": [], "source": "error", "stage": "complete"}
                return
            elif resp.status_code == 503:
                yield {"type": "response_complete", "text": "⚠️ Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.", "documents": [], "source": "error", "stage": "complete"}
                return
            elif resp.status_code == 401:
                yield {"type": "response_complete", "text": "⚠️ Xác thực không thành công. Vui lòng kiểm tra API key.", "documents": [], "source": "error", "stage": "complete"}
                return
            
            resp.raise_for_status()
            
            for line in resp.iter_lines():
                if not st.session_state.generating:
                    return
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    if raw:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            pass
                            
    except httpx.ConnectError:
        yield {"type": "response_complete", "text": "⚠️ Không thể kết nối backend. Vui lòng kiểm tra kết nối mạng.", "documents": [], "source": "error", "stage": "complete"}
    except httpx.ConnectTimeout:
        yield {"type": "response_complete", "text": "⚠️ Kết nối quá hạn. Vui lòng thử lại sau.", "documents": [], "source": "error", "stage": "complete"}
    except httpx.ReadTimeout:
        yield {"type": "response_complete", "text": "⚠️ Yêu cầu quá thời gian chờ. Vui lòng thử lại với câu hỏi ngắn hơn.", "documents": [], "source": "error", "stage": "complete"}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            yield {"type": "response_complete", "text": "⚠️ Dữ liệu gửi lên không hợp lệ. Vui lòng thử lại.", "documents": [], "source": "error", "stage": "complete"}
        else:
            yield {"type": "response_complete", "text": f"⚠️ Lỗi máy chủ (HTTP {exc.response.status_code}). Vui lòng thử lại sau.", "documents": [], "source": "error", "stage": "complete"}
    except Exception as exc:
        yield {"type": "response_complete", "text": f"⚠️ Lỗi không xác định: {exc}", "documents": [], "source": "error", "stage": "complete"}


# ---------------------------------------------------------------------------
# PDF / TXT export
# ---------------------------------------------------------------------------

def _export_pdf(messages: List[Dict], title: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, margin=72)
        styles = getSampleStyleSheet()

        # Try to register a Unicode font (Windows or Linux)
        font_ok = False
        if os.name == "nt":
            for name in ["arial.ttf", "arialuni.ttf", "times.ttf", "calibri.ttf"]:
                p = os.path.join(os.environ.get("WINDIR", ""), "Fonts", name)
                if os.path.exists(p):
                    pdfmetrics.registerFont(TTFont("UF", p))
                    font_ok = True
                    break
        if not font_ok:
            import glob, subprocess
            try:
                out = subprocess.run(["fc-list", ":lang=vi", "file"], capture_output=True, text=True, timeout=5)
                if out.returncode == 0 and out.stdout:
                    path = out.stdout.strip().split("\n")[0].split(":")[0]
                    pdfmetrics.registerFont(TTFont("UF", path))
                    font_ok = True
            except Exception:
                pass

        body_name = "VietBody"
        bold_name = "VietBold"
        if font_ok:
            styles.add(ParagraphStyle(name=body_name, parent=styles["Normal"], fontName="UF", fontSize=10.5, leading=14))
            styles.add(ParagraphStyle(name=bold_name, parent=styles["Normal"], fontName="UF", fontSize=10.5, leading=14))
        else:
            body_name = "Normal"
            bold_name = "Normal"  # <b> tag handles bold

        story = []
        story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))
        story.append(Paragraph(f"<i>{datetime.now():%d/%m/%Y %H:%M}</i>", styles["Normal"]))
        story.append(Spacer(1, 16))

        for m in messages:
            role = "Bạn" if m["role"] == "user" else "Trợ lý"
            txt = m["content"].replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(f"<b>{role}:</b>", styles[bold_name]))
            story.append(Paragraph(txt, styles[body_name]))
            if m.get("timestamp"):
                ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
                story.append(Paragraph(f"<i>{ts:%H:%M · %d/%m/%Y}</i>", styles[body_name]))
            story.append(Spacer(1, 8))

        doc.build(story)
        return buf.getvalue()
    except ImportError:
        st.warning("⚠️ Thiếu thư viện PDF, sẽ xuất file TXT thay thế.")
        return _export_txt(messages).encode("utf-8"), True  # Return tuple (data, is_fallback)
    except Exception as e:
        st.error(f"⚠️ Lỗi tạo PDF: {e}")
        return _export_txt(messages).encode("utf-8"), True
    
    return buf.getvalue(), False  # Success, no fallback


def _export_txt(messages: List[Dict]) -> str:
    lines = [f"EPR Assistant — {datetime.now():%d/%m/%Y %H:%M}\n{'='*60}"]
    for m in messages:
        role = "Bạn" if m["role"] == "user" else "Trợ lý"
        lines.append(f"\n{role}:")
        lines.append(m["content"])
        if m.get("timestamp"):
            ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
            lines.append(f"  [{ts:%H:%M}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Send message + stream response
# ---------------------------------------------------------------------------

def _send(query: str):
    # Prevent double submission: check if already generating
    if st.session_state.generating:
        return

    st.session_state.messages.append({"role": "user", "content": query, "timestamp": datetime.utcnow().isoformat() + "Z"})
    st.session_state.generating = True

    with st.chat_message("assistant"):
        status_box = st.empty()
        content_box = st.empty()
        stop_btn = st.button("⏹ Stop", type="primary", key="stop_btn")

        text = ""
        source = ""
        docs = []

        for ev in _stream(query, st.session_state.session_id, st.session_state.get("faq_threshold", 0.75)):
            if stop_btn:
                st.session_state.generating = False
                break
            t = ev.get("type")
            if t == "status":
                status_box.caption(ev.get("message", ""))
            elif t == "response_chunk":
                text += ev.get("chunk", "")
                content_box.markdown(text + "▌")
            elif t == "response_complete":
                text = ev.get("text", text)
                source = ev.get("source", "")
                docs = ev.get("documents", [])
                status_box.empty()
                content_box.markdown(text)
                break

        st.session_state.generating = False

        # Meta line: source + doc count
        meta = ""
        if source:
            labels = {"faq": "FAQ", "legal": "Văn bản", "chitchat": "Chat", "web_search": "Web", "cache": "Cache"}
            meta = labels.get(source, source)
        if docs:
            meta += f"  ·  {len(docs)} tài liệu" if meta else f"{len(docs)} tài liệu"
        if meta:
            st.markdown(f'<div class="msg-meta">{meta}</div>', unsafe_allow_html=True)

        # Doc expander
        if docs:
            with st.expander("Tài liệu tham khảo"):
                for d in docs:
                    meta_d = d.get("metadata", {})
                    parts = []
                    if meta_d.get("Dieu"):
                        parts.append(f"Điều {meta_d['Dieu']}")
                    if meta_d.get("Chuong"):
                        parts.append(f"Chương {meta_d['Chuong']}")
                    st.markdown(f"**{' | '.join(parts) or 'Tài liệu'}**")
                    st.markdown(f"> {d.get('page_content', '')[:250]}…")

    st.session_state.messages.append({"role": "assistant", "content": text, "timestamp": datetime.utcnow().isoformat() + "Z"})
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _sidebar():
    with st.sidebar:
        if st.button("＋ New chat", use_container_width=True, type="primary"):
            _reset_chat()

        st.markdown("### Chats")

        # Refresh list
        if "conv_loaded" not in st.session_state or st.session_state.get("_refresh_convos"):
            st.session_state.conversations = _load_sessions()
            st.session_state.conv_loaded = True
            st.session_state._refresh_convos = False

        for c in st.session_state.conversations[:30]:
            active = c["id"] == st.session_state.session_id
            title = (c.get("title") or "New chat")[:36]
            cls = "conv-item active" if active else "conv-item"
            if st.button(title, key=f"c_{c['id']}", use_container_width=True):
                detail = _load_session(c["id"])
                if detail:
                    st.session_state.session_id = detail["id"]
                    st.session_state.messages = detail.get("messages", [])
                    st.session_state._refresh_convos = True
                    st.rerun()

        st.divider()

        # Export
        if st.session_state.messages:
            conv_title = "EPR Chat"
            for c in st.session_state.conversations:
                if c["id"] == st.session_state.session_id:
                    conv_title = c.get("title", "EPR Chat")[:36]
                    break

            fmt = st.selectbox("Export", options=["", "📄 PDF", "📝 TXT"], index=0, label_visibility="collapsed")
            if fmt == "📄 PDF":
                pdf_data, is_fallback = _export_pdf(st.session_state.messages, conv_title)
                if is_fallback:
                    # User was already warned in _export_pdf
                    file_name = f"{conv_title}.txt"
                    mime = "text/plain"
                else:
                    file_name = f"{conv_title}.pdf"
                    mime = "application/pdf"
                st.download_button("Tải PDF", data=BytesIO(pdf_data) if not is_fallback else pdf_data,
                                   file_name=file_name, mime=mime, use_container_width=True)
            elif fmt == "📝 TXT":
                st.download_button("Tải TXT", data=_export_txt(st.session_state.messages).encode("utf-8"),
                                   file_name=f"{conv_title}.txt", mime="text/plain", use_container_width=True)

        # Settings
        st.caption("Settings")
        st.session_state.faq_threshold = st.slider(
            "FAQ threshold", 0.5, 1.0, st.session_state.get("faq_threshold", 0.75), 0.05,
            label_visibility="collapsed",
        )


# ---------------------------------------------------------------------------
# Message renderer with actions
# ---------------------------------------------------------------------------

def _render_messages():
    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

            # Timestamp
            if m.get("timestamp"):
                try:
                    ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
                    st.markdown(f'<div class="msg-meta">{ts:%H:%M · %d/%m/%Y}</div>', unsafe_allow_html=True)
                except Exception:
                    pass

            # Action row (assistant only)
            if m["role"] == "assistant":
                c1, c2, c3, c4 = st.columns([1, 1, 1, 4])
                with c1:
                    if st.button("📋", key=f"cp{i}", help="Copy"):
                        st.toast("Đã copy", icon="✅")
                        st.session_state[f"_clip_{i}"] = m["content"]
                with c2:
                    if st.button("👍", key=f"up{i}", help="Good"):
                        if _submit_feedback(st.session_state.session_id, i, 2):
                            st.toast("Cảm ơn!", icon="👍")
                        else:
                            st.toast("Không thể gửi phản hồi", icon="❌")
                with c3:
                    if st.button("👎", key=f"dn{i}", help="Bad"):
                        if _submit_feedback(st.session_state.session_id, i, 1):
                            st.toast("Đã ghi nhận", icon="👎")
                        else:
                            st.toast("Không thể gửi phản hồi", icon="❌")
                with c4:
                    if i == len(st.session_state.messages) - 1 and st.button("🔄", key=f"rg{i}", help="Regenerate"):
                        # Re-send the last user message
                        for j in range(i - 1, -1, -1):
                            if st.session_state.messages[j]["role"] == "user":
                                st.session_state.messages = st.session_state.messages[:i]  # trim assistant response
                                _send(st.session_state.messages[j]["content"])
                                return


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def _onboarding():
    st.markdown("### 👋 Xin chào — Tôi có thể giúp gì?")
    st.caption("Trợ lý AI về Luật EPR & Nghị định 08/2022/NĐ-CP")
    st.markdown("")

    examples = [
        "Nghị định 08/2022 là gì?",
        "Điều 77 quy định gì về tái chế?",
        "Tỷ lệ tái chế bao bì nhựa PE/PP?",
        "Nghĩa vụ của nhà sản xuất khi làm EPR?",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex}", use_container_width=True):
            _send(ex)
            return

    # Also accept input at onboarding
    user_input = st.chat_input("Nhập câu hỏi…")
    if user_input:
        _send(user_input)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_init()
_sidebar()

if st.session_state.messages:
    _render_messages()

    # Regenerate trigger
    if st.session_state.get("_regen_query"):
        q = st.session_state.pop("_regen_query")
        _send(q)
else:
    _onboarding()

# Chat input at bottom (always visible)
if not st.session_state.generating:
    user_input = st.chat_input("Nhập câu hỏi…", key="chat_input_main")
    if user_input:
        _send(user_input)
