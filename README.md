# EPR Chatbot — Trợ Lý Pháp Lý AI cho Luật Trách Nhiệm Mở Rộng Của Nhà Sản Xuất

**EPR Chatbot** là một hệ thống trợ lý pháp lý AI chuyên biệt trả lời các câu hỏi về Luật Bảo vệ Môi trường và Nghị định 08/2022/NĐ-CP (Trách Nhiệm Tái Chế của Nhà Sản Xuất) tại Việt Nam.

## 🎯 Mục Đích Dự Án

- **Trả lời chính xác** các câu hỏi pháp lý về EPR dựa trên dữ liệu từ văn bản luật chính thức
- **Tối ưu hóa** hiệu suất truy xuất và trả lời thông qua caching thông minh và semantic search
- **Đảm bảo độ tin cậy** bằng cách trích dẫn rõ ràng các điều luật liên quan
- **Hỗ trợ thương mại hóa** với kiến trúc scalable và đầy đủ evaluation framework

## 📌 Results Overview (E2E Eval + Performance)

- **Routing accuracy**: **33/33 (100%)**
- **Keyword hit rate**: **avg ~0.924**, full match **20/24** case có kỳ vọng từ khóa
- **LLM-as-judge (0–5)**: Faithfulness **~3.04**, Relevance **~3.96**, Completeness **~3.70**
- **Retrieval Accuracy**: **0.813/1.0** (P@1: 92%, NDCG@3: 97.2%)
- **User-Perceived Latency**: Avg 1.65s TTFT, Cache Hit: 454ms
- **Success Rate**: 92% (23/25 queries < 4s)


## 🏗️ Kiến Trúc Hệ Thống

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                   FastAPI Backend (port 8000)                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Optimized RAG Pipeline (Async)                 │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  1. Semantic Cache (Redis exact + Qdrant semantic) │ │  │
│  │  ├─────────────────────────────────────────────────────┤ │  │
│  │  │  2. 2-way Router: chitchat | substantive           │ │  │
│  │  ├─────────────────────────────────────────────────────┤ │  │
│  │  │  3. Conditional Rewrite (only ambiguous follow-up)  │ │  │
│  │  ├─────────────────────────────────────────────────────┤ │  │
│  │  │  4. Strict FAQ semantic cache                       │ │  │
│  │  ├─────────────────────────────────────────────────────┤ │  │
│  │  │  5. Deep Legal Retrieval (dense + lexical + rerank)│ │  │
│  │  ├─────────────────────────────────────────────────────┤ │  │
│  │  │  6. Relevance Gate -> Legal Answer or Web Fallback │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────┬──────────────┬──────────────────┬───────────┬──────────┘
         │              │                  │           │
    ┌────▼───┐  ┌──────▼──────┐   ┌───────▼────┐  ┌───▼───────┐
    │ Redis  │  │  Qdrant     │   │   OpenAI   │  │ LangSmith │
    │ Cache  │  │  Vector DB  │   │   API      │  │ Tracing   │
    └────────┘  └─────────────┘   └────────────┘  └───────────┘
