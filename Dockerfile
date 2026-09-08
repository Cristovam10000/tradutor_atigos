FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 poppler-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY tradutor/__init__.py ./tradutor/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip pip install '.[dev]'
COPY . .
RUN pip install --no-deps --no-cache-dir -e .
ENV TRADUTOR_DADOS=/dados OLLAMA_HOST=http://modelo:11434
EXPOSE 8000
CMD ["python", "-m", "tradutor", "servir", "--host", "0.0.0.0"]
