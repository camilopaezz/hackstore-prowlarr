FROM python:3.13-alpine

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY proxy.py decrypt_url.py ./

EXPOSE 8080

ENV DETAIL_CACHE_TTL=3600 \
    MAX_TIERS=4 \
    TMDB_LANGUAGES=es-MX,es \
    TMDB_TITLE_CACHE_TTL=86400

CMD ["python", "proxy.py"]
