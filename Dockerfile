FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py ./
COPY gamak_demo ./gamak_demo
COPY data ./data
COPY examples ./examples
COPY .streamlit ./.streamlit

RUN mkdir -p data/local

EXPOSE 8080

CMD ["sh", "-c", "uv run streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8080} --server.headless true"]
