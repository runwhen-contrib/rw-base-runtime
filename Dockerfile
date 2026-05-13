# syntax=docker/dockerfile:1.7
#
# rw-base-runtime — the complete RunWhen runtime image.
#
# This image is what every codecollection image should `FROM`. It carries:
#   - Python 3.14 on slim-bookworm
#   - The RunWhen worker binary (pulled from a publishable worker image)
#   - rw-core-keywords (and everything it transitively pulls in)
#   - The helper scripts that wire the worker to robotframework
#       (entrypoint.sh, runrobot.{sh,py}, RWP.py, metrics_daemon.py, ...)
#   - The standard production CLI tooling (kubectl, aws, az, helm, gcloud,
#     skopeo, jq, yq, pwsh, gh, kubelogin, istioctl, terraform-free)
#
# Build args you can override:
#   BASE_PY_IMAGE   – upstream python image (defaults to a pinned slim-bookworm)
#   WORKER_IMAGE    – container image to extract /bin/worker from
#   CLOUD_SDK_VERSION – gcloud SDK pin
#
# Build:
#   docker build -t ghcr.io/runwhen-contrib/rw-base-runtime:dev .
#
# Codecollection consumption (example):
#   ARG BASE_IMAGE=ghcr.io/runwhen-contrib/rw-base-runtime:latest
#   FROM ${BASE_IMAGE}
#   COPY --chown=runwhen:0 . /home/runwhen/collection
#   RUN pip install --no-cache-dir -r /home/runwhen/collection/requirements.txt
#
# The codecollection MUST land at /home/runwhen/collection — that path is
# what PAPI's RW_PATH_TO_ROBOT references and what runrobot.sh / runrobot.py
# resolve against. PYTHONPATH below adds ${RUNWHEN_HOME}/collection and
# ${RUNWHEN_HOME}/collection/libraries for the same reason.

ARG BASE_PY_IMAGE=python:3.14.2-slim-bookworm
ARG WORKER_IMAGE=us-docker.pkg.dev/runwhen-nonprod-shared/public-images/runner-worker:2026-02-20.1
ARG CLOUD_SDK_VERSION=532.0.0
ARG LINEAR_CLI_VERSION=0.3.22

###############################################################################
# Stage 1: worker — copy the binary out of the published worker image so we
# don't depend on a heavy multi-arch image at runtime.
###############################################################################
FROM ${WORKER_IMAGE} AS worker

###############################################################################
# Stage 2: linear-cli-build — compile Finesssee/linear-cli from crates.io.
#
# The upstream prebuilt release links against GLIBC 2.39, but our runtime
# stage is on bookworm (glibc 2.36). Compiling here against bookworm's
# glibc gives us a binary that runs in the final stage.
###############################################################################
FROM rust:1-slim-bookworm AS linear-cli-build
ARG LINEAR_CLI_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install linear-cli --version ${LINEAR_CLI_VERSION} --locked --root /opt/linear-cli

###############################################################################
# Stage 3: runtime — everything the codecollection layer expects to find.
###############################################################################
FROM ${BASE_PY_IMAGE}

ARG CLOUD_SDK_VERSION

# ---------------------------------------------------------------------------
# Non-root user
# ---------------------------------------------------------------------------
ENV RUNWHEN_HOME=/home/runwhen
RUN groupadd -r runwhen && \
    useradd -r -g runwhen -d ${RUNWHEN_HOME} -m -s /bin/bash runwhen && \
    mkdir -p ${RUNWHEN_HOME} && \
    chown -R runwhen:runwhen ${RUNWHEN_HOME}

WORKDIR ${RUNWHEN_HOME}

# ---------------------------------------------------------------------------
# OS packages — keep this single layer so the apt cache is dropped in one shot.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget gnupg2 apt-transport-https lsb-release \
        git unzip jq bc bsdmainutils dnsutils default-mysql-client \
        openssh-client entr vim \
        htop lsof strace psmisc procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /usr/share/info /var/cache/man

