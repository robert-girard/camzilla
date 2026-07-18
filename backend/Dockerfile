FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 YOLO_CONFIG_DIR=/tmp/Ultralytics
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY pyproject.toml uv.lock ./
# Install a CPU wheel explicitly: PyPI's Linux torch wheel pulls CUDA runtime
# packages even for the default CPU deployment. CUDA is selected at runtime only
# in a separately GPU-enabled image/environment. A minimal package directory
# keeps this dependency layer independent of ordinary application source edits.
RUN mkdir app && touch app/__init__.py \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.13.0" "torchvision==0.28.0" \
    && pip install --no-cache-dir ".[ultralytics]" "ultralytics==8.4.92" \
    && pip uninstall --yes opencv-python \
    && pip install --no-cache-dir "opencv-python-headless==5.0.0.93"
RUN install -d -o appuser -g appuser /data /media
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
