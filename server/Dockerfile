# Built to be used with docker-compose from root
# Dockerfile
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install uvicorn
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py database.py models.py .

ARG APP_PORT=8000
ENV APP_PORT=${APP_PORT}
EXPOSE ${APP_PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${APP_PORT}"]