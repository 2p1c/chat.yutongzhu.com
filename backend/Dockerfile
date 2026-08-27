# Build context is the REPO ROOT (see docker-compose.yml: build.context),
# so backend/ and frontend/ keep their on-disk relative layout: main.py
# resolves the frontend as `parent.parent / "frontend"`.
FROM python:3.12-slim

WORKDIR /srv

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY backend/ backend/
COPY frontend/ frontend/

WORKDIR /srv/backend
EXPOSE 8000

# init_db.py is idempotent (CREATE ... IF NOT EXISTS), safe to run on every start.
CMD ["sh", "-c", "python init_db.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
