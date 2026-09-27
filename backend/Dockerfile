FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

EXPOSE 8000

# init_db.py is idempotent (CREATE ... IF NOT EXISTS), safe to run on every start.
# Each worker is a separate process with its own DB pool: keep workers x DB_POOL_MAX_SIZE < PG max_connections.
CMD ["sh", "-c", "python init_db.py && uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
