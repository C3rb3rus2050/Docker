FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/kest-tool/src
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
COPY kest-tool/requirements.txt kest-tool/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY kest-tool/ ./kest-tool/
COPY backend/ ./backend/
COPY --from=web /web/dist ./frontend/dist
RUN groupadd --gid 10001 kest && useradd --uid 10001 --gid kest --create-home kest \
    && mkdir -p /data/kest && chown -R kest:kest /data/kest
USER kest
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
