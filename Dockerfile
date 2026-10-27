# syntax=docker/dockerfile:1
# Base image pinned by digest so builds are reproducible; Dependabot proposes updates.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:b3575dcf816cdacc5292df77a6e3e59b8941631078373a045efa2ac1e9c5c3b2

# ---- build: install hash-verified dependencies into an isolated venv ----
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# The venv gets no pip of its own; this stage's pip installs into it.
RUN python -m venv --without-pip /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip --python /opt/venv/bin/python install --require-hashes --no-deps -r /tmp/requirements.txt

# ---- runtime: no build tools, no pip, unprivileged user ----
FROM ${PYTHON_IMAGE} AS runtime
# pip is not needed at runtime, and its vendored libraries (urllib3, msgpack,
# pkg_resources) are attack surface that image scanners flag.
RUN python -m pip uninstall --yes --root-user-action=ignore pip \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY app ./app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=2)"
CMD ["python", "-m", "app.server"]
