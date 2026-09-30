FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests/fixtures/api/audd_success.body ./tests/fixtures/api/audd_success.body

ENV BLAZAM_DATA_DIR=/data BLAZAM_DB_PATH=/data/blazam.sqlite3 PYTHONUNBUFFERED=1
VOLUME ["/data"]
# PORT is set by hosts such as Render; --proxy-headers makes preview_url come out as https://
# behind the host's TLS proxy instead of http:// (which browsers block as mixed content)
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://localhost:{os.getenv('PORT','8000')}/api/health\")"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
