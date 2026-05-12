# rw-base-runtime — AI Coding Guidelines

This repo produces a single container image: the production RunWhen
runtime that every codecollection's image is expected to `FROM`.

## Design invariants

These are the rules that justify the existence of this repo. Don't break
them without a paired discussion in the migration docs.

1. **Single complete image, no split.** This image replaces the old
   split between `robot-runtime-base-image` (base) and the
   `build-artifacts/dockerfile` runtime layer in
   `platform-robot-runtime`. Do not re-introduce a separate "base" tag
   — codecollections pin one image and that image must be runnable on
   its own.
2. **Helper scripts are colocated with the image.** `entrypoint.sh`,
   `runrobot.{sh,py}`, `RWP.py`, `metrics_daemon.py`, `process_metrics.py`,
   `runtime_metrics.py`, and `debug_vault_token_cache.py` are checked
   into `scripts/` and copied to `/home/runwhen/robot-runtime/` at build
   time. They are NOT pulled at runtime; the image is reproducible
   from this repo + the pinned worker image.
3. **`rw-core-keywords` is the single source of truth for `RW.Core` /
   `RW.Utils`.** Never reintroduce an in-tree `RW/` directory, even for
   dev convenience. Anything that needs to change in the keyword
   library lives in `runwhen-contrib/rw-core-keywords` and is consumed
   via PyPI.
4. **CLI tools are added when codecollections will call them, not for
   human convenience alone.** Anything a Robot Framework task or
   keyword might shell out to belongs here (cloud SDKs, registry
   tools, AI/workflow CLIs like `linear-cli`, `claude`, `cursor`).
   Tooling that only helps humans author codebundles (Taskfile,
   terraform, IDE helpers, language servers) belongs in
   `codecollection-devtools` instead. When in doubt: if a codebundle
   would `Run Process ... <tool>` against it, install it here.
5. **The image is one stable user (`runwhen`, gid `0`) and one writable
   `${RUNWHEN_HOME}`.** OpenShift random-UID compatibility is handled
   by `entrypoint.sh` `create_system_user_if_missing`; do not regress.
6. **Worker binary is pulled from a published worker image, not from a
   GitHub Release or GCS object.** This keeps the worker's supply
   chain identical to every other multi-arch container we ship. The
   `WORKER_IMAGE` build arg is the lever for swapping versions.

## Relationship to `platform-robot-runtime`

`platform-robot-runtime` is still authoritative for the Python helper
scripts. When something needs to change in `metrics_daemon.py` or
`runrobot.py`:

- Make the change in `platform-robot-runtime/build-artifacts/` first.
- Copy the resulting file into `scripts/` here.
- Commit both in lockstep until the helpers physically move to this repo.

This dual-write is the only reason `platform-robot-runtime` still
exists for our purposes; we will collapse it once consumers are off
the legacy `robot-runtime-base-image` tag.

## Versioning & release flow

- Pushed to `ghcr.io/runwhen-contrib/rw-base-runtime` by
  `.github/workflows/build-push.yaml`.
- Tags described in `README.md` "Image tagging".
- `cc-registry-v2`'s image catalog (the radically-simple-design plan)
  reads our tag suffix verbatim — never invent a new tag schema here.

## Common edits

- **New CLI tool**: add a single `RUN ...` block in the Dockerfile and
  document it in the README. Verify it cross-arch installs by checking
  with both `ARCH_BIN=amd64` and `ARCH_BIN=arm64` paths.
- **Bumping `rw-core-keywords`**: just bump the floor in
  `requirements.txt`. CI rebuild will pick it up.
- **Changing a helper script**: edit in `scripts/`, smoke-test the
  resulting image (the GH workflow exec's `runrobot.sh --help`-style
  checks; extend that step if you add a new entry point).

## Testing

- The CI build runs a smoke step that boots the image with
  `WORKER_MODE_RUNNER=false` and verifies the metrics daemon comes up
  and `RW.Core` is importable. Don't bypass that check.
- For local validation: `docker run --rm rw-base-runtime:dev python3 -c "import RW.Core, RW.Utils"`.
