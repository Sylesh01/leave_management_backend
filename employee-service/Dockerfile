FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY employee-service ./employee-service

ENV PYTHONPATH=/app
WORKDIR /app/employee-service

EXPOSE 8002

CMD ["python", "app.py"]
