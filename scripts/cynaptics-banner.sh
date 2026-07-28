#!/usr/bin/env bash

# Files in /etc/profile.d are sourced into the user's shell. Do not change the
# caller's shell options, and stay quiet for non-interactive SSH commands/SCP.
# When this helper is executed directly, always render it for local review.
# Ubuntu may source profile.d files from POSIX sh as well as Bash.
if [ -z "${BASH_VERSION:-}" ]; then
    return 0 2>/dev/null || exit 0
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]] && { [[ $- != *i* ]] || [[ ! -t 1 ]]; }; then
    return 0
fi

if [[ -r /etc/opengpu-storage.env ]]; then
    source /etc/opengpu-storage.env
fi

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    cyan=$'\033[38;2;37;181;255m'
    white=$'\033[38;2;235;245;250m'
    muted=$'\033[38;2;139;162;175m'
    warning=$'\033[38;2;255;193;92m'
    bold=$'\033[1m'
    reset=$'\033[0m'
else
    cyan=''
    white=''
    muted=''
    warning=''
    bold=''
    reset=''
fi

if [[ -t 1 ]]; then
    printf '\033[2J\033[H'
fi

printf '%s\n' "${cyan} ██████╗██╗   ██╗███╗   ██╗ █████╗ ██████╗ ████████╗██╗ ██████╗███████╗${reset}"
printf '%s\n' "${cyan}██╔════╝╚██╗ ██╔╝████╗  ██║██╔══██╗██╔══██╗╚══██╔══╝██║██╔════╝██╔════╝${reset}"
printf '%s\n' "${cyan}██║      ╚████╔╝ ██╔██╗ ██║███████║██████╔╝   ██║   ██║██║     ███████╗${reset}"
printf '%s\n' "${cyan}██║       ╚██╔╝  ██║╚██╗██║██╔══██║██╔═══╝    ██║   ██║██║     ╚════██║${reset}"
printf '%s\n' "${cyan}╚██████╗   ██║   ██║ ╚████║██║  ██║██║        ██║   ██║╚██████╗███████║${reset}"
printf '%s\n' "${cyan} ╚═════╝   ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝        ╚═╝   ╚═╝ ╚═════╝╚══════╝${reset}"
printf '\n'
printf '%s\n' "${white} ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗ ██████╗ ██╗   ██╗${reset}"
printf '%s\n' "${white}██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝ ██╔══██╗██║   ██║${reset}"
printf '%s\n' "${white}██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║  ███╗██████╔╝██║   ██║${reset}"
printf '%s\n' "${white}██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║   ██║██╔═══╝ ██║   ██║${reset}"
printf '%s\n' "${white}╚██████╔╝██║     ███████╗██║ ╚████║╚██████╔╝██║     ╚██████╔╝${reset}"
printf '%s\n' "${white} ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝      ╚═════╝ ${reset}"
printf '\n'
printf '%s\n' "${bold}${white}Welcome, ${USER:-researcher}.${reset} ${muted}Your accelerated workspace is ready.${reset}"
printf '\n'
printf '%s\n' "${muted}  gpu         ${reset}${white}NVIDIA RTX A6000${reset} ${cyan}· 48 GB VRAM${reset}"
printf '%s\n' "${muted}  cpu         ${reset}${white}16 cores${reset} ${cyan}· 32 GB system RAM${reset}"
printf '%s\n' "${muted}  storage     ${reset}${white}${OPENGPU_TEMP_STORAGE_GB:-${TEMP_STORAGE_GB:-100}} GB temporary${reset} ${cyan}· ${OPENGPU_WORKSPACE_GB:-${WORKSPACE_GB:-2}} GB /workspace limit (persistent)${reset}"
printf '\n'
printf '%s\n' "${white}Save files you want to keep in ${cyan}/workspace${white}.${reset}"
printf '%s\n' "${warning}Files outside /workspace are deleted when your reservation ends.${reset}"
printf '\n'
