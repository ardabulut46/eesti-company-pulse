# Pipeline + app image. Data lives in a volume mounted at /data (never baked into the image).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PULSE_DATA_DIR=/data \
    PULSE_DBT_DIR=/opt/pulse/dbt

WORKDIR /opt/pulse
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[dbt,app]"
COPY dbt ./dbt
COPY app ./app
# Parse once at build time so a broken dbt project fails the image build, not the first run.
RUN cd dbt && DBT_PROFILES_DIR=. dbt parse --no-partial-parse > /dev/null && rm -rf target logs

VOLUME ["/data"]
ENTRYPOINT ["pulse"]
CMD ["--help"]
