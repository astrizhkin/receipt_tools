FROM python:3.12-slim AS base

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .

ENV PH_CONFIG=/app/config/pipeline.yaml \
    PH_ARTIFACTS_DIR=/artifacts

EXPOSE 8000
CMD ["python", "-m", "phunter.main"]

# test stage: docker build --target test -t ph-test pipeline && docker run --rm ph-test
FROM base AS test
RUN pip install --no-cache-dir ".[test]"
COPY tests ./tests
CMD ["pytest", "-q"]
