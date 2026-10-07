FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# tzdata: richtige Ortszeit (die Uhr der Thermostate wird damit gestellt)
# gcc: nur für Plattformen ohne fertige Python-Pakete (z. B. ältere Raspberry Pi), wird danach entfernt
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata gcc libc6-dev \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY *.py ./
COPY frontend ./frontend

VOLUME /app/data
EXPOSE 8099
CMD ["python", "bluetooth2mqtt.py", "--data", "/app/data"]
