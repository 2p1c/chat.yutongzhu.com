FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

EXPOSE 8000

# init_db.py is idempotent (CREATE ... IF NOT EXISTS), safe to run on every start.
CMD ["sh", "-c", "python init_db.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
