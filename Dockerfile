FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/uploads

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn mas_app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
