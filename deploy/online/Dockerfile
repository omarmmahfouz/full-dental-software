# The online demo (see deploy/online/README.md): Koyeb, Cloudflare Containers or any host that runs a Dockerfile.
# Built from the project's root folder:  docker build -f deploy/online/Dockerfile .
# BASE_IMAGE can point to a mirror when Docker Hub refuses downloads (e.g. mirror.gcr.io/library/python:3.12-slim).
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x deploy/online/start.sh

EXPOSE 8000
ENTRYPOINT ["deploy/online/start.sh"]
