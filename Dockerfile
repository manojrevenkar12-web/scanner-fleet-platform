# One image for both architectures: docker buildx build --platform linux/amd64,linux/arm64 .
# The test stage runs the suite on the target architecture (QEMU in CI for arm64).
FROM python:3.13-slim AS base
WORKDIR /opt/sfp
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir .

FROM base AS test
COPY tests ./tests
COPY scripts ./scripts
RUN pip install --no-cache-dir pytest amqtt grpcio-tools \
 && python -m pytest -q -p no:cacheprovider tests/test_platform.py tests/test_hal.py tests/test_mqtt.py

FROM base AS runtime
RUN useradd --system --home /var/lib/sfp sfp && mkdir -p /var/lib/sfp && chown sfp /var/lib/sfp
USER sfp
ENTRYPOINT ["sfp-agent"]
