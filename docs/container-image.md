# Container Image

The `opengpu:ml` image (published as `yashbhamare123/opengpu:ml`) is built from `nvidia/cuda:12.8.0-devel-ubuntu22.04`. It provides an SSH-accessible CUDA development environment rather than the OpenGPU control plane.

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
6. Starts `sshd` in the foreground with public-key authentication against `/etc/ssh/host_keys/authorized_keys` (command-line overrides beat a stale scratch `sshd_config`).

`sshd` still accepts password authentication. An empty authorized_keys file leaves password-only access. The file is root-owned mode `644` on the host-key bind mount (`ssh-host-keys/` is `755`) so `sshd` can read it after dropping to the login user. Host private keys remain mode `600`.

`/etc` is a bind-mounted copy of the image `/etc` on the scratch disk so the root filesystem can stay read-only. Host private keys are removed during image construction and generated only at runtime. The bundled profile script prints the terminal welcome banner for interactive SSH sessions.

The published runtime image is `yashbhamare123/opengpu:ml`. Hosts pull that tag via `DOCKER_IMAGE` / `opengpu setup`. Building from this Dockerfile is for image development:

```bash
docker build -t opengpu:ml .
docker tag opengpu:ml yashbhamare123/opengpu:ml
docker push yashbhamare123/opengpu:ml
docker run --rm --entrypoint bash opengpu:ml -lc 'python --version && nvim --version | head -1 && tmux -V'
```

## CPU image

`Dockerfile.cpu` is a small Ubuntu 22.04 image with Python, OpenSSH, sudo, git, curl, and vim. It uses the same entrypoint as the GPU image so reservations still work over SSH. It does not include CUDA or PyTorch.

```bash
docker build -f Dockerfile.cpu -t opengpu:cpu -t yashbhamare123/opengpu:cpu .
docker push yashbhamare123/opengpu:cpu
```

On a host without NVIDIA hardware, `opengpu doctor` prompts to enable CPU-only mode. That sets `CPU_ONLY=true`, switches `DOCKER_IMAGE` to `yashbhamare123/opengpu:cpu` (or a local `opengpu:cpu` tag), and omits GPU device requests. Non-interactive installs can pass `opengpu setup --cpu` or `opengpu doctor --cpu`.

GPU validation requires a free compatible device:

```bash
docker run --rm --gpus all --entrypoint python opengpu:ml \
  -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name())'
```

Also verify that the built image contains no `/etc/ssh/ssh_host_*_key` private keys. Do not run a GPU smoke test while a reservation is active.

ML dependencies are intentionally broad and materially affect image size. Review compatibility, CUDA wheels, licensing, and layer growth before adding packages.
