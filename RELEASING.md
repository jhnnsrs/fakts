# Releasing fakts-next

`fakts-next` ships as a PyPI package (`fakts-next`). Versioning is automated by
[python-semantic-release][psr] from [Conventional Commits][cc] — you never bump
the version by hand. A push to a release branch runs
`.github/workflows/release.yaml`, which:

1. runs the test suite,
2. computes the next version from the commit history, bumps `pyproject.toml`,
   updates `CHANGELOG.md`, tags `vX.Y.Z`, and cuts a GitHub Release,
3. builds the wheel and, **only if a release was cut**, uploads it to PyPI via
   trusted publishing (OIDC).

## Commit messages drive the version

| Commit prefix | Bump | Example |
| --- | --- | --- |
| `fix:` | patch | `fix: handle expired token` |
| `feat:` | minor | `feat: add device-code grant` |
| `feat!:` / `BREAKING CHANGE:` footer | **major** | `feat!: new api` |

Commits that aren't releasable (`chore:`, `docs:`, `refactor:` …) don't trigger
a release on their own.

## Branches

| Branch | Releases | PyPI |
| --- | --- | --- |
| `main` | stable `X.Y.Z` | the default install (`pip install fakts-next`) |
| `next` | prereleases `X.Y.Z-rc.N` | published as a **prerelease** — only reached via `pip install fakts-next --pre` or an exact pin |
| `N.x` (e.g. `4.x`) | maintenance `X.Y.Z` | published stable for an older major |

PyPI marks `…-rc.N` versions as prereleases, so a plain `pip install fakts-next`
never picks them up — `next` is a safe soak channel.

## Tag-based integration backends

`fakts-next` has no backend image of its own — its integration stack stands up
the **lok** auth server and a **rekuest** backend. `integration.yaml` runs on
`main` and `next` and sets `LOK_SERVICE_TAG` and `REKUEST_SERVICE_TAG` (both
`latest` on `main`, `next` elsewhere). `tests/integration/docker-compose.yml`
resolves them per service via `jhnnsrs/lok:${LOK_SERVICE_TAG:-next}` and
`jhnnsrs/rekuest:${REKUEST_SERVICE_TAG:-next}`, so the prerelease line is tested
against the prerelease backends and the stable line against `:latest`. Keeping
the tags split lets you pin one backend independently of the other.

## Day-to-day

- **Patch/feature for the current line:** merge a `fix:`/`feat:` PR into `main`.
  PSR cuts the next stable release and publishes it to PyPI.
- **Anything risky / breaking:** land it on `next` first. Each push cuts a fresh
  `…-rc.N` and publishes it as a PyPI prerelease so you can soak it. Promote by
  merging `next` → `main`.

## Working on a new major (v5)

```
next   feat!: …      -> 5.0.0-rc.1, 5.0.0-rc.2 …   (PyPI prereleases)
              │ merge main into next regularly to keep the rc base correct
main   ──4.0.0──(merge next)──> 5.0.0 -> 5.0.1 …    (stable PyPI)
          │ cut `4.x` from main HEAD *before* the 5.0.0 merge
4.x    ──4.0.0──> 4.0.1 -> 4.0.2 …                  (stable PyPI for v4)
```

1. **Develop v5 on `next`.** Land `feat!:` / `BREAKING CHANGE:` commits there.
   PSR cuts `5.0.0-rc.N` as PyPI prereleases. Periodically merge `main` → `next`
   so the rc base stays at the latest v4.
2. **Cut the maintenance branch first.** Right before promoting, branch `4.x`
   from `main` HEAD (still at the last v4 commit):
   ```sh
   git checkout main && git pull
   git checkout -b 4.x && git push -u origin 4.x
   ```
3. **Promote v5.** Merge `next` → `main`. The breaking change makes PSR cut
   stable `5.0.0`.

## Backporting a fix to v4 (after v5 has shipped)

Branch off `4.x`, PR the fix into `4.x` with a `fix:` commit. PSR cuts the next
patch and publishes it to PyPI. Forward-port the same fix to `main`/`next` if it
also applies there.

## Consuming the next channel

```sh
pip install fakts-next --pre          # latest rc (or stable, whichever is newer)
pip install 'fakts-next==5.0.0-rc.1'  # pin a specific rc
```

Stable consumers (`pip install fakts-next`) are unaffected by the `next` channel.

## Dry-running locally

`python-semantic-release` is in the dev group, so you can preview the version a
branch would cut without pushing anything:

```sh
uv run semantic-release version --print   # prints the next version, makes no changes
```

[psr]: https://python-semantic-release.readthedocs.io/
[cc]: https://www.conventionalcommits.org/
