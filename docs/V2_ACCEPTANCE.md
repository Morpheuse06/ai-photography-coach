# V2 Local Acceptance Checklist

## Scope

V2 keeps the V1 single-photo coaching flow and adds a fixed RAG pipeline:
image-grounded retrieval planning, dense embedding search, Chroma persistence,
text reranking, and knowledge-grounded report generation. It does not add user
accounts, history, a database, automatic editing, or an open-ended agent graph.

## Automated checks

- [x] `/api/v2/analyze` reuses V1 image validation and error responses.
- [x] Retrieval planning covers all five report dimensions.
- [x] Chroma validates corpus, embedding model, and dimension metadata.
- [x] Candidate retrieval and final reranking scores remain separately traceable.
- [x] Reranking preserves all five dimensions in the bounded final context.
- [x] RAG services initialize once during the FastAPI application lifespan.
- [x] Tests can inject isolated settings and never require real model calls.
- [x] V1 responses remain compatible with absent retrieval metadata.
- [x] V2 responses expose non-secret retrieval metadata.
- [x] The React client submits photos to `/api/v2/analyze`.
- [x] Backend unit and HTTP tests pass: 165 tests.
- [x] Frontend lint, TypeScript build, and component tests pass: 9 tests.

## Browser smoke test

- [x] The Vite client reaches FastAPI through the development proxy.
- [x] File selection, preview, intent, and privacy consent work together.
- [x] Duplicate submission is disabled while analysis is running.
- [x] A Mock V2 request renders five dimensions, three actions, and one exercise.
- [x] Knowledge source, Embedding, Reranker, and hit count are visible.
- [x] No browser console errors were recorded.
- [x] No horizontal overflow at 375 px, 768 px, or 1280 px.

## Real-provider evidence

- [x] `qwen3-rerank` completed a text-only smoke test with relevant passages first.
- [x] One authorized photo completed the entire DashScope V2 pipeline.
- [x] The real run covered all five dimensions and returned six knowledge chunks.
- [ ] Run a small cross-category regression set after explicit photo-send approval.

## Local release decision

The Mock-powered local V2 is accepted. A real-provider local release remains
pending only on the approved cross-category regression run. Public internet
deployment would additionally require application-owned rate limiting, cost
controls, deployment timeout configuration, and explicit client shutdown.
