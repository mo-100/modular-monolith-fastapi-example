FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml alembic.ini main.py ./
COPY shared ./shared
COPY modules ./modules
COPY scripts ./scripts

# Editable install keeps migrations and alembic.ini addressable from /app.
RUN pip install -e .

EXPOSE 8000

CMD ["uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test

RUN pip install -e ".[dev]"
COPY tests ./tests

CMD ["pytest"]
