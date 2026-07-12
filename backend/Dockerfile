FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 YOLO_CONFIG_DIR=/tmp/Ultralytics
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY pyproject.toml ./
COPY app ./app
# Install a CPU wheel explicitly: PyPI's Linux torch wheel pulls CUDA runtime
# packages even for the default CPU deployment. CUDA is selected at runtime only
# in a separately GPU-enabled image/environment.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir ".[ultralytics]" \
    && pip uninstall --yes opencv-python \
    && pip install --no-cache-dir opencv-python-headless
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
