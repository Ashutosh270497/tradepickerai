# Shadow paper trader for the frozen 4h trend filter. Public Delta data only; no API keys, no orders.
# Build for AWS Graviton (ARM64):  docker buildx build --platform linux/arm64 -t paper-trader .
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
WORKDIR /app
COPY requirements-paper.txt .
RUN pip install --no-cache-dir -r requirements-paper.txt
COPY core/ core/
COPY strategies/ strategies/
COPY paper/ paper/
COPY paper_config.json frozen_rules.md paper_trading_plan.md ./
RUN useradd --create-home --uid 10001 trader && mkdir -p /state && chown trader /state
USER trader
ENTRYPOINT ["python", "-m", "paper.run_task"]
