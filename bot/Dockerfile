FROM public.ecr.aws/docker/library/python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY src ./src
RUN pip install --upgrade pip && \
    pip install --requirement requirements.lock && \
    pip install --no-deps .

USER 10001:10001
CMD ["python", "-m", "vpn_bot.main"]
