#!/usr/bin/env sh
set -eu

key_path="${HOME}/.ssh/id_ed25519"
host_name="127.0.0.1"
port="2222"
no_connect=0

usage() {
    cat <<EOF
Usage: setup-ssh-agent.sh [--key PATH] [--host HOST] [--port PORT] [--no-connect]
EOF
}

step() {
    printf '==> %s\n' "$1"
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Required command %s was not found. Install OpenSSH and try again.\n' "$1" >&2
        exit 1
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --key)
            key_path="$2"
            shift 2
            ;;
        --host)
            host_name="$2"
            shift 2
            ;;
        --port)
            port="$2"
            shift 2
            ;;
        --no-connect)
            no_connect=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 1
            ;;
    esac
done

require_command ssh
require_command ssh-add
require_command ssh-keygen

ssh_dir=$(dirname "$key_path")
if [ ! -d "$ssh_dir" ]; then
    step "Creating $ssh_dir"
    mkdir -p "$ssh_dir"
fi
chmod 700 "$ssh_dir" 2>/dev/null || true

if [ ! -f "$key_path" ]; then
    step "Creating Ed25519 SSH key at $key_path"
    ssh-keygen -t ed25519 -f "$key_path" -N "" -C "iatreon@$(hostname)"
fi
chmod 600 "$key_path" 2>/dev/null || true

if ! ssh-add -l >/dev/null 2>&1; then
    step "Starting ssh-agent for this session"
    eval "$(ssh-agent -s)" >/dev/null
fi

case "$(uname -s)" in
    Darwin)
        step "Adding key to ssh-agent and macOS Keychain"
        if ! ssh-add --apple-use-keychain "$key_path" 2>/dev/null; then
            ssh-add -K "$key_path" 2>/dev/null || ssh-add "$key_path"
        fi
        ;;
    *)
        step "Adding key to ssh-agent"
        ssh-add "$key_path"
        ;;
esac

keys=$(ssh-add -L 2>/dev/null || true)
if [ -z "$keys" ]; then
    printf 'ssh-agent is running, but no keys are loaded.\n' >&2
    exit 1
fi

step "ssh-agent is ready"
printf '\nLoaded public key:\n%s\n\n' "$keys"

if [ "$no_connect" -eq 1 ]; then
    printf 'Connect with:\nssh -A -p %s %s\n' "$port" "$host_name"
else
    step "Connecting to Iatreon SSH server"
    ssh -A -p "$port" "$host_name"
fi
