# syntax=docker/dockerfile:1.6
# ============================================================================
# zzzpeak dev container — git/gh + vim/tmux + ssh client + Claude Code CLI,
# plus Python for tools/ (the spaCy phrase chunker) and a place to preview
# docs/ (the GitHub Pages webapp) locally.
#
# Runs as service user uid=1000 so bind-mounted repo files stay host-owned
# under rootless podman (--userns=keep-id). Attach interactively:
#   podman exec -it zzzpeak bash        (or `claude` to drive the repo)
#
# No uv/venv manager baked in — plain python3 + pip installs tools/requirements.txt
# system-wide so `python3 tools/chunk.py` / `python3 tools/test_chunker.py` just work.
#
# BUILD CONTEXT = repo root (so tools/requirements.txt is reachable):
#   podman build -t zzzpeak-dev -f container/Dockerfile .
#   (or just run container/build.sh)
# ============================================================================
FROM debian:trixie-slim

ARG USERNAME=dev
ARG USER_UID=1000
# Pin Claude Code by passing --build-arg CLAUDE_VERSION=<x.y.z>; empty = latest stable.
ARG CLAUDE_VERSION=""

# --- system packages (root) ------------------------------------------------
# git/gh: repo control. vim/tmux/ripgrep/jq/tree/less: for exec'ing in.
# openssh-client: git-over-ssh if you'd rather mount a key than use gh.
# python3/pip: runs tools/chunk.py + the test scripts + `python3 -m http.server`
# for docs/ preview. python3-full pulls in venv support (unused here, but
# keeps distutils/pip happy on trixie's "externally managed" Python).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
        git openssh-client \
        vim tmux \
        ripgrep jq tree less bash-completion procps \
        python3 python3-full python3-pip \
    && rm -rf /var/lib/apt/lists/*

# --- GitHub CLI (official apt repo, keyring-verified) ----------------------
RUN install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*


# --- service user = host uid 1000 (keep-id maps it back to the host user) --
RUN useradd -m -u ${USER_UID} -s /bin/bash ${USERNAME}
USER ${USERNAME}
ENV HOME="/home/${USERNAME}"
WORKDIR /project

# --- Python deps for tools/ (spaCy chunker) --------------------------------
# No uv, no venv. PIP_BREAK_SYSTEM_PACKAGES covers `pip install` here AND the
# pip subprocess spaCy's own `download` command shells out to internally
# (which doesn't accept a --break-system-packages flag of its own).
ENV PIP_BREAK_SYSTEM_PACKAGES=1
COPY --chown=${USER_UID}:${USER_UID} tools/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && python3 -m spacy download en_core_web_sm \
    && python3 -m spacy download de_core_news_lg \
    && rm /tmp/requirements.txt

# --- Claude Code (native installer; npm is deprecated) ---------------------
# Auth is injected at runtime via the CLAUDE_CODE_OAUTH_TOKEN secret (run.sh).
RUN if [ -n "${CLAUDE_VERSION}" ]; then \
        curl -fsSL https://claude.ai/install.sh | bash -s -- "${CLAUDE_VERSION}"; \
    else \
        curl -fsSL https://claude.ai/install.sh | bash; \
    fi

# Non-login PATH (podman exec doesn't source login files).
ENV PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# --- dotfiles (so exec'd shells feel like your box: vi mode, git prompt, vim, tmux)
COPY --chown=${USER_UID}:${USER_UID} container/dotfiles/bashrc    ${HOME}/.bashrc.zzzpeak
COPY --chown=${USER_UID}:${USER_UID} container/dotfiles/vimrc     ${HOME}/.vimrc
COPY --chown=${USER_UID}:${USER_UID} container/dotfiles/tmux.conf ${HOME}/.tmux.conf
COPY --chown=${USER_UID}:${USER_UID} container/dotfiles/gitconfig ${HOME}/.gitconfig
COPY --chown=${USER_UID}:${USER_UID} container/dotfiles/gitignore ${HOME}/.gitignore
RUN cat ${HOME}/.bashrc.zzzpeak >> ${HOME}/.bashrc && rm ${HOME}/.bashrc.zzzpeak

# vim: fugitive (git inside vim)
RUN mkdir -p "${HOME}/.vim/pack/tpope/start" \
    && git clone --depth 1 https://tpope.io/vim/fugitive.git \
        "${HOME}/.vim/pack/tpope/start/fugitive" \
    && vim -u NONE -c "helptags ${HOME}/.vim/pack/tpope/start/fugitive/doc" -c q

# --- verify claude resolves + spaCy models loaded (fail the build early if not) ---
RUN command -v claude >/dev/null || { echo "BUILD ERROR: claude not on PATH after install" >&2; exit 1; }
RUN python3 -c "import spacy; spacy.load('en_core_web_sm'); spacy.load('de_core_news_lg'); print('spacy models ok')"

RUN pip install -U "spacy[transformers]" \
    && python -m spacy download de_dep_news_trf

# docs/ preview (see container/run.sh) — python3 -m http.server, published from run.sh
EXPOSE 8080

CMD ["bash"]

# --- provenance labels (LAST so they don't bust cache on the layers above) --
ARG GIT_REVISION=""
ARG BUILD_DATE=""
ARG IMAGE_VERSION="v0"
LABEL org.opencontainers.image.title="zzzpeak-dev" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}"
