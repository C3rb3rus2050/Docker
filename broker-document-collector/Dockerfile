FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DISPLAY=:99
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xvfb fluxbox x11vnc novnc websockify && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install chromium
COPY . .
RUN chmod +x /app/docker-entrypoint.sh
EXPOSE 8765 6080
ENTRYPOINT ["/app/docker-entrypoint.sh"]
