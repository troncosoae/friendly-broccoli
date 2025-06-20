# services/team_members_service/Dockerfile
FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY .env .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