# ---------------------------------------------------------------------------
# Architecture detection — sourced by later install steps.
# ---------------------------------------------------------------------------
RUN ARCH=$(uname -m) && \
    if   [ "$ARCH" = "x86_64"  ]; then echo "ARCH_BIN=amd64" >  /tmp/arch_vars; echo "AWS_ARCH=x86_64"  >> /tmp/arch_vars; \
    elif [ "$ARCH" = "aarch64" ]; then echo "ARCH_BIN=arm64" >  /tmp/arch_vars; echo "AWS_ARCH=aarch64" >> /tmp/arch_vars; \
    else echo "Unsupported architecture: $ARCH"; exit 1; \
    fi && cat /tmp/arch_vars

# ---------------------------------------------------------------------------
# jp + yq (small, no dependency)
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    JP_ARCH="$ARCH_BIN" && \
    curl -fsSL "https://github.com/jmespath/jp/releases/download/0.2.1/jp-linux-${JP_ARCH}" -o /usr/local/bin/jp && \
    chmod +x /usr/local/bin/jp && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${ARCH_BIN}" -o /usr/bin/yq && \
    chmod +x /usr/bin/yq

# ---------------------------------------------------------------------------
# kubectl
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)" && \
    curl -fsSLO "https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH_BIN}/kubectl" && \
    curl -fsSLO "https://dl.k8s.io/${KVER}/bin/linux/${ARCH_BIN}/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check && \
    chmod +x kubectl && mv kubectl /usr/local/bin && rm kubectl.sha256

# ---------------------------------------------------------------------------
# AWS CLI v2
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip && \
    (cd /tmp && unzip -q awscliv2.zip && ./aws/install) && \
    rm -rf /tmp/awscliv2.zip /tmp/aws

# ---------------------------------------------------------------------------
# Helm (latest stable, with a pinned fallback if the API rate-limits us)
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    HELM_VERSION="$(curl -fsSL https://api.github.com/repos/helm/helm/releases/latest | jq -r '.tag_name')" && \
    HELM_URL="https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH_BIN}.tar.gz" && \
    if ! curl -fsSL -o /tmp/helm.tar.gz "${HELM_URL}"; then \
        HELM_VERSION="v3.18.6"; \
        curl -fsSL -o /tmp/helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH_BIN}.tar.gz"; \
    fi && \
    tar -zxf /tmp/helm.tar.gz -C /tmp && \
    mv /tmp/linux-${ARCH_BIN}/helm /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    rm -rf /tmp/helm.tar.gz /tmp/linux-${ARCH_BIN}

# ---------------------------------------------------------------------------
# Azure CLI + kubelogin
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    curl -sL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/trusted.gpg.d/microsoft.asc.gpg && \
    echo "deb [arch=${ARCH_BIN}] https://packages.microsoft.com/repos/azure-cli/ bookworm main" > /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends azure-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    curl -fsSL "https://github.com/Azure/kubelogin/releases/latest/download/kubelogin-linux-${ARCH_BIN}.zip" -o /tmp/kubelogin.zip && \
    unzip -q /tmp/kubelogin.zip -d /tmp && \
    mv /tmp/bin/linux_${ARCH_BIN}/kubelogin /usr/local/bin/kubelogin && \
    chmod +x /usr/local/bin/kubelogin && \
    rm -rf /tmp/kubelogin.zip /tmp/bin

# ---------------------------------------------------------------------------
# Istioctl
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    ISTIO_VERSION="$(curl -fsSL https://api.github.com/repos/istio/istio/releases/latest | jq -r '.tag_name')" && \
    ISTIO_URL="https://github.com/istio/istio/releases/download/${ISTIO_VERSION}/istioctl-${ISTIO_VERSION}-linux-${ARCH_BIN}.tar.gz" && \
    if ! curl -fsSL -o /tmp/istioctl.tar.gz "${ISTIO_URL}"; then \
        ISTIO_VERSION="1.27.0"; \
        curl -fsSL -o /tmp/istioctl.tar.gz "https://github.com/istio/istio/releases/download/${ISTIO_VERSION}/istioctl-${ISTIO_VERSION}-linux-${ARCH_BIN}.tar.gz"; \
    fi && \
    tar -xzf /tmp/istioctl.tar.gz -C /tmp && \
    mv /tmp/istioctl /usr/local/bin/ && chmod +x /usr/local/bin/istioctl && \
    rm /tmp/istioctl.tar.gz

