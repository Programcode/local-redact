# local-redact web UI

Next.js frontend for the local redaction app. It talks only to the FastAPI
server in `src/local_redact/server.py` (`127.0.0.1:8420`). There is no
separate deployment target: production is a static export served by that
same process.

See the repository README for install, privacy notes, and how to run it.

```bash
pnpm install
pnpm dev    # http://localhost:3000, proxies /api to :8420
pnpm lint
pnpm build  # static export in web/out, served by local-redact-web
```