```

### Flow Overview (Current Runtime)

1. Exact/semantic cache lookup (`semantic_cache.lookup`)  
2. Router (`chitchat` vs `epr_query`)  
3. Conditional rewrite (only when query is context-dependent follow-up)  
4. Strict FAQ semantic cache:
   - only return FAQ when score high + margin strong + query not legal-specific  
5. Legal retrieval (hybrid):
   - dense cosine (Qdrant)
   - lexical BM25-style retrieval
   - explicit `Điều X` boost (if present)
   - fast rerank over merged candidates  
6. Relevance gate:
   - pass -> stream legal answer
   - fail/miss -> EPR-scoped web fallback (domain guard)  
7. Cache substantive final answer (FAQ/legal/web). Chitchat is not cached.

## 🛠️ Tech Stack

### Backend
- **Framework**: FastAPI 0.115.0
- **LLM Orchestration**: LangChain 0.3.7 + LangChain Core 0.3.19
- **Vector Database**: Qdrant Cloud (eu-central-1)
- **Caching**: Redis + redis-py 5.1.1
- **LLM Models**:
  - `gpt-4o-mini` — routing (2-way), question rewriting, relevance gate
  - `gpt-3.5-turbo` — chitchat, FAQ generation, legal generation (stream)
  - `text-embedding-3-small` — embedding (1536 chiều)

### Frontend
- **Framework**: React 18 + TypeScript + Vite 5
- **Styling**: Tailwind CSS

### Evaluation
- **Test Framework**: Custom pytest-based eval runner
- **Metrics**: Routing accuracy, keyword presence, latency, LLM-as-judge (faithfulness, relevance, completeness)

### Infrastructure
- **Containers**: Docker (Redis, uvicorn services)
- **LLM Observability**: LangSmith (tracing)
- **Web Search**: Tavily API (fallback)

## 📊 Dữ Liệu

### FAQ Collection (49 entries)
- Câu hỏi thường gặp về EPR
- Được lưu trữ tại: `data/faq.json`
- Tự động index trên Qdrant khi backend khởi động

### Law Collection (178 articles)
1. **Nghị định 08/2022/NĐ-CP** (169 articles)
   - Các điều quy định chi tiết về trách nhiệm tái chế
   - Cấu trúc phân cấp: Chương → Điều → Mục
   - Được lưu trữ tại: `data/law.json`

2. **Phụ lục XXII** (9 entries - mới thêm)
   - Tỷ lệ tái chế bắt buộc theo loại sản phẩm/bao bì
   - Quy cách tái chế bắt buộc chi tiết
   - Sản phẩm bao gồm:
     - Ắc quy & pin sạc (61-65%)
     - Dầu nhớt (100%)
     - Săm lốp (47%)
     - Bao bì nhựa PE/PP/PET (22-30%)
     - Sản phẩm điện-điện tử (70%)
     - Phương tiện giao thông (95%)

### Indexing Workflow
```bash
python -m scripts.build_index
```
Quy trình:
1. Load articles từ `data/law.json`
2. Summarize từng article bằng gpt-3.5-turbo (batch = 5)
3. Embed summaries bằng text-embedding-3-small
4. Upsert vào Qdrant `law_collection` (178 vectors)
5. Tạo payload indexes cho Dieu, Chuong, Muc (structured filters)

## 🚀 Cách Chạy Dự Án

### Quick Start (Recommended)

**Yêu cầu**: Docker + Docker Compose

```bash
cd "d:\UIT\Nam 4\Ki 2\epr_chatbot"

# 1. Chuẩn bị .env
cp .env.example .env
# Sau đó chỉnh sửa .env với API keys của bạn

# 2. Khởi động Redis
docker-compose up -d redis

# 3. Cài đặt dependencies backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements/backend.txt

# 4. Cài đặt dependencies frontend React
cd frontend-react
npm install
cd ..

# 5. Index luật (lần đầu)
python -m scripts.build_index

# 6. Chạy backend (Terminal 1)
$env:PYTHONPATH = "d:\UIT\Nam 4\Ki 2\epr_chatbot"
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 7. Chạy frontend React (Terminal 2)
cd frontend-react
npm run dev
# Mở: http://localhost:3000
```

---

### Step-by-step Setup (Alternative)

#### 1. Chuẩn Bị Môi Trường

```bash
cd "d:\UIT\Nam 4\Ki 2\epr_chatbot"

# Tạo virtual environment
python -m venv venv
venv\Scripts\activate

# Cài đặt dependencies backend
pip install -r requirements/backend.txt
```

#### 2. Cấu Hình `.env`

Sao chép từ template:
```bash
cp .env.example .env
```

Sau đó chỉnh sửa `.env` với API keys của bạn:
```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Qdrant Cloud
USE_QDRANT_CLOUD=true
QDRANT_CLOUD_URL=https://...eu-central-1-0.aws.cloud.qdrant.io
QDRANT_API_KEY=...

# Redis
REDIS_URL=redis://localhost:6379/0