# ---------------------------------------------------------------------------
# PowerShell — many Azure tasks shell out to pwsh.
# ---------------------------------------------------------------------------
ARG PW_VERSION=7.5.4
RUN . /tmp/arch_vars && \
    if [ "$ARCH_BIN" = "amd64" ]; then PW_ARCH="x64"; else PW_ARCH="arm64"; fi && \
    curl -fsSL "https://github.com/PowerShell/PowerShell/releases/download/v${PW_VERSION}/powershell-${PW_VERSION}-linux-${PW_ARCH}.tar.gz" -o /tmp/pwsh.tar.gz && \
    mkdir -p /opt/powershell && \
    tar -xzf /tmp/pwsh.tar.gz -C /opt/powershell && \
    chmod +x /opt/powershell/pwsh && \
    ln -sf /opt/powershell/pwsh /usr/local/bin/pwsh && \
    rm /tmp/pwsh.tar.gz

# ---------------------------------------------------------------------------
# GitHub CLI — used by tasks that touch GitHub APIs.
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    GH_VERSION=$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest | jq -r '.tag_name' | sed 's/^v//') && \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH_BIN}.tar.gz" -o /tmp/gh.tar.gz && \
    tar -xzf /tmp/gh.tar.gz -C /tmp && \
    mv /tmp/gh_${GH_VERSION}_linux_${ARCH_BIN}/bin/gh /usr/local/bin/gh && \
    chmod +x /usr/local/bin/gh && \
    rm -rf /tmp/gh.tar.gz /tmp/gh_${GH_VERSION}_linux_${ARCH_BIN}

# ---------------------------------------------------------------------------
# Linear CLI (Finesssee/linear-cli) — built in the linear-cli-build stage so
# it links against bookworm glibc. Codecollections that automate Linear
# (issue creation, status updates) can shell out to `linear-cli`.
# ---------------------------------------------------------------------------
COPY --from=linear-cli-build /opt/linear-cli/bin/linear-cli /usr/local/bin/linear-cli
RUN chmod +x /usr/local/bin/linear-cli && linear-cli --version

