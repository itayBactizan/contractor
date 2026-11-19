# Python version must match .python-version
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# Organization CA certificates (put .crt files in certs/), so HTTPS works inside the container
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    UV_NATIVE_TLS=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv==0.9.5

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml / uv.lock change)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project --no-dev

# Then the code
COPY scripts/ scripts/

CMD ["uv", "run", "--no-sync", "scripts/contract_orthophoto.py"]