# LangSmith (optional tracing)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=...

# Tavily (optional web search)
TAVILY_API_KEY=...

# Pipeline feature flags (minimal, reversible controls)
ENABLE_QUERY_REWRITE=true
ENABLE_LLM_ROUTER_FALLBACK=false
ENABLE_STRICT_FAQ_GATE=true
ENABLE_RELEVANCE_GATE=true
ENABLE_WEB_FALLBACK=true
WEB_FALLBACK_TIMEOUT_SECONDS=6
ENABLE_FOLLOWUP_SUGGESTIONS=false
ENABLE_LEGAL_EVIDENCE_GUARDRAIL=true
LEGAL_CONTEXT_MAX_DOCS=3
LEGAL_CONTEXT_MAX_TOKENS_PER_DOC=500
MIN_LEGAL_EVIDENCE_DOCS=1
MIN_LEGAL_EVIDENCE_CHARS=160

# Index contract validation
INDEX_CONTRACT_STRICT=true
```

**Low-latency profile (ưu tiên tốc độ phản hồi):**
```bash
ENABLE_LLM_ROUTER_FALLBACK=false
ENABLE_RELEVANCE_GATE=false
ENABLE_WEB_FALLBACK=false
ENABLE_FOLLOWUP_SUGGESTIONS=false
LEGAL_CONTEXT_MAX_DOCS=2
LEGAL_CONTEXT_MAX_TOKENS_PER_DOC=400
```

#### 3. Khởi Động Redis

**Option A: Docker Compose (Recommended)**
```bash
# Khởi động Redis từ docker-compose.yml
docker-compose up -d redis

# Kiểm tra Redis đang chạy
docker-compose logs redis
```

**Option B: Standalone Docker**
```bash
docker run -d --name epr_redis -p 6379:6379 redis:7.0-alpine
```

**Option C: Local Installation** (Windows)
```bash
# Cài Redis nếu chưa có
choco install redis-64
# hoặc WSL: sudo apt-get install redis-server
```

#### 4. Khởi Động Backend

```bash
# Set Python path và chạy backend
$env:PYTHONPATH = (Get-Location).Path
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Kiểm tra health check ở: http://localhost:8000/api/v1/health

#### 5. Khởi Động Frontend React

**Cửa sổ terminal mới:**
```bash
# Cần Node.js 18+ (hoặc 20+)
cd frontend-react
npm install
npm run dev
```

Truy cập ở: http://localhost:3000

---

## 🧪 Evaluation Framework

### Tập Test
- **33 test cases** đã được định nghĩa trong `tests/eval/test_cases.json`
- Phân nhóm: 5 chitchat, 10 FAQ, 10 legal, 5 edge cases, 3 web_search

### Chạy Eval

```bash
# Eval không dùng LLM (nhanh)
python -m tests.eval.run_eval --no-llm-eval --verbose

# Eval đầy đủ (với LLM judge)
python -m tests.eval.run_eval --verbose

# LLM-as-judge (Faithfulness/Relevance/Completeness) nên chạy với --no-cache
# để tránh cache hit làm documents rỗng (Faithfulness không chấm chính xác).
python -m tests.eval.run_eval --no-cache --output tests/eval/results_with_llm_judge.json

# Quality gate (fail CI/release nếu chất lượng dưới ngưỡng)
python -m tests.eval.run_eval --no-cache --quality-gate

# Chỉ eval FAQ category
python -m tests.eval.run_eval --category faq --output results_faq.json

# Thu gọn các file tests/eval/results_*.json đã lưu (bỏ final_text + lý do rỗng) để repo nhẹ hơn
python -m tests.eval.compact_stored_results
```

### Metrics Đánh Giá
- **Routing Accuracy**: % câu hỏi được route đúng (chitchat vs vectorstore)
- **Keyword Hit Rate**: % từ khóa kỳ vọng có trong trả lời
- **Latency**:
  - Chitchat: ~3-5s (gpt-3.5-turbo)
  - FAQ: ~4-6s (embedding + retrieval)
  - Legal: ~6-16s (query construction + legal generation)