# ---------------------------------------------------------------------------
# Claude Code CLI (claude) — standalone binary, no Node.js runtime needed.
# Available for codecollections that want to invoke Claude as part of a task
# (e.g. AI-assisted triage / remediation flows).
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    if [ "$ARCH_BIN" = "amd64" ]; then CLAUDE_ARCH="x64"; else CLAUDE_ARCH="arm64"; fi && \
    CLAUDE_PLATFORM="linux-${CLAUDE_ARCH}" && \
    CLAUDE_VERSION=$(curl -fsSL https://downloads.claude.ai/claude-code-releases/stable) && \
    CLAUDE_MANIFEST=$(curl -fsSL "https://downloads.claude.ai/claude-code-releases/${CLAUDE_VERSION}/manifest.json") && \
    CLAUDE_CHECKSUM=$(echo "$CLAUDE_MANIFEST" | jq -r ".platforms[\"${CLAUDE_PLATFORM}\"].checksum") && \
    curl -fsSL "https://downloads.claude.ai/claude-code-releases/${CLAUDE_VERSION}/${CLAUDE_PLATFORM}/claude" -o /usr/local/bin/claude && \
    echo "${CLAUDE_CHECKSUM}  /usr/local/bin/claude" | sha256sum --check && \
    chmod +x /usr/local/bin/claude && \
    claude --version

# ---------------------------------------------------------------------------
# Google Cloud SDK (kept in $RUNWHEN_HOME for user-writable component updates)
# ---------------------------------------------------------------------------
RUN . /tmp/arch_vars && \
    if [ "$ARCH_BIN" = "amd64" ]; then GCLOUD_ARCH="x86_64"; else GCLOUD_ARCH="arm"; fi && \
    curl -fsSLO "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-${CLOUD_SDK_VERSION}-linux-${GCLOUD_ARCH}.tar.gz" && \
    tar xzf google-cloud-cli-${CLOUD_SDK_VERSION}-linux-${GCLOUD_ARCH}.tar.gz && \
    rm google-cloud-cli-${CLOUD_SDK_VERSION}-linux-${GCLOUD_ARCH}.tar.gz && \
    rm -rf google-cloud-sdk/platform/bundledpythonunix
ENV PATH="${RUNWHEN_HOME}/google-cloud-sdk/bin:${PATH}"
RUN gcloud config set core/disable_usage_reporting true && \
    gcloud config set component_manager/disable_update_check true && \
    gcloud config set metrics/environment github_docker_image && \
    gcloud components update --quiet && \
    gcloud components remove -q bq && \
    gcloud components install -q beta gke-gcloud-auth-plugin && \
    rm -rf $(find google-cloud-sdk/ -regex ".*/__pycache__") \
           google-cloud-sdk/.install/.backup \
           google-cloud-sdk/bin/anthoscli

# ---------------------------------------------------------------------------
# skopeo from sid — bookworm's version is too old for several registries we hit.
# ---------------------------------------------------------------------------
RUN echo "deb http://deb.debian.org/debian sid main" > /etc/apt/sources.list.d/sid.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends -t sid skopeo && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Worker binary — copied from the worker stage so we keep only the bits we need.
# ---------------------------------------------------------------------------
COPY --from=worker /bin/worker ${RUNWHEN_HOME}/worker
RUN chmod +x ${RUNWHEN_HOME}/worker

# ---------------------------------------------------------------------------
# Helper scripts. These wire the worker / robotframework to the RunWhen
# platform and live under ${RUNWHEN_HOME}/robot-runtime/ which is added to
# PYTHONPATH below for `import` access to RWP / runtime_metrics / etc.
# ---------------------------------------------------------------------------
COPY --chown=runwhen:0 scripts/ ${RUNWHEN_HOME}/robot-runtime/
RUN chmod +x ${RUNWHEN_HOME}/robot-runtime/entrypoint.sh \
              ${RUNWHEN_HOME}/robot-runtime/runrobot.sh

# ---------------------------------------------------------------------------
# Python deps — installed system-wide so codecollection layers can import
# RW.* without re-installing rw-core-keywords on every CC build.
# ---------------------------------------------------------------------------
COPY requirements.txt /tmp/rw-base-runtime-requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/rw-base-runtime-requirements.txt && \
    rm /tmp/rw-base-runtime-requirements.txt

# ---------------------------------------------------------------------------
# Final permissions / cleanup
# ---------------------------------------------------------------------------
RUN usermod -g 0 runwhen -G 0 && \
    chown -R runwhen:0 ${RUNWHEN_HOME} && \
    chmod g=u /etc/passwd && \
    chmod -R g+w ${RUNWHEN_HOME} && \
    rm -f /tmp/arch_vars

ENV TMPDIR=/tmp/runwhen
RUN mkdir -p ${TMPDIR} && chmod 1777 ${TMPDIR}

# PYTHONPATH lets codecollections import RWP / runtime_metrics directly,
# and exposes the codecollection's own libraries/codebundles dirs (when the
# CC image lays them down at the conventional path below).
#
# Convention: codecollection contents (codebundles/, libraries/, ...) MUST
# be copied to ${RUNWHEN_HOME}/collection — NOT /codecollection. PAPI emits
# RW_PATH_TO_ROBOT=$(RUNWHEN_HOME)/collection/codebundles/<bundle>/sli.robot
# and runrobot.{sh,py} only know how to resolve under /collection/.
ENV PYTHONPATH="${RUNWHEN_HOME}/robot-runtime:${RUNWHEN_HOME}/collection:${RUNWHEN_HOME}/collection/libraries"
ENV PATH="${PATH}:/usr/local/bin:${RUNWHEN_HOME}/.local/bin"

USER runwhen

# ---------------------------------------------------------------------------
# Cursor CLI (cursor-agent / `cursor` alias). Installer targets
# $HOME/.local/bin, so it MUST run as the `runwhen` user (otherwise the
# binary lands in /root/.local which is unreachable at runtime).
# ---------------------------------------------------------------------------
RUN curl -fsSL https://cursor.com/install | bash \
 && ln -sf "$HOME/.local/bin/cursor-agent" "$HOME/.local/bin/cursor" \
 && cursor --version

ENTRYPOINT ["/bin/bash", "-c", "$RUNWHEN_HOME/robot-runtime/entrypoint.sh"]
