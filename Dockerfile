# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.14-alpine3.23
ARG DEBIAN_IMAGE=debian:bookworm-slim

FROM ${PYTHON_IMAGE} AS cpython-deps
WORKDIR /build
COPY requirements-docker.txt .
RUN python -m pip install --no-cache-dir --no-compile --only-binary=:all: \
    --target /packages -r requirements-docker.txt

FROM ${PYTHON_IMAGE} AS cpython
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/packages TESTLAB_DB=/data/testlab.sqlite3 HOME=/tmp
WORKDIR /app
RUN mkdir /data && chown 10001:10001 /data
COPY --from=cpython-deps /packages /opt/packages
COPY server.py .
COPY testlab/ testlab/
COPY static/ static/
COPY sql/ sql/
COPY ops/ ops/
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD ["python", "ops/health.py"]
CMD ["python", "server.py", "--host", "0.0.0.0"]

FROM cpython AS cpython-tests
COPY tests/ tests/
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

# GraalPy - нативная Python-среда GraalVM Community, без установленной JVM.
FROM ${DEBIAN_IMAGE} AS graalpy-build
ARG TARGETARCH
ARG GRAALPY_VERSION=25.4.4
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      amd64) arch=amd64; sha=a038c8fa650f3bd17046f3cb8609b271e07b0e21fdb8527f10726beee442b93d ;; \
      arm64) arch=aarch64; sha=5d0fab1a2f541b387dbf3fbf6b123a5836a0bc99937076f34aeb29282ee246c1 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL --connect-timeout 20 --max-time 600 --retry 3 "https://github.com/oracle/graalpython/releases/download/graal-${GRAALPY_VERSION}/graalpy3.13-community-${GRAALPY_VERSION}-linux-${arch}.tar.gz" -o /tmp/graalpy.tgz \
    && echo "$sha  /tmp/graalpy.tgz" | sha256sum -c - \
    && mkdir /opt/graalpy \
    && tar -xzf /tmp/graalpy.tgz -C /opt/graalpy --strip-components=1 \
    && rm /tmp/graalpy.tgz
COPY requirements-docker.txt .
# Используется именно pip GraalPy: CPython-wheels с ним несовместимы.
RUN /opt/graalpy/bin/graalpy -m venv /tmp/venv \
    && case "$TARGETARCH" in amd64) wheel_arch=x86_64 ;; arm64) wheel_arch=aarch64 ;; esac \
    && mkdir /tmp/wheels \
    && wheel="bcrypt-5.0.0-graalpy313-graalpy253_313_native-manylinux_2_28_${wheel_arch}.whl" \
    && curl -fsSL --connect-timeout 20 --max-time 120 --retry 3 --retry-all-errors \
       "https://gds.oracle.com/download/graalpy-wheels/${wheel}" -o "/tmp/wheels/${wheel}" \
    && /tmp/venv/bin/python -m pip install --no-cache-dir --no-compile --only-binary=:all: \
       --no-index --find-links /tmp/wheels --target /packages -r requirements-docker.txt \
    && rm -rf /opt/graalpy/docs /opt/graalpy/include /opt/graalpy/graalpy_virtualenv_seeder

FROM ${DEBIAN_IMAGE} AS graalpy
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/packages TESTLAB_DB=/data/testlab.sqlite3 HOME=/tmp \
    PATH=/opt/graalpy/bin:$PATH
WORKDIR /app
RUN mkdir /data && chown 10001:10001 /data
COPY --from=graalpy-build /opt/graalpy /opt/graalpy
COPY --from=graalpy-build /packages /opt/packages
COPY server.py .
COPY testlab/ testlab/
COPY static/ static/
COPY sql/ sql/
COPY ops/ ops/
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=10s --start-period=40s --retries=4 \
    CMD ["python", "ops/health.py"]
CMD ["python", "server.py", "--host", "0.0.0.0"]

FROM graalpy AS graalpy-tests
COPY tests/ tests/
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM node:22-alpine AS js-tests
WORKDIR /app
COPY static/js/ static/js/
COPY tests/test_ui.js tests/test_ui.js
USER node
CMD ["node", "tests/test_ui.js"]

# docker build . по умолчанию создаёт компактный CPython-образ.
FROM cpython AS runtime
