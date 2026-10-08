# Veles-MOEX backend image.
# Build context is the repository root.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy app code first so setuptools can discover the `app` package at install time.
COPY backend/pyproject.toml backend/README.md backend/requirements.lock ./
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

# P4 (MVP-7.3): trust the Russian Trusted Root CA chain that signs *.tbank.ru
# (official certs from https://www.gosuslugi.ru/crt — see docker/certs/README.md).
# TLS verification stays ON: certs go into the system store via update-ca-certificates.
# NOTE: update-ca-certificates only processes *.crt, so the .pem sources are
# copied under .crt names.
COPY docker/certs/russian_trusted_root_ca.pem /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY docker/certs/russian_trusted_sub_ca.pem /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
COPY docker/certs/russian_trusted_sub_ca_2024.pem /usr/local/share/ca-certificates/russian_trusted_sub_ca_2024.crt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates

# B1 (MVP-7.3, review round 1): httpx (certifi) verifies TLS against its own
# bundle, not the system store, so update-ca-certificates alone was not enough
# and the image failed against *.tbank.ru with CERTIFICATE_VERIFY_FAILED.
# Point certifi at the system bundle, which includes the Russian Trusted Root
# CA chain from P4. TLS verification stays ON; no operator environment is
# needed — the value is part of the image.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_DIR=/etc/ssl/certs

# P2 (MVP-7.3): install the exact dependency set the tests run on — the
# requirements.lock pins every package, so builds are reproducible and the
# image cannot silently pick up a newer FastAPI.
RUN pip install --no-cache-dir -c requirements.lock .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
