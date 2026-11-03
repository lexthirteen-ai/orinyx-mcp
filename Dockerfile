FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/orinyx-mcp

COPY pyproject.toml README.md LICENSE requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Stamp the same release commit used for the image tag and deploy revision label.
ARG COMMIT_SHA=""
ENV ORINYX_COMMIT_SHA=${COMMIT_SHA}
LABEL org.opencontainers.image.revision=${COMMIT_SHA}

COPY orinyx_mcp ./orinyx_mcp
RUN pip install --no-cache-dir --no-deps .

RUN useradd --system --no-create-home orinyx
USER orinyx

EXPOSE 8000
CMD ["orinyx-mcp"]
