# Container Image

The `opengpu:ml` image is built from `nvidia/cuda:12.8.0-devel-ubuntu22.04`. It provides an SSH-accessible CUDA development environment rather than the OpenGPU control plane.

## Image contents

- Python available as both `python` and `python3`
- PyTorch, torchvision, and torchaudio CUDA 12.8 wheels
- Scientific Python, notebooks, visualization, CV/audio, Hugging Face, ONNX, experiment tracking, and developer tooling from `requirements-ml.txt`
- Git, curl, build tools, FFmpeg, Graphviz, Vim, Neovim, and tmux
- OpenSSH server and passwordless sudo for the generated user

The framework layer is separate from the broader ML requirements so changes to application libraries can reuse the large PyTorch layer.

## Startup

The entrypoint:

1. Creates the Linux user named by `TEAM_NAME` without a default home or lastlog update (`useradd -M -l`), so `/home` and `/tmp` stay on the scratch mounts.
2. Applies `TEAM_PASSWORD_HASH` with `chpasswd -e`.
3. Grants passwordless sudo and suppresses the Ubuntu MOTD.
4. Assigns `/workspace` to the user and ensures `/tmp` is mode `1777`.
5. Creates missing Ed25519, ECDSA, and RSA host keys in `/etc/ssh/host_keys`.
6. Starts `sshd` in the foreground.

`/etc` is a bind-mounted copy of the image `/etc` on the scratch disk so the root filesystem can stay read-only. Host private keys are removed during image construction and generated only at runtime. The bundled profile script prints the terminal welcome banner for interactive SSH sessions.

## Building and testing

```bash
docker build -t opengpu:ml .
docker run --rm --entrypoint bash opengpu:ml -lc 'python --version && nvim --version | head -1 && tmux -V'
```

GPU validation requires a free compatible device:

```bash
docker run --rm --gpus all --entrypoint python opengpu:ml \
  -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name())'
```

Also verify that the built image contains no `/etc/ssh/ssh_host_*_key` private keys. Do not run a GPU smoke test while a reservation is active.

ML dependencies are intentionally broad and materially affect image size. Review compatibility, CUDA wheels, licensing, and layer growth before adding packages.
