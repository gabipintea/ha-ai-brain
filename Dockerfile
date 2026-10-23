ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM}

WORKDIR /app

# Support both Debian/Ubuntu slim images and Home Assistant Alpine base images
RUN if command -v apt-get >/dev/null 2>&1; then \
        apt-get update && apt-get install -y --no-install-recommends jq curl iputils-ping && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache python3 py3-pip jq curl iputils; \
    fi

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY agents/ ./agents/
COPY run.sh /run.sh

RUN pip install --no-cache-dir --break-system-packages -e . 2>/dev/null || pip install --no-cache-dir -e .
RUN chmod a+x /run.sh

EXPOSE 8099

CMD [ "/run.sh" ]
