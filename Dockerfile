FROM python:3.12-slim

# All runtime files (config.toml, .env-provided vars, token/service_account
# keys, state.json, the generated feed) live in the /data volume.
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 ftmo
USER ftmo
WORKDIR /data
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

CMD ["ftmo-calendar", "--config", "/data/config.toml", "serve"]
