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

### The remote protocol: discover → authorize

A `RemoteGrant` is composed of two pluggable parts:

| Role | Question it answers | Implementations |
|---|---|---|
| **Discovery** | *Where is the coordination server?* | `WellKnownDiscovery` (`/.well-known/fakts`), `FirstAdvertisedDiscovery` (UDP beacons), `SelectBeaconWidget` (Qt picker), `StaticDiscovery` |
| **Authorizer** | *How do we get a session?* | `DeviceCodeAuthorizer` (browser approval), `RedeemAuthorizer` (pre-issued provisioning token, headless), `StaticAuthorizer` (a credential from an earlier session) |

Protocol v1 had a third role: a *claimer* that traded an approval artifact
for the configuration. It is gone because the OAuth token endpoint returns
both at once — there is nothing left to trade.

The builders (`build_device_code_fakts`, `build_redeem_fakts`) wire the
common combinations for you; compose `RemoteGrant` yourself for anything
exotic. The exact HTTP exchanges are specified in
[The Fakts protocol](#the-fakts-protocol) below.

### ActiveFakts: what the server grants

The granted configuration contains the deployment's identity (`self`), the
OAuth2 session held for your app (`auth` — a `client_id` and a rotating
refresh token, never a client secret), and one `Instance` per service, each
with a list of `Alias`es — candidate addresses for reaching that service (a
deployment may expose the same service on a LAN address, a VPN address and a
public address).

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
session across runs, keyed to a hash of your manifest *and* the server url —
change either and the cache invalidates itself. If a *cached* configuration
turns out to be stale (services moved), fakts reloads from the grant once
and retries before failing.

Under protocol v2 the cache is no longer just configuration: it holds a live
refresh token that rotates on every renewal, so it is written at mode `0600`
and updated far more often than before. Two consequences are worth knowing:

- **Give each app its own cache path.** The default is relative to the
  working directory, which is rarely what you want for anything but a script.
- **Processes sharing a cache cooperate rather than compete.** Each rotation
  revokes its predecessor, so a process whose token was rotated away adopts
  the one it finds on disk instead of re-authorizing — which would otherwise
  invalidate its siblings' credentials too.

When a session cannot be renewed at all — the authorization was revoked, or
it hit the server's maximum age — fakts raises `NeedsReauthenticationError`
rather than silently opening a browser, because re-approving an app replaces
its registration and disconnects every other process using it. Catch it and
call `fakts.alogin()` at a point where prompting is appropriate:

```python
try:
    token = await fakts.aget_token()
except NeedsReauthenticationError:
    await fakts.alogin()     # prompts only if the session cannot be revived
    token = await fakts.aget_token()
```

`alogin()` is idempotent — a healthy session returns immediately without a
prompt. `arefresh()` is the blunter tool: it *always* re-runs the grant, which
replaces the app's client registration and disconnects sibling processes.

To end a session, `alogout()` forgets it locally. It does **not** revoke
anything: the protocol has no revocation endpoint, so the refresh token stays
valid server-side until it expires, and a sibling process still holding it will
re-persist it on its next rotation.

## The Fakts protocol

Everything a server needs to implement to speak fakts. This section
describes **protocol version `2`**, which is an extension of the OAuth 2.0
device authorization grant ([RFC 8628][rfc8628]) rather than a protocol of
its own. The server advertises the version it speaks in the well-known
document (`protocol_version`); clients treat a missing value as `"1"` and
refuse to continue, since v1 and v2 share no endpoints.

What is genuinely fakts-specific — service instances, aliases, signed alias
challenges, per-requirement consent and grant statuses — rides along as
extension members on otherwise ordinary OAuth messages. Everything else is
standard, so an off-the-shelf OAuth library recognises most of the exchange.

```
discover ── GET  {url}/.well-known/fakts          Where is the server?
demand   ── POST {device_authorization_endpoint}  Register + stage a user code
consent  ── browser at verification_uri_complete  One-time user approval
token    ── POST {token_endpoint}, polled         Tokens *and* configuration
renew    ── POST {token_endpoint}                 grant_type=refresh_token
use      ── alias challenges, report endpoint
```

Two properties of the token endpoint shape everything downstream:

- It returns the configuration **together with** the tokens. There is no
  separate "claim" step, because there is no intermediate artifact to trade.
- It re-renders that configuration on **every** response, including every
  refresh. Aliases are host-aware, so configuration drift reaches clients
  without anyone re-approving anything.

[rfc8628]: https://datatracker.ietf.org/doc/html/rfc8628

### 1. Discovery — `GET {url}/.well-known/fakts`

Returns a document that is simultaneously the fakts descriptor and OAuth 2.0
authorization-server metadata:

```json
{
  "name": "My Deployment",
  "version": "0.1.0",
  "protocol_version": "2",
  "description": "...",
  "base_url": "https://example.com/lok/f/",

  "issuer": "https://example.com",
  "token_endpoint": "https://example.com/lok/o/token/",
  "device_authorization_endpoint": "https://example.com/lok/o/app-authorization/",
  "jwks_uri": "https://example.com/lok/o/jwks/",
  "grant_types_supported": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
  "configure": "https://example.com/configure/{code}"
}
```

`name` and `token_endpoint` are required. The fakts members carry **no
prefix** — they sit alongside the standard ones in the same flat object,
and unknown members must be ignored rather than rejected (the same document
also advertises `mesh_*` and `hub_*` endpoints that most clients skip).

**Every endpoint URL is absolute.** Deployments commonly sit under a
script-name prefix (`/lok` above), so a client that rebuilds an endpoint by
appending to `issuer` will get the path wrong. Take the URLs as given.

The one exception is the **report endpoint**, which is not advertised;
clients derive it as `{base_url}report/`.

### 2. Demand — `POST {device_authorization_endpoint}`

A JSON body, not form encoding — this is where v2 extends OAuth, because
OAuth has no slot for "here is what my app needs, ask the user which parts
to grant":

```json
{
  "manifest": {"identifier": "my-app", "version": "0.1.0", "scopes": ["openid"],
               "requirements": [{"key": "rekuest", "service": "live.arkitekt.rekuest",
                                 "optional": false}]},
  "expiration_time_seconds": 300,
  "redirect_uris": [],
  "requested_client_kind": "development",
  "requested_client_role": "interface"
}
```

The manifest is a **nested object** here. (The redeem grant in §5 sends the
same manifest as a JSON *string* in a form field — the encodings genuinely
differ, so do not share a code path between them.)

This request also performs client registration: the server mints a *public*
OAuth client for the app (`client_secret: ""`,
`token_endpoint_auth_method: "none"`) and binds it to the device code when
the user approves. One client per app, not one per installation — under v2
it is the *token* that identifies an installation.

The response is RFC 8628 plus the minted `client_id`:

```json
{
  "status": "granted",
  "device_code": "...", "user_code": "WDJB-MJHT", "client_id": "6f0c...",
  "token_endpoint": "https://example.com/lok/o/token/",
  "verification_uri": "https://example.com/configure/",
  "verification_uri_complete": "https://example.com/configure/WDJB-MJHT",
  "expires_in": 300, "interval": 5
}
```

Clients must **carry `client_id` forward** — into polling, and into every
later refresh. It is never derived from the manifest identifier. They should
send the user to `verification_uri_complete` as given rather than deriving an
approval URL.

Two error shapes are specific to this endpoint and easy to mistake for
success: failure is reported as **HTTP 200** with `{"status": "error",
"error": "..."}`, and throttling as **HTTP 429** with a bare
`{"error": "slow_down"}` and no `status` key at all.

### 3. Token — `POST {token_endpoint}`, polled

Standard RFC 8628 polling, form-encoded:

```
grant_type=urn:ietf:params:oauth:grant-type:device_code&device_code=...&client_id=...
```

The RFC 8628 error codes replace v1's bespoke status envelope:

| `error` | client behaviour |
|---|---|
| `authorization_pending` | keep polling |
| `slow_down` | `interval += 5`, keep polling |
| `access_denied` | the user refused — a legitimate outcome, not a fault |
| `expired_token` | the code expired before approval |

Success carries the tokens **and** the configuration as top-level members:

```json
{
  "access_token": "eyJ...", "refresh_token": "...", "token_type": "Bearer",
  "expires_in": 3600, "scope": "openid read",
  "client_id": "6f0c...",

  "self": {"deployment_name": "my-deployment",
           "alias": {"id": "self", "host": "example.com", "ssl": true, "path": "lok", "challenge": "ht"}},
  "instances": {
    "rekuest": {"service": "live.arkitekt.rekuest", "identifier": "3",
                "aliases": [{"id": "lan", "host": "10.0.0.4", "port": 8080, "challenge": "ht"}],
                "challenge_key": {"kind": "ed25519", "key": "<base64>"}}
  },
  "statuses": {"rekuest": "granted", "kabinet": "denied"}
}
```

`instances` is keyed by the **requirement key** from the manifest, not by
service identifier. `statuses` is `granted` | `denied` | `unavailable`;
`denied` means the user declined an optional requirement, `unavailable`
that the deployment could not offer it. Unknown values must not break
older clients.

The granted `scope` may legitimately be narrower than what was requested —
that is what per-requirement consent *means* — so clients must not validate
one against the other.

### 4. Renew — `grant_type=refresh_token`

```
grant_type=refresh_token&refresh_token=...&client_id=...
```

Both parameters are required: the endpoint authenticates the client before
it validates the token, and then checks the token belongs to that client. A
bare refresh token is not a usable credential.

**Refresh tokens rotate**: each use issues a new one and revokes its
predecessor immediately. This has consequences that are easy to get wrong,
so they are stated as obligations below.

### 5. Redeem — the headless grant

For CI runners and deployed containers, where no human is available. An
extension grant at the same token endpoint:

```
grant_type=urn:fakts:grant-type:redeem&redeem_token=...&manifest=<json string>
```

Note the URN has no `params:oauth` segment — it is a fakts URN. Returns the
same combined response as §3, including a refresh token. It never returns a
client secret; v2 issues none.

### 6. Report — `POST {base_url}report/`

Optional, best-effort telemetry that lets the server flag broken
compositions. Authenticated with the access token, like any other resource:

```
Authorization: Bearer <access_token>
```

```json
{
  "alias_reports": {"rekuest": {"alias_id": "lan", "reason": null, "valid": true}},
  "functional": true
}
```

Keyed by requirement key. A failing report must never break the app.

### 7. Using the configuration

Alias challenges are unchanged from v1. Each alias advertises a `challenge`
path; the client GETs it and requires a 200 before treating the alias as
usable, trying them in order until one answers.

When an instance carries a `challenge_key`, a plain 200 is no longer
enough. The client sends a random nonce and the service must return a
signature over the domain-separated message
`fakts-challenge-v1:<nonce>`, made with the matching Ed25519 private key:

```
GET {alias.challenge_path}?nonce=<random>
→ {"signature": "<base64>"}
```

The client verifies against the pinned key and **never downgrades**: an
instance with a key that answers without a valid signature is rejected,
which is what stops anything on the network from impersonating a service
by answering first.

### Client and server obligations

Rotation only works if both sides hold up their end. These are normative.

**Servers MUST NOT apply refresh-token reuse detection to fakts clients**,
or MUST accept a superseded token for a short grace window. Fakts clients
are public, share a process-local cache, and legitimately race. OAuth 2.1
recommends reuse detection with family-wide revocation; applying it here
turns a recoverable collision into a hard failure that needs a human.

**Clients MUST persist a rotated refresh token before using the new access
token**, at mode `0600`. The server commits the rotation when it answers, so
a token that is used but not persisted is simply lost.

**Clients MUST NOT re-run an interactive grant automatically.** Approving an
app again causes the server to replace its client registration and delete the
old one — which severs every other process sharing that credential. Automatic
recovery is only safe for non-interactive grants (redeem).

**Multi-process deployments SHOULD share one cache** and let the loser of a
rotation race adopt the winner's credential, rather than each re-authorizing.

### Transport

Plain HTTP against a **loopback** host is always acceptable, and needs no
configuration on either side. Plain HTTP against a **network** host is a
supported deployment mode, but since v2 puts a rotating refresh token on the
wire it must be opted into explicitly on both ends — clients via
`allow_insecure_transport` (or `FAKTS_ALLOW_INSECURE_TRANSPORT=1`), servers
via whatever their OAuth library requires.

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

**`RemoteGrant` is two pluggable parts, not one.** The remote flow could be a
single object, but its two questions vary independently: *where is the server*
(well-known URL, UDP beacon, Qt picker, static) and *how do we get a session*
(device-code browser flow, pre-issued redeem token, an existing credential).
Splitting Discovery / Authorizer into runtime-checkable protocols lets you
compose new combinations — and implement a part in your own code — without
touching the orchestration. See
[discover → authorize](#the-remote-protocol-discover--authorize).

It used to be three parts: protocol v1 separated *getting approved* from
*fetching the config*, because approval yielded a claim token that a second
request exchanged. Adopting the OAuth device grant collapsed both into the
token endpoint, and the third part had nothing left to do.

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
| `NeedsReauthenticationError` | The session can only be recovered by a human — call `alogin()` where prompting is appropriate |
| `NoFaktsFound` | `get_current_fakts_next()` outside any fakts context |

## Fakts options

| Option | Default | Effect |
|---|---|---|
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
