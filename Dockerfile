FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    git \
    curl \
    vim \
    neovim \
    tmux \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    python-is-python3 \
    cmake \
    ninja-build \
    pkg-config \
    ffmpeg \
    graphviz \
    libgl1 \
    libglib2.0-0 \
    libsndfile1 \
    && rm -f /etc/ssh/ssh_host_* \
    && rm -rf /var/lib/apt/lists/*

# Keep the CUDA framework install separate so application-library changes can
# reuse its large Docker layer. PyTorch 2.11 is the final release line with
# official CUDA 12.8 wheels.
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu128

COPY requirements-ml.txt /tmp/requirements-ml.txt
RUN python -m pip install -r /tmp/requirements-ml.txt && \
    rm /tmp/requirements-ml.txt

RUN mkdir -p /run/sshd /etc/ssh/host_keys

# Ubuntu's sshd_config already sets PubkeyAuthentication no; sshd keeps the first value.
RUN sed -i 's/^PubkeyAuthentication no$/PubkeyAuthentication yes/' /etc/ssh/sshd_config && \
    printf '%s\n' \
    'PasswordAuthentication yes' \
    'PubkeyAuthentication yes' \
    'AuthorizedKeysFile /etc/ssh/host_keys/authorized_keys' \
    'PermitRootLogin no' \
    'HostKey /etc/ssh/host_keys/ssh_host_ed25519_key' \
    'HostKey /etc/ssh/host_keys/ssh_host_ecdsa_key' \
    'HostKey /etc/ssh/host_keys/ssh_host_rsa_key' \
    >> /etc/ssh/sshd_config

COPY entrypoint.sh /entrypoint.sh
COPY scripts/cynaptics-banner.sh /etc/profile.d/cynaptics-banner.sh
RUN chmod +x /entrypoint.sh /etc/profile.d/cynaptics-banner.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
