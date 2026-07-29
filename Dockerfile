# Container image for HeartGuard AI.
#
# Built for Hugging Face Spaces (Docker SDK), which needs no payment details — but this
# is a plain image and runs anywhere Docker does: Fly.io, Koyeb, a VPS, or locally with
#   docker build -t heartguard . && docker run -p 7860:7860 heartguard
#
# python:3.13-slim, not 3.14 (used in development): not every scientific wheel is
# published for 3.14 yet, and falling back to compiling scipy from source turns a
# two-minute build into a twenty-minute one that often runs out of memory.
FROM python:3.13-slim

# libgomp1 is REQUIRED and easy to miss. xgboost's manylinux wheel links against
# OpenMP at runtime, which the slim image does not carry — without it the container
# builds cleanly and then dies on the first import with
# `libgomp.so.1: cannot open shared object file`. Nothing else needs compiling:
# numpy, scipy, scikit-learn, xgboost, shap and matplotlib all ship manylinux wheels,
# so no gcc or gfortran is installed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# A non-root user, because Hugging Face Spaces runs the container unprivileged and the
# application WRITES to its own directory: the SQLite database, system_settings.json,
# and the generated stylesheet and favicon. Owned by root, every one of those fails.
RUN useradd --create-home --uid 1000 app
WORKDIR /home/app/src

# Requirements first, as their own layer: dependencies change far less often than code,
# so an edit to a template reuses the ~700 MB install instead of repeating it.
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    THREADS=4 \
    HEARTGUARD_DEBUG=0 \
    HEARTGUARD_TRUST_PROXY=1 \
    HEARTGUARD_HTTPS=0

# HEARTGUARD_TRUST_PROXY=1 is set because this image is meant to run behind one. Without
# it `request.remote_addr` is the proxy's address for every visitor, and the login rate
# limiter — keyed on (ip, username) — lets an attacker guessing at `admin` lock out the
# real administrator.
#
# HEARTGUARD_HTTPS defaults to 0 so `docker run -p 7860:7860` works over plain http. Set
# it to 1 in the deployment (a Hugging Face Space variable, or `-e` locally behind TLS)
# to add the Secure flag to the session cookie. It is deliberately NOT baked in: with
# Secure set, a browser will not return the cookie over http, so every sign-in fails
# with 400 and the message looks like an expired form rather than a misconfiguration.

# 7860 is what Hugging Face Spaces expects; `app_port` in README.md declares it.
EXPOSE 7860

# wsgi.py runs waitress and reads HOST/PORT/THREADS from the environment, so there is
# nothing to configure here beyond the variables above.
CMD ["python", "wsgi.py"]
