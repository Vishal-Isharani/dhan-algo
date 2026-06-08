FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime \
    && echo Asia/Kolkata > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Repo configs baked into image; entrypoint syncs them into the configs volume on start.
RUN mkdir -p /app/config.defaults \
    && if [ -f strategies/manifest.json ]; then cp strategies/manifest.json /app/config.defaults/manifest.json; else cp strategies/manifest.example.json /app/config.defaults/manifest.json; fi \
    && for f in strategies/configs/*.json; do case "$$f" in *.example.json) ;; *) cp "$$f" /app/config.defaults/ ;; esac; done

ENV PATH="/app/.venv/bin:${PATH}"

RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["run-scheduler"]
