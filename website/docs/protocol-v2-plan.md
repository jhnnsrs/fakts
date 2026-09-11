---
sidebar_position: 1
title: "Plan: protocol v2 (OAuth-native)"
---

:::danger Superseded — historical only

This was the **design proposal**, written before the server existed. Protocol
v2 has since shipped, and several assumptions below turned out differently in
the implementation — among them the discovery path (`/.well-known/fakts` was
kept, not replaced), the extension member names (no `fakts_` prefix), the
device request encoding (JSON, not form-encoded), and the origin of
`client_id` (minted by the server, not the manifest identifier).

**The normative specification is now "The Fakts protocol" in the README.**
Read that instead; this file is kept only for the reasoning behind the
decisions.

:::

# Fakts protocol v2 — an OAuth-native negotiation layer

> **Status: proposal, not implemented.** This document is the design plan for replacing
> the custom fakts negotiation protocol (v1) with a standard OAuth 2.0 device
> authorization grant carrying fakts-specific extension members. Nothing in the client
> has been changed yet.

## Context

Fakts today speaks a fully custom HTTP protocol for negotiation (see *The Fakts protocol*
in the README, "protocol version 1"): a bespoke discovery document, a `start/` +
`challenge/` polling pair that mints a *claim token*, and a `claim/` endpoint that
exchanges that claim token for the whole configuration — including OAuth2 `client_id` /
`client_secret`, which the client then uses in a **client_credentials** flow
(`fakts_next/fakts.py:244-321`) to get runtime access tokens.

Every one of those steps re-invents something OAuth already standardises: device-code
approval is RFC 8628, endpoint discovery is RFC 8414 / OIDC discovery, and "exchange an
authorization artifact for a token" *is* the token endpoint. The custom envelope
(`{"status": "granted", ...}`) means no off-the-shelf OAuth server or client library can
speak fakts without bespoke code on both ends — and the drift is already visible: the
TypeScript client's schema
(`arkitektio.github.io/src/lib/arkitekt/fakts/faktsSchema.tsx:22-40`) lacks `statuses` and
`challenge_key` and would reject a current Python-side claim.

**The change**: keep everything fakts is genuinely *about* — service instances, aliases,
signed alias challenges, per-requirement consent and grant statuses — and make it an
**extension of a standard OAuth 2.0 device authorization grant** rather than a protocol
of its own. Custom negotiation disappears; what stays fakts-specific rides as extension
members on standard OAuth messages.

Intentionally **breaking** (protocol v1 → v2, client `5.0.0`), with a **hard server-side
dependency**: lok must ship the device grant + extension members before a v2 client can
talk to it.

## Verdict: yes, and the server-side work is smaller than it looks

Three custom endpoints (`start/`, `challenge/`, `claim/`) and one custom response envelope
collapse into two standard OAuth requests. The fakts data model (`Alias`, `Instance`,
`ChallengeKey`, `GrantStatus`, signed challenges) survives **untouched** — it stops being a
protocol and becomes an extension payload.

Verified against the lok source at `/home/jhnnsrs/Code/deployments/next/mounts/lok`:

- lok runs **Authlib 1.7.2** (`authapp/server.py:25`, `pyproject.toml:29`), which **ships
  RFC 8628** (`authlib.oauth2.rfc8628`). lok's device-code flow is currently hand-rolled in
  its own `fakts` app (`fakts/views.py:110-209`) — adopting the standard grant *deletes*
  that code rather than adding to it.
- lok **already serves OIDC discovery** at `/.well-known/openid-configuration` with
  `issuer`, `token_endpoint`, `jwks_uri`, `grant_types_supported`
  (`authapp/views.py:80-101`). v2 discovery extends a document that already exists.
- Injecting `instances`/`self`/`statuses` into the token response is a **one-method
  override** on `MyJWTBearerTokenGenerator` (`authapp/token_generators.py`, registered at
  `authapp/server.py:71-74`), reusing the existing `render_hub`
  (`fakts/services/rendering.py:66-96`) minus its `auth` block.

