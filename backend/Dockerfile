FROM public.ecr.aws/docker/library/python:3.12.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app

COPY pyproject.toml ./
COPY requirements.lock ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --upgrade pip && \
    pip install --requirement requirements.lock && \
    pip install --no-deps .

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "vpn_platform.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
