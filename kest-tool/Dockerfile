FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN groupadd --gid 10001 kest && useradd --uid 10001 --gid kest --create-home kest \
    && mkdir -p /data/kest && chown -R kest:kest /data/kest
USER kest
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--server.enableCORS=true", "--server.enableXsrfProtection=true"]
