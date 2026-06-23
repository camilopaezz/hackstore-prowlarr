# AGENTS.md

## Architecture

```
Prowlarr → Cardigann → hackstore.yml → proxy.py (localhost:7070) → hackstore.fo
                                          ↓
                              decrypts acortalink URLs in HTML
                              rewrites href/src/action to proxy
                              enriches listing pages (pre-fetches detail
                                pages → clones results per quality tier)
                              filters detail pages to single quality tier
```

- `proxy.py` — Flask reverse proxy, must be running for the indexer to work
- `hackstore.yml` — Cardigann v11 indexer definition, installed into Prowlarr's `Definitions/Custom/`
- `decrypt_url.py` — standalone; called by the proxy to decrypt `acortalink.net/s.php?i=...` URLs into real magnet/torrent links

## Quality tier enrichment

The proxy clones each listing page result N times (once per quality tier found on the detail page), so Prowlarr sees separate results like:
- `Movie.2026.WEB-DL.4K.Latino`
- `Movie.2026.WEB-DL.1080p.Latino`
- `Movie.2026.1080p.Latino`
- `Movie.2026.720p.Latino`

Each clone's `href` includes `?_tier=N`. When Cardigann visits the detail page, the proxy strips `_tier` from the upstream request and filters the response HTML to show only that quality's accordion section.

## Env vars

| Var | Default | Description |
|---|---|---|
| `DETAIL_CACHE_TTL` | `3600` | Seconds to cache detail page tier metadata |
| `MAX_TIERS` | `4` | Max quality tiers to expose per result |
| `TMDB_API_KEY` | `""` | TMDB API v3 key. If empty, query translation is skipped |
| `TMDB_LANGUAGES` | `es-MX,es` | Comma-separated ordered list of locale codes to try |
| `TMDB_TITLE_CACHE_TTL` | `86400` | Seconds to cache translated titles |

## Commands

```bash
# Install deps (uses uv)
uv venv && source .venv/bin/activate && uv pip install cryptography flask requests beautifulsoup4

# Start proxy (required before using the indexer in Prowlarr)
./.venv/bin/python proxy.py

# Test proxy is working
curl -s --max-time 20 http://localhost:7070/ | head -c 300

# Test acortalink decryption (any detail page through proxy)
curl -s --max-time 30 http://localhost:7070/peliculas/stuart-little-2-la-aventura-continua-2002/ | rg -c 'magnet:'
# Should return >0

# Validate YML against Prowlarr v11 schema
git clone https://github.com/Prowlarr/Indexers.git /tmp/prowlarr-indexers
cd /tmp/prowlarr-indexers && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/validate.py --single path/to/hackstore.yml definitions/v11/schema.json
```

## Docker / networking gotchas

When Prowlarr runs in Docker but the proxy runs on the host:

- **The proxy binds `0.0.0.0`**, not `127.0.0.1`. `localhost` inside Docker is the container's own loopback, not the host.
- **The proxy uses `request.host_url`** to determine the base URL for rewritten links — it automatically uses whatever host:port Prowlarr used to reach the proxy. No configuration needed.
- **`hackstore.yml` `links`** must match the URL Prowlarr can actually reach. Only keep the one Prowlarr can actually reach — remove `localhost` entries when using Docker.
- If you change the proxy host/port, update only `hackstore.yml` `links`.

## Schema gotchas

The v11 schema requires one of these in `search.fields` (even for indexers that extract downloads from detail pages):
- `download`, `magnet`, or `infohash` — use `text: "{{ .Result.details }}"` when the real download is extracted by the `download` block

Categories are handled by per-path `categories` arrays in `search.paths` — no `category` field in `search.fields` is needed when each path has its own category.

The proxy passes `debug=False` to Flask — using `debug=True` causes the reloader to hang.

## Indexer gotchas

- **Title must include the year** (e.g. `Michael (2026)`) for Radarr/Sonarr to match results. Do not strip the year from the title field.
- **Download links are on detail pages**, not listing pages. The `download` field in `search.fields` points to `details`. The `download` block selectors run against the detail page HTML (after the proxy decrypts acortalink URLs).
- The first `table.newtab a.btn-slide` on any detail page is always the Bittorrent magnet link (highest quality).

## Install to Prowlarr

```bash
cp hackstore.yml <Prowlarr config>/Definitions/Custom/
# restart Prowlarr, then add indexer via UI
```

Common Prowlarr config paths:
- Docker: `/config/Definitions/Custom/`
- Linux: `~/.config/Prowlarr/Definitions/Custom/`
