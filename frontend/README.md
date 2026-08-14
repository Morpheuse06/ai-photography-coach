# AI Photography Coach Frontend

React + TypeScript single-page client for the AI Photography Coach V2 API.

```bash
npm install
npm run dev
```

Development requests to `/api` and `/health` are proxied to FastAPI at
`http://127.0.0.1:8000`.

Photo analysis is submitted to `/api/v2/analyze`, which runs the backend RAG
pipeline. The browser never receives API keys or calls model providers directly.
