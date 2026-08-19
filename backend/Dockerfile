# NOTE: the build context for this image is the REPO ROOT (the CI in
# .github/workflows/main.yml sets context: ./), so paths below are relative
# to the root. The root .dockerignore keeps the build context small.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
