# Alias selection

A service is usually reachable at several addresses: `localhost` on the hub's own
machine, a name on the hub's docker network, a LAN address, the organization's mesh, a
public domain. Each is an **alias**. This page explains which one a fakts client uses,
and who decides.

In short: **the hub's owner ranks the aliases, the client follows that ranking, and the
client may narrow it with its own policy.** The client's challenge decides what it can
actually reach, and a safety floor that no server can relax decides where plain HTTP is
allowed.

## Who decides, in order

| Layer | Decided by | Can |
|---|---|---|
| 1. Safety floor | fakts itself | Refuse plain HTTP outside loopback, the deployment's network and the mesh, on a [strict instance](#the-safety-floor) |
| 2. Client policy | whoever runs the client | Drop aliases by reach or id; try some reaches first |
| 3. Server policy | the hub's owner, on Lok | Rank aliases, switch them off, and do either for some clients only |
| 4. Built-in rules | fakts itself | Where the client runs: docker-only aliases inside a container, mesh aliases once a node is up |

An earlier layer wins where they disagree. Neither the client nor the server can add an
alias: the client only ever chooses among what the server handed it.

## Reach

Every alias says where its address works:

| `reach` | The address works | Example |
|---|---|---|
| `loopback` | on this machine | `http://localhost:2754` |
| `internal` | inside the deployment's own (docker) network | `http://gateway:80` |
| `lan` | on the local network | `https://10.0.0.4:2755` |
| `mesh` | on the organization's mesh | `http://hub.tailnet.ts.net` |
| `public` | on the internet | `https://lab.example.org` |

konstruktor sets it for every alias it registers; Lok derives it for older rows.

## The server's ranking

Lok hands every alias with a `priority`, lower first, and sends an instance's aliases
already sorted by it. Unless the hub's owner set one, the priority comes from the reach:

| Reach | plain HTTP | HTTPS |
|---|---|---|
| internal | 10 | 11 |
| loopback | 20 | 21 |
| lan | 31 | 30 |
| mesh | 40 | 41 |
| public | 51 | 50 |

Closest first. Where the connection never leaves the machine or the deployment's
network, plain HTTP comes before HTTPS, so clients there need no certificate at all;
everywhere else HTTPS comes first.

In kontrol the hub's owner can:

- **set an alias's priority**, or clear it to go back to the reach default;
- **switch an alias off**: no client is handed it;
- **add a rule** that switches an alias off, or gives it another priority, for
  one client, every client of an app, every client of a user, or every client of
  a member holding a role. Where several rules name the same alias, the most specific
  wins (client, then app, then user, then role), and at the same level switching off
  beats re-ranking.

A hub authorizing again with the same aliases never overwrites what the owner set.

Switching an alias off is routing, not access control: anyone who knows the address can
still reach it. Tokens and scopes decide who may use a service.

## The client's policy

A client can say which aliases it uses, on top of the server's ranking:

| Setting | Environment | `arkitekt run` | Effect |
|---|---|---|---|
| `prefer_reach` | `FAKTS_ALIAS_PREFER_REACH` | `--prefer-reach` (repeatable) | Try these reaches first, in this order; the server's ranking decides within each |
| `exclude_reach` | `FAKTS_ALIAS_EXCLUDE_REACH` | `--exclude-reach` (repeatable) | Never use aliases of these reaches |
| `exclude_aliases` | `FAKTS_ALIAS_EXCLUDE` | | Never use these alias ids |

Environment values are comma-separated. In code:

```python
from fakts import AliasPolicy, Fakts

fakts = Fakts(
    grant=...,
    manifest=...,
    alias_policy=AliasPolicy(prefer_reach=["public"], exclude_reach=["mesh"]),
)
```

`alias_policy` defaults to what the environment says. On the command line, a flag
replaces what the environment says about the same thing and keeps the rest:

```bash
# A laptop that should use the public address, even when it sits on the hub's LAN
arkitekt run prod app:app --prefer-reach public

# Never go over the internet
FAKTS_ALIAS_EXCLUDE_REACH=public arkitekt run prod app:app
```

A policy never makes a service reachable that otherwise is not: a preferred reach
without a working alias falls through to the next one. When a policy excludes every
alias of a required service, the error says so.

## The safety floor

An instance whose hub registered its certificate with the coordination server is
**strict**: its HTTPS aliases are verified by that certificate alone, and its plain-HTTP
aliases are used only where plain HTTP never leaves this machine, the deployment's own
network or the mesh:

| Plain HTTP alias | On a strict instance |
|---|---|
| `loopback`, `internal` | used: the traffic stays on this machine or in the deployment |
| `mesh` | used: the mesh encrypts it |
| `lan`, `public` | not used: tokens and storage credentials would cross the network readable |

So a client on the hub's own machine talks plain HTTP to `localhost` and needs no
certificate, while a client across the LAN uses the hub's HTTPS address, pinned to the
hub's certificate. Only `allow_insecure_transport` on the client changes how credentials
may travel; no server setting does.

## How the aliases are tried

For each required service, fakts:

1. drops what the safety floor and the client's policy rule out;
2. orders the rest: the client's preferred reaches first, then the server's priority,
   then, among aliases ranked alike, the one that worked last time, then the server's
   order;
3. challenges the first alone for `alias_head_start` (0.3 s). If it answers, that is
   the only request;
4. otherwise challenges all the others alongside it. Of those that pass, the one ranked
   highest wins. Aliases that do not answer cost one `alias_challenge_timeout` (3 s)
   between them, not one each.

Two facts only the client knows still apply: an `internal` alias is tried first inside a
container and last anywhere else, and a mesh alias waits until the others failed unless
the mesh node already runs (see [mesh-only services](../README.md#mesh-only-services)).

The chosen alias is kept for the process. It is challenged again after a failure, or
when a refresh changes the instance (an owner who re-ranks an alias changes it). The
alias that worked is remembered in the cache as the instance's `preferred_alias`, and
only breaks ties among aliases the server ranks alike: it never jumps the owner's
ranking.

### An example

The lab hub's mikro has four aliases. A Mac on the LAN and a script on the hub's own
machine both follow the default ranking:

| Alias | Reach | Priority | Mac on the LAN | Script on the hub |
|---|---|---|---|---|
| `http://gateway:80` | internal | 10 | not a container: tried last | not a container: tried last |
| `http://localhost:2754` | loopback | 20 | refused at once | **answers within the head start** |
| `https://10.0.0.4:2755` | lan | 30 | **answers** | not asked |
| `https://lab.example.org` | public | 50 | answers later, loses | not asked |

## Other clients

arkirust, arkitekt-kotlin and orkestrator follow the same ranking and the same
`FAKTS_ALIAS_*` variables (orkestrator has no client policy). arkirust and
arkitekt-kotlin try aliases one after another rather than racing them, so an address
that silently drops packets costs them a full timeout before the next is tried.
Clients that predate `priority` still follow the server, since Lok sends the aliases in
order.
