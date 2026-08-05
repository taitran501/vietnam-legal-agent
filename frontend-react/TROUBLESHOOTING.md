# 🔧 Troubleshooting Guide

## ⚠️ HTTP 502: Bad Gateway

### Cause
The Vite development proxy cannot connect to the backend server.

### Solution

1. **Make sure the backend is running:**
   ```bash
   # From project root
   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Verify backend is accessible:**
   ```bash
   curl http://localhost:8000/health
   ```
   Should return: `{"status":"ok","qdrant":"ok","redis":"ok","openai":"ok"}`

3. **Check Vite proxy logs:**
   In the terminal running `npm run dev`, you should see:
   ```
   Sending Request to the Target: POST /api/v1/chat
   Received Response from the Target: 200 /api/v1/chat
   ```

4. **If backend is on a different port:**
   Update `frontend-react/.env`:
   ```
   VITE_API_BASE_URL=http://localhost:YOUR_PORT
   ```

5. **Restart Vite after changing config:**
   ```bash
   npm run dev
   ```

## ⚠️ CORS Errors

If you see CORS errors, the backend is already configured to allow `http://localhost:3000`.
Make sure `ALLOWED_ORIGINS` in backend `.env` includes `http://localhost:3000`.

## ⚠️ SSE Streaming Not Working

The Vite proxy should handle SSE automatically. If not:
1. Check that `changeOrigin: true` is set in `vite.config.ts`
2. Try accessing backend directly: set `VITE_API_BASE_URL=http://localhost:8000`

## Quick Test

```bash
# Test backend health
curl http://localhost:8000/health

# Test chat endpoint
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"test","session_id":"test-123"}'
```
