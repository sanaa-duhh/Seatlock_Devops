FROM python:3.11-alpine@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup -g 10001 app && adduser -D -u 10001 -G app app
RUN apk upgrade --no-cache \
    && pip uninstall -y setuptools wheel pip
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
