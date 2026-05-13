# rw-base-runtime

The complete RunWhen runtime container image. Every codecollection image
should `FROM` this image.


## What's inside

- Python 3.14 on `slim-bookworm`
- The RunWhen worker binary (copied out of the published `runner-worker` image)
- [`rw-core-keywords`](https://pypi.org/project/rw-core-keywords/)
  installed system-wide. Codecollections can `import RW.Core` / `import RW.Utils`
  without any extra setup.
- Helper scripts at `/home/runwhen/robot-runtime/` that wire the worker
  to robotframework:
  - `entrypoint.sh` (default `ENTRYPOINT`)
  - `runrobot.sh`, `runrobot.py`
  - `RWP.py`
  - `metrics_daemon.py`, `process_metrics.py`, `runtime_metrics.py`
- Standard cloud / cluster CLIs: `kubectl`, `aws`, `helm`, `az`,
  `kubelogin`, `gcloud` (+ `gke-gcloud-auth-plugin`), `istioctl`, `pwsh`,
  `gh`, `jq`, `yq`, `jp`, `skopeo`, `git`.
- AI / workflow CLIs that codecollections may want to invoke from a task:
  `linear-cli` (Finesssee/linear-cli, built from crates.io against
  bookworm glibc), `claude` (Claude Code, standalone binary), `cursor`
  (Cursor CLI / `cursor-agent`).

## Layout

```
.
├── Dockerfile              # single multi-stage build
├── requirements.txt        # rw-core-keywords + psutil
├── scripts/                # helper scripts -> /home/runwhen/robot-runtime/
├── examples/               # otel-collector samples
├── docs/
│   ├── RUNTIME_METRICS.md  # what metrics_daemon exports
│   └── DEBUG.md
└── .github/workflows/build-push.yaml
```

## Building locally

```sh
docker build -t ghcr.io/runwhen-contrib/rw-base-runtime:dev .
```

Override the worker image (e.g. to pick up a PR build of the worker):

```sh
docker build \
  --build-arg WORKER_IMAGE=us-docker.pkg.dev/.../runner-worker:pr-123-abc \
  -t ghcr.io/runwhen-contrib/rw-base-runtime:dev .
```

## Consuming this image from a codecollection

Codecollections should pin a specific image tag rather than `:latest` in
their own `Dockerfile`:

```Dockerfile
ARG BASE_IMAGE=ghcr.io/runwhen-contrib/rw-base-runtime:latest
FROM ${BASE_IMAGE}

COPY --chown=runwhen:0 . /home/runwhen/collection
RUN if [ -f /home/runwhen/collection/requirements.txt ]; then \
      pip install --no-cache-dir -r /home/runwhen/collection/requirements.txt ; \
    fi
```

The codecollection contents MUST land at `/home/runwhen/collection` (not
`/codecollection`). PAPI emits `RW_PATH_TO_ROBOT=$(RUNWHEN_HOME)/collection/codebundles/...`
and `runrobot.{sh,py}` only resolve paths under `/home/runwhen/collection`,
so a mismatch here will surface as `FileNotFoundError: Could not find the
robot file in any known locations.` at runtime.

The codecollection-registry `OCISource` and the
[radically-simple-design](https://github.com/runwhen/platform-robot-runtime/blob/main/docs/migration/radically-simple-design.md)
tag schema embed the base-runtime commit sha into the codecollection
image tag suffix (`<ref>-<cc_sha>-<rt_sha>`), so PAPI can always tell
which runtime a given codecollection image was built against.

## Image tagging

Pushed to `ghcr.io/runwhen-contrib/rw-base-runtime` by
`.github/workflows/build-push.yaml`. Tags:

| Tag           | When                                                              |
|---------------|-------------------------------------------------------------------|
| `<sha>`       | every push and PR — full commit sha                               |
| `<sha7>`      | every push and PR — first 7 of the commit                         |
| `main`        | push to `main`                                                     |
| `latest`      | push to `main`                                                     |
| `pr-<n>`      | pull_request events                                                |
| `v<x.y.z>`    | git tags matching semver                                           |

Codecollections (and the CC image catalog in cc-registry-v2) treat
`<rt_sha>` as the commit pinned in the tag suffix.
