FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Match the dashboard versions verified in the integration smoke tests.
RUN python -m pip install --no-cache-dir streamlit==1.67.0 pandas==3.1.1

COPY app.py ./
COPY src/ ./src/
COPY data/ ./data/
COPY .streamlit/config.toml ./.streamlit/config.toml

EXPOSE 80

CMD ["sh", "-c", "exec python -m streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-80} --server.headless=true --browser.gatherUsageStats=false"]
