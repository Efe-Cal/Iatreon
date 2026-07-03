#!/usr/bin/env sh
set -eu

key_path="${HOME}/.ssh/id_ed25519"
host_name=""
port=""
no_connect=0
default_agent_sock="${HOME}/.ssh/iatreon-agent.sock"
host_alias="iatreon"
origin_url="https://iatreon.efecal.hackclub.app/"

usage() {
    cat <<EOF
Usage: setup-iatreon.sh [--key PATH] [--origin URL] [--no-connect]
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
        --origin)
            origin_url="$2"
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

fetch_host_info() {
    require_command curl
    host_txt_url="${origin_url%/}/host.txt"
    step "Fetching host info from $host_txt_url"
    body=$(curl -fsSL --max-time 10 "$host_txt_url" 2>/dev/null || true)
    if [ -z "$body" ]; then
        step "Could not fetch host.txt; falling back to 127.0.0.1:2222"
        host_name="127.0.0.1"
        port="2222"
        return
    fi
    first_line=$(printf '%s' "$body" | sed -n '1p')
    parsed_host=$(printf '%s' "$first_line" | awk -F: '{print $1}')
    parsed_port=$(printf '%s' "$first_line" | awk -F: '{print $2}')
    if [ -z "$parsed_host" ] || [ -z "$parsed_port" ]; then
        step "host.txt was empty or malformed; falling back to 127.0.0.1:2222"
        host_name="127.0.0.1"
        port="2222"
        return
    fi
    host_name="$parsed_host"
    port="$parsed_port"
    step "Using $host_name:$port from host.txt"
}

fetch_host_info

ssh_dir=$(dirname "$key_path")
if [ ! -d "$ssh_dir" ]; then
    step "Creating $ssh_dir"
    mkdir -p "$ssh_dir"
fi
chmod 700 "$ssh_dir" 2>/dev/null || true

agent_dir=$(dirname "$default_agent_sock")
if [ ! -d "$agent_dir" ]; then
    step "Creating $agent_dir"
    mkdir -p "$agent_dir"
fi
chmod 700 "$agent_dir" 2>/dev/null || true

if [ ! -f "$key_path" ]; then
    step "Creating Ed25519 SSH key at $key_path"
    ssh-keygen -t ed25519 -f "$key_path" -N "" -C "iatreon@$(hostname)"
fi
chmod 600 "$key_path" 2>/dev/null || true

agent_responds() {
    set +e
    SSH_AUTH_SOCK="$1" ssh-add -l >/dev/null 2>&1
    status=$?
    set -e
    [ "$status" -eq 0 ] || [ "$status" -eq 1 ]
}

agent_sock="$default_agent_sock"
if ! agent_responds "$agent_sock"; then
    step "Starting ssh-agent at $agent_sock"
    rm -f "$agent_sock"
    ssh-agent -a "$agent_sock" >/dev/null
fi
export SSH_AUTH_SOCK="$agent_sock"

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

write_ssh_config() {
    config_path="${HOME}/.ssh/config"
    tmp_path="${config_path}.tmp.$$"
    start_marker="# >>> iatreon"
    end_marker="# <<< iatreon"

    if [ -f "$config_path" ]; then
        awk -v start="$start_marker" -v end="$end_marker" '
            $0 == start { skip = 1; next }
            $0 == end { skip = 0; next }
            !skip { print }
        ' "$config_path" > "$tmp_path"
    else
        : > "$tmp_path"
    fi

    {
        cat "$tmp_path"
        if [ -s "$tmp_path" ]; then
            printf '\n'
        fi
        printf '%s\n' "$start_marker"
        printf 'Host %s\n' "$host_alias"
        printf '    HostName %s\n' "$host_name"
        printf '    Port %s\n' "$port"
        printf '    ForwardAgent yes\n'
        printf '    IdentityAgent %s\n' "$default_agent_sock"
        printf '%s\n' "$end_marker"
    } > "$config_path"
    rm -f "$tmp_path"
    chmod 600 "$config_path" 2>/dev/null || true
}

step "Writing SSH config for $host_alias"
write_ssh_config

step "ssh-agent is ready"
printf '\nLoaded public key:\n%s\n\n' "$keys"

if [ "$no_connect" -eq 1 ]; then
    printf 'Connect with:\nssh %s\n' "$host_alias"
else
    printf 'Run ssh %s now? [y/N] ' "$host_alias"
    IFS= read -r answer || answer=
    case "$answer" in
        y|Y|yes|YES|Yes)
            step "Connecting to Iatreon SSH server"
            ssh "$host_alias"
            ;;
    esac
fi
