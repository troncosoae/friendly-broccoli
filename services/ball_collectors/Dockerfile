# services/ball_carriers_service/Dockerfile
FROM python:3.11-slim-bookworm

# This line is crucial for 'curl' to be available for the healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY .env .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
