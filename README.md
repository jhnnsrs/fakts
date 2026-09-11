# fakts-next

[![codecov](https://codecov.io/gh/jhnnsrs/fakts-next/branch/main/graph/badge.svg?token=UGXEA2THBV)](https://codecov.io/gh/jhnnsrs/fakts-next)
[![PyPI version](https://badge.fury.io/py/fakts-next.svg)](https://pypi.org/project/fakts-next/)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://pypi.org/project/fakts-next/)
![Maintainer](https://img.shields.io/badge/maintainer-jhnnsrs-blue)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/fakts-next.svg)](https://pypi.python.org/pypi/fakts-next/)
[![PyPI status](https://img.shields.io/pypi/status/fakts-next.svg)](https://pypi.python.org/pypi/fakts-next/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Fakts is an **asynchronous app configuration and service-discovery client** for
dynamic client-server deployments. An app declares *what* it needs (a
manifest with required services); fakts negotiates *where and how* to get it:
it discovers the server, registers the app (with one-time user approval),
fetches possible paths to find declared services, resolves every required service to a
**reachable** address, and hands out OAuth2 tokens — caching everything so
all of this happens exactly once.

Fakts powers app configuration for the [Arkitekt](https://arkitekt.live)
platform, but contains no Arkitekt-specific logic: it speaks a small,
documented HTTP protocol that any server can implement.

## Install

```bash
pip install fakts-next
```

Optional extras:

```bash
pip install fakts-next[qt]      # Qt widgets (endpoint picker, settings cache)
pip install fakts-next[rath]    # GraphQL transport links for rath
pip install fakts-next[crypto]  # signed alias challenges (Ed25519 verification)
```

## Quickstart

```python
from fakts_next import build_device_code_fakts, Manifest, Requirement

fakts = build_device_code_fakts(
    url="http://localhost:8000",
    manifest=Manifest(
        identifier="my-app",
        version="0.1.0",
        scopes=["openid"],
        requirements=[
            Requirement(key="rekuest", service="live.arkitekt.rekuest"),
        ],
    ),
)

async with fakts:
    alias = await fakts.aget_alias("rekuest")   # a verified, reachable address
    url = alias.to_http_path("graphql")         # http(s)://host:port/path/graphql
    ws = alias.to_ws_path("graphql")            # ws(s)://...
    token = await fakts.aget_token()            # OAuth2 access token
```

The **first run** opens the browser: the server shows what `my-app` is asking
for, the user approves it once, and the granted configuration is cached in
`.fakts_cache.json`. **Every later run starts instantly and silently** from
the cache — until the manifest changes (new scopes or requirements
automatically invalidate the cache) or the cached services stop answering
(fakts then re-fetches the configuration once and heals itself).

Everything also works synchronously (via [koil](https://github.com/jhnnsrs/koil)) —
same instance, no asyncio boilerplate:

```python
with fakts:
    alias = fakts.get_alias("rekuest")
    token = fakts.get_token()
```

## Core concepts

### Manifest & requirements

The `Manifest` is your app's identity card: a globally unique `identifier`,
a `version`, the OAuth2 `scopes` it needs, and a list of `Requirement`s —
the services it wants to talk to, referenced by a `key` of your choosing and
a globally unique `service` identifier (reverse-domain style). Requirements
can be `optional=True`: the app keeps working when they are absent.

### The remote protocol: discover → demand → claim

A `RemoteGrant` is composed of three pluggable parts:

| Role | Question it answers | Implementations |
|---|---|---|
| **Discovery** | *Where is the coordination server?* | `WellKnownDiscovery` (`/.well-known/fakts`), `FirstAdvertisedDiscovery` (UDP beacons), `SelectBeaconWidget` (Qt picker), `StaticDiscovery` |
| **Demander** | *How do we get a claim token?* | `DeviceCodeDemander` (browser approval), `RedeemDemander` (pre-issued token, headless), `StaticDemander` |
| **Claimer** | *How do we fetch the config?* | `ClaimEndpointClaimer` (the default), `StaticClaimer` |

The builders (`build_device_code_fakts`, `build_redeem_fakts`) wire the
common combinations for you; compose `RemoteGrant` yourself for anything
exotic. The exact HTTP exchanges are specified in
[The Fakts protocol](#the-fakts-protocol) below.

### ActiveFakts: what the server grants

The claimed configuration contains the deployment's identity (`self`), the
OAuth2 client credentials minted for your app (`auth`), and one `Instance`
per service, each with a list of `Alias`es — candidate addresses for
reaching that service (a deployment may expose the same service on a LAN
address, a VPN address and a public address).

`instances` only ever contains services that were actually granted. The
sibling `statuses` map reports the outcome per requirement key
(`granted` / `denied` / `unavailable`), so a user declining an optional
service is distinguishable from a deployment that does not offer it.
Servers that do not report statuses simply omit the field; the client
then treats missing services as `unknown`.

```python
match await fakts.aget_grant_status("kabinet"):
    case GrantStatus.DENIED: ...       # the user said no — respect it
    case GrantStatus.UNAVAILABLE: ...  # the deployment can't offer it
    case GrantStatus.GRANTED: ...

# or simply, for graceful degradation:
if alias := await fakts.aget_alias_or_none("kabinet"):
    enable_kabinet_features(alias)
```

### Alias resolution: challenge once, then stick

On the first `aget_alias(key)`, fakts *challenges* the aliases of every
required service (a concurrent HTTP probe against each alias's challenge
path) and keeps the first one that answers. If the instance carries a
`challenge_key`, the probe is cryptographically verified: the service must
sign a fresh nonce with its identity key, so an impostor answering 200
does not pass (see the protocol section). Subsequent calls return the
selected alias instantly — no further probing. The winning alias is also
persisted as the preferred one, so the next process start challenges the
last-known-good address first. Pass `force_refresh=True` to re-resolve, or
`omit_challenge=True` to skip probing entirely.

### Caching & self-healing

The cache (`FileCache` by default in the builders) stores the granted
configuration across runs, keyed to a hash of your manifest *and* the
server url — change either and the cache invalidates itself. If a *cached*
configuration turns out to be stale (services moved, client revoked), fakts
reloads from the grant once and retries before failing: an expired client
is re-registered, moved services are re-resolved.

## The Fakts protocol

Everything a server needs to implement to speak fakts. This section
describes **protocol version `1`**; the server advertises the version it
speaks in the well-known descriptor (`protocol_version`), and clients
treat a missing value as `"1"`. All exchanges are JSON over HTTP(S).
`{base}` is the server's fakts base URL as advertised by discovery (e.g.
`https://example.com/f/`). The negotiation endpoints share one response
envelope: a `status` field plus status-specific fields (`"granted"`
carries the payload; `"error"` / `"denied"` carry a message).

```
discover ── GET  {url}/.well-known/fakts        Where is the server?
demand   ── POST {base}start/ + {base}challenge/  One-time user approval → claim token
            (or POST {base}redeem/ headless)
claim    ── POST {base}claim/                   Claim token → ActiveFakts
use      ── alias challenges, OAuth2 token url, report url
```

### 1. Discovery — `GET {url}/.well-known/fakts`

Returns the endpoint descriptor. Only `name` is required; `base_url`
anchors all following requests:

```json
{
  "name": "my-deployment",
  "base_url": "https://example.com/f/",
  "protocol_version": "1",
  "version": "1.2",
  "description": "Our lab's deployment",
  "configure_url": "https://example.com/configure/",
  "claim_url": null,
  "retrieve_url": null
}
```

`protocol_version` is the fakts protocol version the server speaks
(this document: `"1"`); `version` is the server software's own version,
purely informational.

### 2a. Demand (interactive): the device code flow

The client registers its manifest and asks for a device code —
`POST {base}start/`:

```json
{
  "manifest": {
    "identifier": "my-app",
    "version": "0.1.0",
    "scopes": ["openid"],
    "requirements": [
      {"key": "rekuest", "service": "live.arkitekt.rekuest", "optional": false, "description": null}
    ],
    "logo": null, "description": null, "node_id": null, "public_sources": []
  },
  "expiration_time_seconds": 300,
  "redirect_uris": [],
  "requested_client_kind": "development"
}
```

→ `{"status": "granted", "code": "<device-code>"}` (or
`{"status": "error", "error": "..."}`).

The client opens `{configure_url}{code}` in the browser. **This is the
consent step**: the server shows the manifest — identifier, version,
scopes and requirements, with optional ones individually declinable — and
the *user* decides what the app gets.

Meanwhile the client polls `POST {base}challenge/` with
`{"code": "<device-code>"}` once per second:

| Response | Meaning |
|---|---|
| `{"status": "waiting"}` / `{"status": "pending"}` | Not decided yet — keep polling (until the code expires) |
| `{"status": "granted", "token": "<claim-token>"}` | Approved |
| `{"status": "denied", "message": "..."}` | The user refused the app entirely |
| `{"status": "error", "error": "..."}` | Code expired/invalid |

### 2b. Demand (headless): the redeem flow

A redeem token issued by the server beforehand is exchanged in one shot —
`POST {base}redeem/` (or the discovery's `retrieve_url`) with
`{"manifest": {...}, "token": "<redeem-token>"}` →
`{"status": "granted", "token": "<claim-token>"}`. Redeem tokens are
single-use.

### 3. Claim — `POST {base}claim/`

The claim token is exchanged for the actual configuration. Request:
`{"token": "<claim-token>", "secure": true}` (`secure` reflects whether
the client reached the server over https). Response:
`{"status": "granted", "config": <ActiveFakts>}`:

```json
{
  "self": {
    "deployment_name": "my-deployment",
    "alias": {"id": "self", "host": "example.com", "port": null, "ssl": true, "path": "lok", "challenge": "ht"}
  },
  "auth": {
    "client_id": "...", "client_secret": "...",
    "client_token": "...",
    "token_url": "https://example.com/o/token/",
    "report_url": "https://example.com/f/report/",
    "scopes": ["openid"]
  },
  "instances": {
    "rekuest": {
      "service": "live.arkitekt.rekuest",
      "identifier": "rekuest-prod",
      "challenge_key": {"kind": "ed25519", "key": "<base64 raw 32-byte public key>"},
      "aliases": [
        {"id": "lan", "host": "10.0.0.5", "port": 8090, "ssl": false, "path": null, "challenge": "ht"},
        {"id": "public", "host": "example.com", "port": null, "ssl": true, "path": "rekuest", "challenge": "ht"}
      ]
    }
  },
  "statuses": {
    "rekuest": "granted",
    "kabinet": "denied"
  }
}
```

- `instances` is keyed by the *requirement key* from the manifest and only
  contains granted services. Each alias is one candidate address; its
  challenge URL is `http(s)://{host}[:{port}][/{path}]/{challenge}`.
- `challenge_key` is the service's identity key. Registering one is
  **opt-in per service instance** — instances without a key keep the
  plain 200-challenge. When present, alias challenges must be *signed*
  (see below). One key per instance — the service has one identity no
  matter which route reaches it.
- `statuses` (optional, same keys) reports the outcome per requirement:
  `"granted"`, `"denied"` (user declined) or `"unavailable"` (deployment
  does not offer the service). Older servers omit it; clients coerce
  unrecognized values to `unknown`, so new statuses are forward compatible.
- `auth.client_token` identifies this client registration to the server
  (used for reporting); `client_id`/`client_secret` are the OAuth2
  client credentials.

### 4. Using the configuration

- **Alias challenge (plain)**: `GET` on an alias's challenge URL must
  answer `200` if (and only if) the service is reachable through that
  alias. The client probes aliases in order and uses the first that
  answers.
- **Alias challenge (signed)**: if the instance carries a
  `challenge_key`, the client appends a fresh random nonce —
  `GET {challenge_url}?nonce=<nonce>` — and the service must answer:

  ```json
  {"signature": "<base64(Ed25519-Sign(private_key, message))>"}
  ```

  where `message = UTF8("fakts-challenge-v1:" + nonce)`. The client
  verifies the signature against the pinned public key; with a key
  pinned, **a plain 200 fails the challenge** (no silent downgrade), so
  a host that merely answers the probe cannot impersonate the service.
  The domain tag means the service never signs raw client-supplied
  bytes; the fresh nonce prevents replaying recorded responses. Keys of
  an unrecognized `kind` are ignored with a warning (forward
  compatible). Requires the `crypto` extra
  (`pip install fakts-next[crypto]`).

  *Scope*: over plain http the signed challenge authenticates the
  *probe*, not the connection — an active attacker can relay it and
  hijack the traffic afterwards. Use `ssl: true` aliases for real
  channel security (pinning the same key at the TLS layer, accepting
  matching self-signed certificates, is the planned next step — it lets
  LAN deployments skip public CAs entirely).
- **Access tokens**: standard OAuth2 *client credentials* flow against
  `auth.token_url` with `client_id`, `client_secret` and the granted
  scopes.
- **Report** (optional): if `auth.report_url` is advertised, the client
  POSTs the outcome of alias resolution — best-effort telemetry that
  lets the server flag broken compositions:

  ```json
  {
    "token": "<client_token>",
    "alias_reports": {"rekuest": {"alias_id": "lan", "reason": null, "valid": true}},
    "functional": true
  }
  ```

## Design notes

Most of fakts is machinery for *negotiating* configuration that a smaller app
would simply hardcode. Each piece is there because the obvious simpler choice
breaks in a real client–server deployment. The decisions worth knowing:

**Negotiation instead of static configuration.** The obvious approach is to
bake service URLs into the app (or read them from a config file). But in a
client–server world the deployment owns the topology: the same service may live
on a LAN address, a VPN address and a public one; services move; each
deployment mints its own OAuth2 client. So the app declares *what* it needs (the
manifest) and the deployment decides *where* — fakts negotiates once and caches
the result. When you genuinely don't need negotiation (config injected by a
container, or hardcoded in a test) the static path is still there: see
[`EnvGrant` and `HardFaktsGrant`](#containers-configuration-from-the-environment).

**`RemoteGrant` is three pluggable parts, not one.** The remote flow could be a
single object, but its three questions vary independently: *where is the server*
(well-known URL, UDP beacon, Qt picker, static), *how do we get approved*
(device-code browser flow, pre-issued redeem token, static), and *how do we
fetch the config* (claim endpoint, static). Splitting Discovery / Demander /
Claimer into runtime-checkable protocols lets you compose new combinations — and
implement a part in your own code — without touching the orchestration. See
[discover → demand → claim](#the-remote-protocol-discover--demand--claim).

**Challenge once, then stick.** Two tempting extremes are both wrong: re-probing
every alias on every `aget_alias` is slow (each probe carries a timeout) and
churny, while trusting the cached address blindly hands back dead endpoints when
a service moves. fakts instead challenges all required services once on first
resolution, keeps the first alias that answers, and returns it instantly
thereafter — persisting it as the preferred address so the *next* process start
tries the last-known-good first. Re-resolution happens only on
`force_refresh=True` or the cached-config self-heal path. See
[alias resolution](#alias-resolution-challenge-once-then-stick).

**Signed challenges are opt-in per service instance.** Always requiring
signatures would force every deployment — including legacy ones and TLS-only
services whose certificate already proves identity — to mint and manage an
Ed25519 key. Never allowing them means a host that merely answers `200` on a
shared network can impersonate a service. Per-instance opt-in puts the bar
exactly where a deployment wants it, and once a key is pinned there is no silent
downgrade to a plain `200`. The honest limit: over plain http a signature
authenticates the *probe*, not the channel — use `ssl: true` aliases for real
channel security. See [using the configuration](#4-using-the-configuration).

**The cache key is a hash of the manifest *and* the server URL.** A single
path-keyed cache file would silently serve stale data across two boundaries that
matter: a changed manifest is a changed *permission* boundary (new scopes or
requirements), and a changed URL is a different *deployment* (dev vs prod).
Hashing both means either change invalidates the cache automatically. Writes are
atomic (temp file + rename) and a corrupt cache is treated as a miss and
reloaded — caching is an optimization, never a thing that can break startup. See
[caching & self-healing](#caching--self-healing).

**Denial is a first-class outcome, not an error.** If a user declining an
optional service looked the same as an outage, app authors would mark everything
required and users would grant everything — defeating consent. So the server's
per-key `statuses` distinguish `granted` / `denied` / `unavailable`,
`ServiceNotGrantedError` (a subclass of `AliasNotFoundError`) is catchable, and
`aget_alias_or_none` lets an app degrade gracefully. The end user stays in
control of what an app may reach. See
[what the server grants](#activefakts-what-the-server-grants).

**One instance, sync *and* async.** Rather than ship two clients that drift
apart, fakts writes the async methods (`aget_alias`, `aget_token`, …) and
derives the synchronous ones from them via [koil](https://github.com/jhnnsrs/koil),
so both surfaces share a single implementation and a single event loop.

## Recipes

### Headless / CI: redeem grant

No browser available? Have the server issue a redeem token and use:

```python
from fakts_next import build_redeem_fakts

fakts = build_redeem_fakts(
    url="http://localhost:8000",
    manifest=manifest,
    token="my-redeem-token",
)
```

### Containers: configuration from the environment

When the configuration is provisioned from the outside (compose files,
mounted secrets), skip the server negotiation entirely:

```python
from fakts_next import Fakts, EnvGrant

# reads $FAKTS (inline JSON) or $FAKTS_FILE (path to a JSON file)
fakts = Fakts(grant=EnvGrant(), manifest=manifest)
```

### Testing: hardcoded fakts

```python
from fakts_next import Fakts
from fakts_next.grants.hard import HardFaktsGrant

fakts = Fakts(grant=HardFaktsGrant(fakts=my_active_fakts), manifest=manifest)
```

(`fakts_next.grants.remote.builders.build_remote_testing` and
`build_remote_testing_with_token` cover the remote-flavored variants.)

### Qt apps

With the `[qt]` extra, `fakts_next.grants.remote.discovery.qt.selectable_beacon`
provides `SelectBeaconWidget` — a dialog that scans for advertised servers and
lets the user pick or type one — and `fakts_next.cache.qt.settings.QtSettingsCache`
persists the configuration in `QSettings` instead of a file.

### GraphQL via rath

With the `[rath]` extra, `fakts_next.contrib.rath` provides drop-in rath
links that configure themselves from a fakts context: `FaktsAIOHttpLink`,
`FaktsHttpXLink`, `FaktsGraphQLWSLink`, `FaktsWebsocketLink` (all resolving
their endpoint through `aget_alias`) and `FaktsAuthLink` (token loading and
refresh).

## Error handling

All errors derive from `FaktsError` and carry the URL contacted, the status
code and (truncated) response body where applicable:

| Error | Raised when |
|---|---|
| `NotEnteredError` | A method needing the context was called outside `with`/`async with` |
| `GrantError` / `RemoteGrantError` | The grant could not load the configuration (`DiscoveryError`, `DemandError`, `ClaimError` for the three remote stages) |
| `CompositionError` | One or more *required* services could not be resolved to a working alias |
| `AliasNotFoundError` | `aget_alias(key)` for a key that is not resolvable (not in the manifest, or its challenges failed) |
| `ServiceNotGrantedError` | Subclass of `AliasNotFoundError`: the key *is* declared, but the server granted no instance (user declined, or service unavailable) — catch it (or use `aget_alias_or_none`) to degrade gracefully |
| `NoFaktsFound` | `get_current_fakts_next()` outside any fakts context |

## Fakts options

| Option | Default | Effect |
|---|---|---|
| `load_on_enter` | `False` | Run the grant eagerly when entering the context (front-loads the interactive flow) |
| `delete_on_exit` | `False` | Reset the cache and loaded state on exit |
| `allow_auto_load` | `True` | If `False`, `aget_*` raises instead of loading implicitly — call `aload()` yourself |
| `refetch_on_alias_failure` | `True` | Reload from the grant once when aliases from a *cached* config fail their challenges |
| `alias_challenge_timeout` | `3` | Seconds per alias challenge probe |

## Development

```bash
uv sync                                            # install (Python >= 3.11)
uv run pytest -m "not integration"                 # unit tests
uv run pytest -m integration                       # needs docker (spins up a Fakts server)
uv run ruff check fakts_next/
```

The documentation site lives in `website/` (Docusaurus; API reference
generated with pydoc-markdown).
