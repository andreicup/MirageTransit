# Runtime patch and multi-platform manifest digest verified against Docker registry.
FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /app
# Runtime has no third-party dependencies or package-install network requirements.
COPY src/miragetransit /app/miragetransit
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "miragetransit.service"]