- **LLM Scores** (Faithfulness, Relevance, Completeness): 0-5 (gpt-4o-mini judge)

## 📁 Cấu Trúc Thư Mục

```
epr_chatbot/
├── backend/
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Settings (Qdrant, Redis, OpenAI)
│   ├── core/
│   │   ├── pipeline.py            # Main RAG async generator
│   │   ├── retrieval.py           # FAQ strict cache + legal retrieval entrypoint
│   │   ├── ensemble_retrieval.py  # Hybrid legal retrieval (dense + lexical + rerank)
│   │   ├── generation.py          # Answer generation + streaming
│   │   ├── router.py              # Chitchat vs substantive routing
│   │   ├── rewriter.py            # Question rewriting
│   │   └── llm_instances.py       # LLM singletons
│   ├── api/
│   │   └── routes/
│   │       ├── health.py          # Health check endpoint
│   │       └── chat.py            # /chat endpoint (SSE)
│   ├── cache/
│   │   └── semantic_cache.py      # 2-layer cache implementation
│   └── memory/
│       └── session_store.py       # Chat history (Redis)
├── frontend-react/
│   ├── src/                       # React source code
│   └── package.json               # Frontend scripts/dependencies
├── scripts/
│   ├── build_index.py             # Offline indexing script
│   └── add_phuluc_xxii.py         # Data augmentation script
│   └── eda_law.py                 # EDA on law.json length/tokens (chunking hints)
├── tests/
│   └── eval/
│       ├── test_cases.json        # Golden test dataset
│       ├── evaluators.py          # LLM-as-judge implementation
│       ├── run_eval.py            # CLI eval runner
│       ├── compact_stored_results.py  # Thu gọn results_*.json đã commit
│       └── results_*.json         # Eval results (đã compact, không có final_text)
├── data/
│   ├── faq.json                   # FAQ dataset (49 entries)
│   └── law.json                   # Legal articles (178 entries)
├── requirements/
│   ├── backend.txt               # Backend dependencies
│   └── frontend.txt              # Frontend dependencies
├── .env                          # Environment variables (gitignore)
├── .env.example                  # Template cho .env
├── docker-compose.yml            # Docker Compose config
├── Dockerfile.backend            # Backend container
├── Dockerfile.frontend           # Frontend container
└── README.md                      # This file
```

## 📈 Kết Quả Đánh Giá Mới Nhất (E2E + LLM-as-judge)

Tổng hợp từ các file kết quả (đã bỏ bản snapshot trùng `results_e2e_v*`, `*_final`, v.v.):
- `tests/eval/results_e2e.json` — E2E baseline
- `tests/eval/results_llm_judge_full.json` — full run có LLM judge
- `tests/eval/results_chitchat_routing.json`
- `tests/eval/results_llm_judge_faq.json`
- `tests/eval/results_llm_judge_legal.json`
- `tests/eval/results_llm_judge_edge.json`
- `tests/eval/results_llm_judge_web_search.json`
- (tuỳ chọn) `results_llm_judge_sample.json`, `results_llm_judge_smoke_3.json`

Các file `results_*.json` trong repo đã qua `python -m tests.eval.compact_stored_results` (không lưu `final_text`; cần full text thì chạy lại `run_eval --output ...`).

### Routing + Keyword

| Metric | Kết Quả |
|--------|--------:|
| **Routing Accuracy (TOTAL)** | **33/33 (100%)** |
| **Keyword presence** | **avg hit rate ~0.924** |
| **Full keyword match** | **20/24 case** (>= 100% expected keywords) |

### LLM-as-judge (scale 0–5)

Tính trung bình trên các case có score dạng số:
- **Faithfulness (avg)**: ~**3.04/5**
- **Relevance (avg)**: ~**3.96/5**
- **Completeness (avg)**: ~**3.70/5**

