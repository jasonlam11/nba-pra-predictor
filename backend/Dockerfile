# Serving image. Deliberately installs requirements.txt only, not
# requirements-data.txt: the API reads a prebuilt snapshot and needs neither
# pyarrow, xgboost nor nba_api. That keeps the image small enough for a 512 MB
# free tier (measured: ~21 MB of packages).

FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data/teams.json ./data/teams.json

ENV SNAPSHOT_DIR=/tmp/nba-snapshot
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
