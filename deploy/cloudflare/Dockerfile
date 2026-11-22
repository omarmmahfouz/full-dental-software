# The online demo on Cloudflare Containers (see deploy/cloudflare/README.md).
# Built from the project's root folder:  docker build -f deploy/cloudflare/Dockerfile .
# BASE_IMAGE can point to a mirror when Docker Hub refuses downloads (e.g. mirror.gcr.io/library/python:3.12-slim).
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
# An optional build secret "ca" (a certificate file) is trusted while the packages download, for a network that
# inspects HTTPS. It is not kept in the image.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x deploy/cloudflare/start.sh

EXPOSE 8000
ENTRYPOINT ["deploy/cloudflare/start.sh"]