One consequence is not free and is accepted deliberately: moving from **client_credentials**
(app-bound, renews forever, no user) to **refresh tokens** (user-bound, finite, revocable)
changes the failure mode for long-running and headless apps — see
[Consequences](#consequences-you-are-signing-up-for).

## Decisions taken

| Question | Decision |
|---|---|
| Token subject | Full user-bound `access_token` + `refresh_token`; **no** client_credentials in the remote flow |
| Config location | Inline in the token response as top-level extension members |
| Discovery | Standard AS metadata + `fakts_*` extension members |
| Client registration | **No** RFC 7591; the manifest rides on the device authorization request |

---

## The v2 wire protocol

```
discover ── GET  {url}/.well-known/oauth-authorization-server   (fallback: openid-configuration)
demand   ── POST {device_authorization_endpoint}                RFC 8628 §3.1
consent  ── browser at verification_uri_complete                RFC 8628 §3.3
token    ── POST {token_endpoint}  device_code grant, polled    RFC 8628 §3.4/3.5
             └─ returns the tokens AND the fakts config
renew    ── POST {token_endpoint}  refresh_token grant          RFC 6749 §6
use      ── alias challenges, report endpoint                   unchanged
```

### 1. Discovery

`GET {url}/.well-known/oauth-authorization-server`, falling back to
`/.well-known/openid-configuration` (which lok already serves). Standard metadata with
fakts values as `fakts_`-prefixed extension members — no second document to fetch:

```json
{
  "issuer": "https://example.com",
  "token_endpoint": "https://example.com/o/token/",
  "device_authorization_endpoint": "https://example.com/o/device/",
  "grant_types_supported": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
  "scopes_supported": ["openid", "read", "write"],

  "fakts_protocol_version": "2",
  "fakts_deployment_name": "my-deployment",
  "fakts_report_endpoint": "https://example.com/f/report/"
}
```

**URL construction** (`discovery/utils.py:36` currently does `f"{url}.well-known/fakts"`):
RFC 8414 §3.1 *inserts* the well-known segment between the authority and the issuer path
rather than appending it — for `https://example.com/f/` that is
`https://example.com/.well-known/oauth-authorization-server/f`. Since fakts URLs are usually
bare origins the two forms coincide, but try both in order (RFC 8414 form, then the
OIDC-style appended form) and take the first 200.

**Validity** becomes `issuer` + `token_endpoint` present (v1 checked only `name`,
`discovery/utils.py:58-64`). **Detect v1 explicitly** — a 404 on
`/.well-known/oauth-authorization-server` must never be the user-visible symptom:

```python
if "issuer" not in data and "name" in data:
    raise DiscoveryError(
        f"{url} speaks fakts protocol v1 (it answered a v1 descriptor with "
        f"name='{data['name']}'). fakts-next >= 5 requires protocol v2. "
        f"Pin fakts-next < 5 or upgrade the server."
    )
```

Same error when `data.get("fakts_protocol_version", "2") != "2"`.

`discover_url` (`utils.py:78-143`), `well_known.py`, `static.py`, `advertised.py` (UDP
beacon) and `qt/selectable_beacon.py` need **no code changes** — they only pass URLs through
and read `.name` / `.base_url`, which the derived fields preserve.

This also closes a live bug: lok emits `configure` / `device_code_start` / `challenge_url`
while `FaktsEndpoint` declares `configure_url` / `claim_url` / `retrieve_url`
(`grants/remote/models.py:39-44`), so pydantic silently drops all of them — which is why
`demanders/device_code.py:29` still needs its `base_url.replace("lok/f/","")` heuristic.
Standard field names remove the guessing.

### 2. Demand — `POST {device_authorization_endpoint}` (RFC 8628 §3.1)

`application/x-www-form-urlencoded`:

```
client_id=my-app
&scope=openid%20read
&fakts_manifest={"identifier":"my-app","version":"0.1.0","requirements":[...],...}
&fakts_secure=true
```

- **`client_id` is the manifest identifier.** No dynamic registration: the server
  auto-provisions a *public* client the first time it sees a `fakts_manifest` for that
  identifier, binding it to the device code at approval time. One client per app (correct
  OAuth semantics), not one per installation as v1 does — the *token* now identifies the
  installation. The manifest hash lets the server detect a changed manifest and re-prompt.
  The token response **MAY echo a different `client_id`** (so the server can namespace, e.g.
  `my-app@demo/demo`); the client must persist whatever the response carries, falling back
  to what it sent, and use that on every later refresh. This is why `RefreshAuth.client_id`
  comes from the response, not from the manifest.
- **`fakts_manifest`** carries the full manifest and is what the server renders on the
  consent screen, including individually declinable optional requirements. This is the one
  place v2 must genuinely extend OAuth: OAuth has no slot for per-resource consent.
- **`fakts_secure`** replaces the `secure` flag v1 sent on the claim request
  (`claimers/post.py:53-56`), which lets the server decide which aliases to hand out
  (`fakts/services/rendering.py` reads `context.request.is_secure`). It must not be
  dropped silently.

Response is vanilla RFC 8628 (`device_code`, `user_code`, `verification_uri`,
`verification_uri_complete`, `expires_in`, `interval`). The browser opens
`verification_uri_complete`, **deleting** the `{configure_url}{code}` heuristic.

### 3. Token — `POST {token_endpoint}`, polled (RFC 8628 §3.4/3.5)

```
grant_type=urn:ietf:params:oauth:grant-type:device_code&device_code=...&client_id=my-app
```

Polling honours the server's `interval`; RFC 8628 error codes replace the custom
`waiting`/`pending`/`granted`/`denied` envelope:

| `error` | client behaviour |
|---|---|
| `authorization_pending` | keep polling |
| `slow_down` | `interval += 5`, keep polling |
| `access_denied` | user refused → `UserDeniedError` (first-class, catchable) |
| `expired_token` | device code expired → `DeviceCodeTimeoutError` |

Success carries tokens **and** config as top-level extension members:

```json
{
  "access_token": "...", "refresh_token": "...", "token_type": "Bearer",
  "expires_in": 3600, "scope": "openid read",

  "self": {"deployment_name": "my-deployment", "alias": {}},
  "instances": {"rekuest": {"service": "...", "identifier": "...",
                            "challenge_key": {}, "aliases": []}},
  "statuses": {"rekuest": "granted", "kabinet": "denied"}
}
```

`Instance`, `Alias`, `ChallengeKey` and `GrantStatus` are byte-for-byte the v1 models.

Note the structural shift: v1 validated the config **wholesale** from the server
(`ActiveFakts(**data["config"])`, `claimers/post.py:84`). In v2 the client **assembles**
`ActiveFakts` from the discovery metadata (`token_endpoint`, `report_endpoint`,
`client_id`) plus the token response (tokens, `self`, `instances`, `statuses`). The `auth`
block is no longer something the server sends.

### 4. Renew — `grant_type=refresh_token`

Replaces the client_credentials fetch entirely. If the response repeats
`instances`/`self`/`statuses`, the client adopts them (free config updates); if it omits
them, the cached config stands.

### 5. Report — same endpoint, standard auth

`POST {fakts_report_endpoint}` with the same body, except authorization moves from the
custom `token: client_token` body field to `Authorization: Bearer <access_token>`.
`AuthFakt.client_token` disappears.

### Client and server obligations

These are normative and belong in the rewritten README, not in a code comment — the
rotation design only holds if both sides honour them.

**Servers MUST NOT apply refresh-token reuse detection to public fakts clients** (or MUST
accept the previous token for a short grace window). fakts clients are public, share a
process-local cache, and legitimately race. OAuth 2.1 recommends reuse detection with
family-wide revocation; applying it here turns a recoverable ping-pong (consequence 1) into
a hard failure needing human re-auth. lok does not implement it today
(`authapp/models.py:183-188` revokes a single row) — this obligation is what keeps it that
way deliberately rather than accidentally.

**Clients MUST persist a rotated refresh token atomically, at mode 0600, before using the
new access token.** A rotation that is used but not persisted leaves the next process start
holding a dead credential.

**Multi-process / multi-replica deployments SHOULD use `client_credentials` via `EnvGrant`**
rather than sharing a refresh-token cache.

---

## Consequences you are signing up for

Confirmed against lok's source, not assumed.

1. **Refresh tokens rotate and revoke the old one immediately.**
   `RefreshTokenGrant.INCLUDE_NEW_REFRESH_TOKEN = True` and `revoke_old_credential()` sets
   `revoked=True` (`authapp/grants.py:91-109`). Two processes sharing a `FileCache` **will**
   invalidate each other. Under client_credentials this was safe — which is exactly why
   `_aadopt_newer_cached_fakts` (`fakts.py:323-368`) exists.
   **Against lok as it stands, the re-read-cache-and-retry mitigation below is sufficient**:
   `authenticate_refresh_token` looks up a single row and `revoke_old_credential` revokes
   *that row only* (`authapp/models.py:183-188`) — there is no reuse detection and no token
   family cascade, so a stale refresh token fails in isolation and the loser of the race
   simply picks up the winner's token. The trigger that would break this: if lok later
   adopts RFC 9700-style refresh-token reuse detection, one lost race poisons the whole
   family and multi-process shared caching becomes unsupported.
2. **The cache becomes mutable credential state.** It goes from a write-once config store
   to something written on every refresh, now holding a live secret. `FileCache` writes
   atomically already (`cache/file.py:126-129`) but at the default umask — it **must** be
   tightened to `0600`.
3. **Refresh-token expiry or revocation means re-running the device flow — a human.**
   lok's refresh lifetime is a hardcoded 30 days from issuance
   (`authapp/models.py:183-188`). Because every refresh issues a fresh token, a
   continuously-running app survives indefinitely; an app **offline for more than 30 days**
   needs someone at a browser. Under v1 it could sit headless forever. This is the real
   cost of the change.
4. **Headless (`build_redeem_fakts`) inherits that cost** — mapped to an extension grant,
   but the resulting session is still refresh-token bound. A CI runner idling past the
   refresh TTL is dead, and v1 redeem tokens are single-use so it cannot self-heal. See the
   [open question](#open-question-headless-renewal) for the one escape hatch worth
   considering.
5. **The app's OAuth identity gets weaker, deliberately.** v1 minted a per-installation
   *confidential* client with a secret. v2's `client_id` is just the manifest identifier,
   which any process can send — the consent screen is the only gate. That is exactly how
   public device-flow clients are meant to work (a secret shipped in a distributed app was
   never a secret), but it is a real change and shouldn't be silent: what identifies an
   installation moves from the client credential to the token.
6. **Blast radius beyond this repo.** Other v1 clients exist and all break:
   TypeScript (`arkitektio.github.io/src/lib/arkitekt/fakts/`,
   `mobile/pokket/lib/arkitekt/fakts/`, npm `@jhnnsrs/fakts`), Rust
   (`rust/arkirust/src/fakts/fakts_protocol.rs`), and the legacy Python clients
   (`packages/fakts`, `packages/herre`, `packages/herre-next`).
   `packages/arkitekt-server`'s tests drive this package's device demander directly.

---

## Implementation

### Models — `fakts_next/models.py`

`ActiveFakts` keeps its shape (`self`, `auth`, `instances`, `statuses`) so the cache,
`EnvGrant`, `HardFaktsGrant` and every consumer keep working. Only `AuthFakt` is reshaped —
into a **discriminated union**, not a flat model with optional fields:

```python
class RefreshAuth(BaseModel):
    """Credentials obtained through a user-approved OAuth flow."""
    kind: Literal["refresh"] = "refresh"
    client_id: str                       # from the token response, see §client_id echo
    token_endpoint: str                  # was token_url
    report_endpoint: Optional[str] = None  # was report_url
    scopes: List[str] = Field(default_factory=list)  # the GRANTED scope, not the requested one
    refresh_token: str                   # live rotating secret
    access_token: Optional[str] = None   # advisory; may be stale on load
    expires_at: Optional[float] = None   # absolute unix ts
    token_type: str = "Bearer"
    secure: bool = True                  # v1's `secure` flag, persisted for refresh

class ClientCredentialsAuth(BaseModel):
    """Pre-provisioned confidential client — containers, CI, injected secrets."""
    kind: Literal["client_credentials"] = "client_credentials"
    client_id: str
    client_secret: str
    token_endpoint: str
    report_endpoint: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)

AuthFakt = Annotated[Union[RefreshAuth, ClientCredentialsAuth], Field(discriminator="kind")]
```

**Why a discriminator rather than optional fields**: `_afetch_token` runs off
`_aensure_loaded()` (`fakts.py:251`) — the *cache*, not the grant object. After a restart,
a persisted field is the only thing that can tell "refresh" from "client_credentials".

This also means **client_credentials survives, but only outside the remote flow** —
`EnvGrant` / `HardFaktsGrant` for containers and CI, where it is the *right* answer because
it has no rotation and therefore none of the race in consequence 1. The interactive remote
path never mints client credentials, as decided.

Free win: because pydantic requires the discriminator, every existing `.fakts_cache.json`
(whose `auth` has `client_token` / `client_secret` / `token_url` and no `kind`) fails
`CacheFile` validation and is already swallowed as a cache miss (`cache/file.py:97-101`).
**No cache migration code is needed.** Bumping the cache hash prefix to `v2:` is still worth
doing as belt-and-braces, so the miss doesn't depend on a swallowed exception.

Deleted: `client_token` (the report moves to `Authorization: Bearer`), `client_secret` on
the remote path. `Alias`, `Instance`, `ChallengeKey`, `GrantStatus`, `SelfFakt`,
`Requirement`, `Manifest` (incl. `hash()`) are **unchanged**. None of `AuthFakt` /
`SelfFakt` / `Instance` are in `__all__` (`__init__.py:59-83`), so the rename is internal.

### Protocol interfaces — `fakts_next/grants/remote/models.py`

- `Discovery.adiscover() -> FaktsEndpoint` — **role unchanged**; the UDP beacon
  (`discovery/advertised.py`) and Qt picker (`discovery/qt/selectable_beacon.py`) keep
  working, since they broadcast/select a *URL* and delegate to `discover_url`.
- `FaktsEndpoint` is rebuilt as AS metadata: `issuer`, `token_endpoint`,
  `device_authorization_endpoint`, `grant_types_supported`, `scopes_supported`, plus
  `fakts_protocol_version` / `fakts_deployment_name` / `fakts_report_endpoint`, with
  `extra="allow"` (RFC 8414 §2 requires unknown members to be ignorable).
  **`name` *and* `base_url` must survive as derived fields** — the Qt picker paints both
  (`qt/selectable_beacon.py:101,110`, and it declares `QtCore.Signal(FaktsEndpoint)` at
  `:63`) and the Qt token store keys on `base_url` (`demanders/qt/qt_settings_token_store.py:56,85`).
  Derive `base_url` from `issuer` and `name` from `fakts_deployment_name` (falling back to
  the issuer's netloc) in a `model_validator`. Drop `claim_url`, `retrieve_url`,
  `configure_url`, `protocol_version`, `version`.
- **`Demander` + `Claimer` collapse into one `Authorizer`**:
  `aauthorize(endpoint) -> TokenResponse`. There is no longer a two-step "get an artifact,
  then trade it" — the token endpoint does both. `grants/remote/claimers/` is **deleted**.
- `FaktsGrant.aload() -> ActiveFakts` (`protocols.py:12-39`) is unchanged.

### File-by-file

| File | Change |
|---|---|
| `grants/remote/discovery/utils.py:36,58-66` | well-known path → `oauth-authorization-server` with `openid-configuration` fallback; validity check → `issuer` + `token_endpoint`; explicit v1 detection (see below) |
| `grants/remote/discovery/well_known.py`, `static.py`, `advertised.py`, `qt/selectable_beacon.py` | mechanical: build the new `FaktsEndpoint` |
| `grants/remote/demanders/device_code.py` | rewritten as `authorizers/device_code.py`: form-encoded device request + RFC 8628 polling loop with `interval`/`slow_down`; browser opens `verification_uri_complete`; `ClientKind` / `redirect_uris` drop out |
| `grants/remote/demanders/redeem.py`, `retrieve.py`, `static.py` | → `authorizers/`; redeem becomes `grant_type=urn:fakts:params:oauth:grant-type:redeem` at the token endpoint. `retrieve.py` is dead code (no builder references it) — **delete** |
| `grants/remote/claimers/*` | **deleted** |
| `grants/remote/base.py:15-72` | `RemoteGrant` = discover → authorize → assemble `ActiveFakts` |
| `grants/remote/errors.py` | drop `ClaimError`; add `UserDeniedError` |
| `fakts_next/fakts.py:244-321` | `_afetch_token` → refresh-token grant via aiohttp; on success update `auth.*` **and write back to the cache**; adopt `instances`/`self`/`statuses` if the response repeats them |
| `fakts_next/fakts.py:323-368` | `_aadopt_newer_cached_fakts` repurposed: on `invalid_grant`, re-read the cache and retry once if it holds a *different* `refresh_token`; only then `aload(reload=True)` |
| `fakts_next/fakts.py:55-59,683-737` | report: drop `ReportRequest.token`, send `Authorization: Bearer` |
| `cache/file.py:112-129` | create the temp file with `os.open(..., O_CREAT\|O_WRONLY, 0o600)` **before** writing, plus `fsync` before `os.replace`. Order matters: `os.replace` preserves the *tmp file's* mode, so a `chmod` after the replace is both wrong-ordered and racy. `aset` is now on the hot path (every refresh) |
| `cache/qt/settings.py:27-38` | same leak, weaker fix: `QSettings` writes `~/.config/<org>/<app>.conf` at the process umask. Best-effort `os.chmod(self.settings.fileName(), 0o600)` after `aset`, and document that the Windows registry backend stores the secret unencrypted (users needing a keychain should implement `FaktsCache` over `keyring`) |
| `grants/remote/builders.py:23-33` | cache hash → `sha256(f"v2:{url}:{manifest.hash()}")`; also **delete** `build_remote_testing_with_token` (its premise — a static v1 claim token traded at `{base}claim/` — has no v2 equivalent; not exported) and switch `build_redeem_grant` from `StaticDiscovery` to `WellKnownDiscovery`, since a static endpoint would now have to guess `token_endpoint` |
| `grants/env.py`, `grants/hard.py` | **no code changes** — they just validate an `ActiveFakts`. What changes is the contract: inject `kind: "client_credentials"` into containers, never `kind: "refresh"` (an injected refresh token goes stale after the first rotation). Update the docstring example at `env.py:29` |
| `pyproject.toml:13` | **drop `oauthlib`** |
| `contrib/rath/*` | signatures unchanged, **semantics change** — see the `arefresh_token` note below |
| `README.md` protocol section | rewrite as v2; it is the normative spec |

**oauthlib vs hand-rolled — hand-roll, and drop the dependency.** This was probed against
the installed oauthlib rather than assumed, and it is not a close call:

- `parse_request_body_response('{"error":"authorization_pending"}')` raises a generic
  `CustomOAuth2Error`, **not** `AuthorizationPendingError`. `raise_from_error`
  (`oauthlib/oauth2/rfc6749/errors.py:390-399`) only scans classes in the *rfc6749* errors
  module, while the RFC 8628 classes live in `rfc8628/errors.py` and are never found. Same
  for `slow_down`. So the device-flow state machine — the one thing worth importing
  oauthlib for — has to string-match `e.error` anyway.
- `parse_request_body_response(<valid token>, scope=[...])` raises a bare `Warning` when the
  granted scope differs from the requested one (`parameters.py:463-473`), unless
  `OAUTHLIB_RELAX_TOKEN_SCOPE` is set. v2's entire selling point is per-requirement
  declinable consent — granted scope differing from requested is the *normal* case. Live
  landmine.
- `prepare_refresh_token_request` raises `InsecureTransportError` on `http://localhost:...`
  (`utils.py:79-83`) unless `OAUTHLIB_INSECURE_TRANSPORT` is set — and localhost http is this
  package's primary dev target.

Today's code sidesteps all of this because `fakts.py:262` only uses `prepare_request_body`
plus a manual `session.post` — it is already 90% hand-rolled. The residual value (parsing
`expires_in` → `expires_at`) is four lines. Verified safe to drop:
`grep -rn oauthlib fakts_next/ tests/` returns exactly the three imports at `fakts.py:11-13`,
all inside the code being replaced.

Introduce a shared `fakts_next/oauth2.py` (`apost_form`, `OAuth2ErrorResponse`,
`TokenResponse`, `to_active_fakts`, grant-type constants) imported by *both* `fakts.py`
(runtime refresh) and the authorizers — this keeps `fakts.py` from importing
`grants.remote.*`.

**`arefresh_token` must never open a browser.** rath calls `FaktsAuthLink.arefresh_token`
(`contrib/rath/auth.py:16-19`) on a 401. In v1 that re-ran client_credentials and always
succeeded unattended. In v2 it runs the refresh grant, and the existing `invalid_grant`
fallback at `fakts.py:308` is `aload(reload=True)` → `DeviceCodeAuthorizer` → **a browser
opening in the middle of a GraphQL request**. Under v1's client_credentials that path was a
rare edge case; under rotating refresh tokens it becomes a scheduled event.

Add a `Fakts.allow_interactive_reauth: bool = True` field so daemons can opt out, and a
`NeedsReauthenticationError`. Recovery ladder on `invalid_grant`:

1. re-read the cache (bounded retry, ~3× 0.25s — the peer process may still be in flight);
   if it holds a *different* refresh token, adopt it and retry once;
2. else if `not allow_interactive_reauth` → raise `NeedsReauthenticationError`;
3. else `aload(reload=True)` and retry once with `allow_reload=False`.

**Lock ordering (new edge).** The report now calls `aget_token()`, and `_areport_aliases` is
reached from `arefresh_aliases` under `_alias_lock` (`fakts.py:795`) while `aget_token` takes
`_token_lock` (`:394`) which can take `_load_lock` (`:307-308, :337`). The established order
becomes **alias → token → load**. It is consistent today (nothing on the token path takes
`_alias_lock`), but this is the first alias→token edge and needs a comment. Put the
`aget_token()` call *inside* the existing `try/except` (`:705-737`) so telemetry can never
break alias resolution.

**Token lifetime semantics must be explicit.** v1 got `expires_at` from oauthlib and
`_token_is_valid()` treats `None` as "valid" (`fakts.py:370-376`). Hand-parsing the response
means spelling out the edge cases, and lok's own value is unverified — it passes no
`expires_generator` (`authapp/server.py:71-74`) and `OAuth2Token.expires_in` defaults to `0`
(`authapp/models.py:159`). Rules: `expires_in` **absent** → leave `expires_at = None`, treat
the token as opaque and refresh only on a 401; `expires_in` **≤ 0 or smaller than
`TOKEN_EXPIRY_SKEW`** → also `None`, never `expires_at = now`, which would turn every
`aget_token()` into a refresh round-trip; otherwise `expires_at = now + expires_in`.

**Unchanged**: `challenge.py` (Ed25519 signed alias challenge), all of alias resolution and
reporting logic in `fakts.py:405-737`, `Manifest.hash()` cache invalidation, the koil
sync/async wrappers, `helpers.py`, `cache/qt/settings.py`, `cache/nocache.py`.

### Server-side work (lok)

Hard dependency — must land before or with the client.

1. `authapp/server.py:31-33` — `server.register_grant(DeviceCodeGrant)` +
   `server.register_endpoint(DeviceAuthorizationEndpoint)` from `authlib.oauth2.rfc8628`.
2. `authapp/grants.py:92` — `RefreshTokenGrant.TOKEN_ENDPOINT_AUTH_METHODS` is
   `["client_secret_basic", "client_secret_post"]`; device-flow clients are **public**, so
   `"none"` must be accepted or every refresh fails. Easy to miss.
3. `authapp/token_generators.py` — override `generate()` to merge `self` / `instances` /
   `statuses` into the response body, reusing `fakts/services/rendering.py:66-96` minus
   `auth_claim`.
4. Handle `fakts_manifest` + `fakts_secure` on the device authorization request:
   auto-provision the public client, store the manifest against the device code, render
   per-requirement consent at the verification URI.
5. `authapp/views.py:80-101` — add `device_authorization_endpoint`, the device grant type,
   `"none"` in `token_endpoint_auth_methods_supported`, and the `fakts_*` members; route
   the same view at `/.well-known/oauth-authorization-server`.
6. Redeem extension grant replacing `POST /f/redeem/` (`fakts/views.py:268-323`).
7. `POST /f/report/` (`fakts/views.py:369-384`) authenticates by Bearer, not `client_token`.
8. `/f/start/`, `/f/challenge/`, `/f/claim/` are deleted. lok's **mesh/hub** flows reuse the
   same custom vocabulary and stay on it — out of scope, but they must keep working.

### Tests

Verified gap: `grep -rn "aget_token\|_afetch_token\|arefresh_token" tests/` returns
**nothing** — the token path has zero coverage today. It becomes the most security-sensitive
part of the client, so this is the largest new surface.

**Start here — one edit fixes three files.** `make_fakts_value()`
(`test_fakts_behavior.py:30-53`) is imported by `test_remote_http.py:22`, `test_cache.py:15`
and `test_env_and_builders.py:19`. Rewriting its `AuthFakt(...)` block (lines 36-42) into a
`RefreshAuth(...)` unblocks all of them at once; add a `make_client_credentials_value()`
sibling for the Env/Hard path.

**Rewrite** — `test_remote_http.py:60-141` (the `ClaimEndpointClaimer` block: delete,
replace with device-flow tests against the token endpoint) and `:148-243` (redeem: handlers
now read `await request.post()` for form data, not `await request.json()`) against the
existing `local_server` aiohttp fixture (`:30-52`, reusable as-is); `:251-330` (discovery:
`{"name": ...}` → `{"issuer", "token_endpoint"}`); `test_fakts_behavior.py:493-525` (both
`_aadopt_newer_cached_fakts` tests compare `client_id`/`client_secret` → refresh-token
comparison) and `:374-399` (`auth.report_url` → `report_endpoint`);
`test_redeem_code.py:37,52-53`; `test_env_and_builders.py:80-83,126-127`
(`fakts.grant.demander` → `fakts.grant.authorizer`);
`test_device_code.py` / `test_device_code_node.py` (integration; the `authorize_through_cmd`
hook signature changes and they need a v2 lok image plus a v2 equivalent of
`manage.py validatecode`). **The integration suite stays red until the server ships v2** —
flag that in the PR rather than treating it as a client bug.

**New**:

- device polling: `authorization_pending` loop, `slow_down` bumping the interval,
  `access_denied` → `UserDeniedError`, `expired_token` → `DeviceCodeExpiredError`, overall
  deadline → `DeviceCodeTimeoutError`. Give the authorizer an injectable
  `sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep` field so the `slow_down`
  test asserts the sleep sequence `[5, 10]` instead of burning 15 seconds of wall clock.
- `verification_uri_complete` is what gets opened: monkeypatch `webbrowser.open_new` and
  assert the v1 `{configure_url}{code}` heuristic is gone.
- a v1 `.well-known/fakts`-only server yields a `DiscoveryError` naming protocol v1.
- a literal v1 `CacheFile` JSON is a miss (`aload() is None`), not a crash.
- `client_credentials` still works via `EnvGrant`: HTTP Basic + `grant_type=client_credentials`,
  and no refresh is ever attempted.
- the report sends `Authorization: Bearer` and no `token` key in the body.
- refresh: success updates `auth.*` **and** rewrites the cache; rotation persists the new
  refresh token.
- `invalid_grant` → adopt a different refresh token from the cache and retry once;
  `invalid_grant` with no newer cache entry → full `aload(reload=True)`.
- token lifetime: a local server returning `expires_in` of `3600`, `0`, and absent — assert
  the refresh decision for each (no lok needed).
- `arefresh_token()` raises `ReauthenticationRequiredError` and does **not** invoke the
  interactive authorizer.
- cache file mode is `0600` after `aset`.

**Unchanged**: `test_challenge.py` (Ed25519), `test_qt_settings_cache.py`,
`test_helpers_and_utils.py`.

### Open question: headless renewal

You chose "no client_credentials in the remote flow", and the plan above honours that. One
option would partially re-open that door and is worth an explicit yes/no rather than a
silent decision:

> The server MAY answer the **redeem** grant with a `fakts_client_secret` member, in which
> case the client builds a `ClientCredentialsAuth` instead of a `RefreshAuth`.

That would restore the exact v1 property headless users depend on — mint tokens forever, no
human, no rotation race — for the one grant where no human is involved anyway. It costs one
branch in `to_active_fakts` and re-introduces a client secret on a path you asked to be
refresh-only.

If the answer is no, the fallback is that servers should issue **multi-use** redeem tokens,
so `aload(reload=True)` can self-heal the headless path non-interactively (redeem is the one
grant where automatic re-auth is safe, so `allow_interactive_reauth` need not gate it).

### Follow-up, not in v2

An inter-process lock (`fcntl.flock` on a sibling `.lock` file, POSIX only) around
read→refresh→write is the *real* fix for the rotation race — exposed as
`FileCache(lock=True)` plus an `aupdate(mutator)` capability on the `FaktsCache` protocol.
The v2 baseline ships adopt-and-retry plus the documented obligations instead; adopt-and-retry
converges probabilistically, and with many processes on a short access-token TTL it can
degrade into repeated `invalid_grant` churn.

### Migration

**Clean break, no v1 fallback.** A dual-protocol client would have to keep the entire
claim/demand chain alive for the one release where it matters, and the v1 path cannot
produce a refresh token anyway. Instead: bump the cache hash prefix to `v2:` so old caches
miss deterministically, and fail v1 servers with an explicit protocol-version error. Every
app re-runs the device flow once on upgrade — unavoidable, since v2 needs a token v1 never
issued.

---

## Verification

1. `uv run pytest tests/ -m "not integration"` — unit suite, including the new token-path
   tests driven by the local aiohttp server.
2. `uv run basedpyright` — the package is under `standard` type checking; the model reshape
   must stay clean.
3. Cache hygiene: after a flow, assert `stat(".fakts_cache.json").st_mode & 0o777 == 0o600`
   and that the persisted `refresh_token` changes after a forced `arefresh_token()`.
4. Integration against a v2 lok build: point `LOK_SERVICE_TAG` at it and run
   `uv run pytest tests/test_device_code.py tests/test_redeem_code.py -m integration`
   (`tests/conftest.py:26-60` brings the stack up via dokker). The end-to-end assertion
   stays the same — `alias.challenge_path == "http://localhost:6888/ht"` — which is the
   point: the negotiation changed, the outcome did not.
5. Manual smoke: `build_device_code_fakts` against local lok; confirm the browser opens
   `verification_uri_complete` (not a derived `configure/` URL), then re-run and confirm the
   cache path is silent.
6. Refresh path: driven by the local `aiohttp` fixture rather than lok (lok has no
   access-token lifetime knob in this checkout). Hold a `Fakts` context open past a
   server-declared expiry and confirm `aget_token()` refreshes, persists the rotated
   refresh token, and never re-prompts.
