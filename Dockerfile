# syntax=docker/dockerfile:1.7
# Single image: FastAPI API + built dashboard served from the same origin.

FROM node:22-alpine AS web
WORKDIR /src
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/typescript-sdk/package.json packages/typescript-sdk/
COPY apps/web/package.json apps/web/
COPY examples/typescript-integration/package.json examples/typescript-integration/
RUN npm ci --no-audit --no-fund
COPY packages/typescript-sdk packages/typescript-sdk
COPY apps/web apps/web
RUN npm run build -w @waltrix/sdk && npm run build -w @waltrix/web

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 waltrix
WORKDIR /app
COPY packages/ledger-core packages/ledger-core
COPY apps/api apps/api
RUN pip install ./packages/ledger-core ./apps/api
COPY --from=web /src/apps/web/dist /app/web
ENV WALTRIX_WEB_DIST=/app/web WALTRIX_ENVIRONMENT=production
USER waltrix
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/readyz').status==200 else 1)"
CMD ["uvicorn", "waltrix_api.asgi:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--proxy-headers"]
