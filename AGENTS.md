# AGENTS.md

## Architecture

```
Prowlarr → Cardigann → hackstore.yml → proxy.py (localhost:8080) → hackstore.fo
                                          ↓
                              decrypts acortalink URLs in HTML
                              rewrites href/src/action to proxy
```

- `proxy.py` — Flask reverse proxy, must be running for the indexer to work
- `hackstore.yml` — Cardigann v11 indexer definition, installed into Prowlarr's `Definitions/Custom/`
- `decrypt_url.py` — standalone; called by the proxy to decrypt `acortalink.net/s.php?i=...` URLs into real magnet/torrent links

## Commands

```bash
# Install deps (uses uv)
uv venv && source .venv/bin/activate && uv pip install cryptography flask requests

# Start proxy (required before using the indexer in Prowlarr)
./.venv/bin/python proxy.py

# Test proxy is working
curl -s --max-time 20 http://localhost:8080/ | head -c 300

# Test acortalink decryption (any detail page through proxy)
curl -s --max-time 30 http://localhost:8080/peliculas/stuart-little-2-la-aventura-continua-2002/ | rg -c 'magnet:'
# Should return >0

# Validate YML against Prowlarr v11 schema
git clone https://github.com/Prowlarr/Indexers.git /tmp/prowlarr-indexers
cd /tmp/prowlarr-indexers && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/validate.py --single path/to/hackstore.yml definitions/v11/schema.json
```

## Docker / networking gotchas

When Prowlarr runs in Docker but the proxy runs on the host:

- **The proxy binds `0.0.0.0`**, not `127.0.0.1`. `localhost` inside Docker is the container's own loopback, not the host.
- **`PROXY_HOST` env var** controls the base URL the proxy uses when rewriting `href`/`src`/`action` in HTML. Default: `http://192.168.1.91:8080`. Every rewritten link Prowlarr follows must use a host:port reachable from inside the Docker container.
- **`hackstore.yml` `links`** must match the same reachable URL. Only keep the one Prowlarr can actually reach — remove `localhost` entries when using Docker.
- If you change the proxy host/port, update both `proxy.py` (via `PROXY_HOST` env var or the fallback) and `hackstore.yml` `links`.

## Schema gotchas

The v11 schema requires these in `search.fields` (even for indexers that extract downloads from detail pages):
- `category` or `categorydesc` — use `text: 2000` as a default
- `download`, `magnet`, or `infohash` — use `text: "{{ .Result.details }}"` when the real download is extracted by the `download` block

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
