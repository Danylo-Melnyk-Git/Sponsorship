FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements-server.txt ./
COPY requirements-pdf.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt -r requirements-pdf.txt && useradd --uid 10001 --create-home sponsor && mkdir -p /data/research /data/auth /data/jobs && chown -R sponsor:sponsor /data
COPY apps ./apps
COPY packages ./packages
COPY agents ./agents
COPY research/poisk-i-podbor ./research/poisk-i-podbor
COPY sponsor.py deploy.py ./
USER 10001:10001
EXPOSE 8080
CMD ["python","-m","uvicorn","apps.api.hosted:create_app","--factory","--host","0.0.0.0","--port","8080","--workers","1","--limit-concurrency","32","--no-access-log","--no-proxy-headers"]
