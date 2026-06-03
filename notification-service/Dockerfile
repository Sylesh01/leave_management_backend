FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY notification-service ./notification-service

ENV PYTHONPATH=/app
WORKDIR /app/notification-service

EXPOSE 8004

CMD ["python", "app.py"]
