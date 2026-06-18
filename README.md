# hackstore-radarr

Prowlarr indexer proxy for [hackstore.fo](https://hackstore.fo) — provides Latin-American Spanish movies, series, and anime to Radarr/Sonarr.

## Features

- **Reverse proxy** — transparently proxies hackstore.fo, rewriting all links so Prowlarr stays within the proxy
- **acortalink decryption** — decrypts `acortalink.net/s.php?i=…` URLs into real magnet/torrent links
- **Quality tier enrichment** — listing pages are automatically cloned per quality tier (4K, 1080p, 720p, etc.) with metadata like size and source
- **TMDB query translation** (optional) — translates English search queries to Latin-American Spanish via TMDB API for better search results

## Quick start (Docker)

```bash
# Build
docker build -t hackstore-proxy .

# Run
docker run -d \
  -p 8080:8080 \
  -e PROXY_HOST=http://<your-host-ip>:8080 \
  -e TMDB_API_KEY=your_tmdb_api_key \
  hackstore-proxy
```

Then configure `hackstore.yml` links to point to `http://<your-host-ip>:8080/` and install it into Prowlarr's `Definitions/Custom/`.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PROXY_HOST` | `http://localhost:8080` | Base URL for rewritten links — must be reachable by Prowlarr |
| `DETAIL_CACHE_TTL` | `3600` | Seconds to cache detail page tier metadata |
| `MAX_TIERS` | `4` | Max quality tiers to expose per listing result |
| `TMDB_API_KEY` | `""` | TMDB API v3 key. If empty, query translation is skipped |
| `TMDB_LANGUAGES` | `es-MX,es` | Comma-separated locale codes to try for translation |
| `TMDB_TITLE_CACHE_TTL` | `86400` | Seconds to cache translated titles |

## Architecture

```
Prowlarr → Cardigann → hackstore.yml → proxy.py (localhost:8080) → hackstore.fo
                                          ↓
                              decrypts acortalink URLs in HTML
                              rewrites href/src/action to proxy
                              enriches listing pages (pre-fetches detail
                                pages → clones results per quality tier)
                              filters detail pages to single quality tier
```

## Setup with Prowlarr

1. Copy `hackstore.yml` to `<Prowlarr config>/Definitions/Custom/`
2. Edit the `links` section in `hackstore.yml` to match your proxy URL (remove the LAN IP entries, add your own)
3. Restart Prowlarr
4. Settings → Indexers → Add → search "Hackstore" → add it

Common Prowlarr config paths:
- Docker: `/config/Definitions/Custom/`
- Linux: `~/.config/Prowlarr/Definitions/Custom/`

## Docker networking

When Prowlarr runs in Docker but the proxy runs on the host:
- The proxy binds `0.0.0.0` automatically
- Use the host IP (or `host.docker.internal`) as `PROXY_HOST`
- Ensure `hackstore.yml` links match the same reachable URL

## Development

```bash
# Install deps
uv venv && source .venv/bin/activate
uv pip install -e .

# Start proxy
python proxy.py

# Lint & format
uv run ruff check .          # check only
uv run ruff check . --fix    # auto-fix
uv run ruff format .         # format code

# Test
curl -s --max-time 20 http://localhost:8080/ | head -c 300
```