Ghi chú: nhánh `web_search` trả `documents=[]` nên faithfulness có xu hướng thấp (judge không có tài liệu để đối chiếu).
Nếu loại `web_search` khỏi phần faithfulness/relevance/completeness:
- **Faithfulness (avg)**: ~**3.42/5**
- **Relevance (avg)**: ~**4.33/5**
- **Completeness (avg)**: ~**3.96/5**

## 🔧 Phiên Bản Python & Dependencies Quan Trọng

```
Python: 3.10.0 (or 3.9+)
FastAPI: 0.115.0
Uvicorn: 0.30.6
LangChain: 0.3.7
LangChain-OpenAI: 0.2.9
Qdrant-client: >=1.12.0,<2.0.0 (⚠️ MUST stay at 1.12.1+ — 1.17.0 has Python 3.10 incompatibility)
OpenAI: >=1.50.0,<2.0.0
Redis: 5.3 (Docker image)
Frontend React: Xem `frontend-react/package.json`
```

Xem chi tiết tại:
- `requirements/backend.txt` — Backend dependencies
- `frontend-react/package.json` — Frontend dependencies

## 🐛 Known Issues & Limitations

1. **Data Gaps**
   - FAQ chỉ có 49 entries → cần mở rộng
   - Phụ lục XXII mới thêm có 9 entries tóm tắt → cần full annotated table

2. **LangChain Deprecation Warnings** (cosmetic)
   - `QdrantTranslator` import từ `langchain.retrievers.self_query` (deprecated)
   - Lời khuyên: upgrade import path, nhưng hiện tại hoạt động bình thường

3. **CORS Policy** 
   - Backend: `allow_origins=["*"]` → cần tighten cho production

4. **Qdrant Query Constructor Limitations**
   - Long OR queries (3+ clauses) overflow Qdrant path parser → fallback to semantic search

## 🚴 Performance Optimization Tips

1. **Semantic Cache Tuning**
   - `semantic_cache_threshold=0.95` — cosine similarity threshold
   - Tăng threshold → stricter matches, ít false positives
   - Giảm threshold → more cache hits, more false matches

2. **FAQ Retrieval**
   - `faq_score_threshold=0.75` — semantic similarity threshold
   - `faq_keyword_boost=0.3` — weight cho keyword matching

3. **Legal Retrieval**
   - `max_retrieval_docs=5` — số docs max lấy từ Qdrant
   - Self-query constructor có timeout 30s → điều chỉnh qua `request_timeout` ở llm_instances

## 🧩 Law EDA & Chunking Hints

Chạy EDA trên `data/law.json` bằng `python -m scripts.eda_law` để hiểu độ dài phân bố (characters/tokens) và đưa ra gợi ý chunking.

Thống kê trên dataset hiện tại:
- Records: `178`
- `law.json` file size: `790,131 bytes`
- Token model (tiktoken): `text-embedding-3-small`

Phân bố tokens (mỗi `article`):
- p50: `902` tokens
- p75: `1646.2` tokens
- p90: `3873.0` tokens
- p95: `5838.0` tokens
- p99: `7390.5` tokens

Gợi ý chunking (theo ngưỡng tokens, với giả định “1 article = 1 chunk”):
- Articles có tokens `> 512`: `126` (`70.8%`)
- Articles có tokens `> 1024`: `78` (`43.8%`)
- Articles có tokens `> 2048`: `36` (`20.2%`)
- Articles có tokens `> 4096`: `15` (`8.4%`)

## 📚 Tài Liệu Thêm

- **Docker Deployment** — Xem `docker-compose.yml` + `Dockerfile.backend` / `Dockerfile.frontend`
- **Backend Configuration** — Xem `backend/config.py` để hiểu tất cả cài đặt có sẵn
- **API Endpoints** — Xem `backend/api/routes/chat.py` (main chat endpoint) và `health.py` (health check)
- **Evaluation Details** — Xem `tests/eval/run_eval.py` để hiểu eval framework


## 📄 License

Chưa định nghĩa. Nếu bạn có LICENSE cụ thể (MIT/Apache-2.0/GPL-3.0), vui lòng thêm vào repo.

