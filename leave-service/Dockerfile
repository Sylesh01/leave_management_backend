FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY leave-service ./leave-service

ENV PYTHONPATH=/app
WORKDIR /app/leave-service

EXPOSE 8003

CMD ["python", "app.py"]
