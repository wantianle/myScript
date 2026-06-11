#!/usr/bin/env bash
set -euo pipefail

APP_NAME="sshc"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/${APP_NAME}"
ZSH_COMPLETION_DIR="${HOME}/.local/share/zsh/site-functions"
BASH_COMPLETION_DIR="${HOME}/.local/share/bash-completion/completions"
COMMAND_PATH="${BIN_DIR}/${APP_NAME}"
CONFIG_PATH="${HOME}/.sshc_config"
CONFIGURED_FILES=()

usage() {
  cat <<'EOF'
Usage:
  ./install.sh

Default:
  install dir: ~/.local/share/sshc
  command:     ~/.local/bin/sshc
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "install.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for file in "${APP_NAME}" "${APP_NAME}.py" "_${APP_NAME}" "${APP_NAME}.bash-completion"; do
  if [[ ! -f "${SOURCE_DIR}/${file}" ]]; then
    echo "install.sh: missing ${SOURCE_DIR}/${file}" >&2
    exit 1
  fi
done

mkdir -p "${BIN_DIR}" "${APP_DIR}" "${ZSH_COMPLETION_DIR}" "${BASH_COMPLETION_DIR}"
install -m 0755 "${SOURCE_DIR}/${APP_NAME}" "${APP_DIR}/${APP_NAME}"
install -m 0644 "${SOURCE_DIR}/${APP_NAME}.py" "${APP_DIR}/${APP_NAME}.py"
install -m 0644 "${SOURCE_DIR}/_${APP_NAME}" "${ZSH_COMPLETION_DIR}/_${APP_NAME}"
install -m 0644 "${SOURCE_DIR}/${APP_NAME}.bash-completion" "${BASH_COMPLETION_DIR}/${APP_NAME}"
ln -sf "${APP_DIR}/${APP_NAME}" "${COMMAND_PATH}"

upsert_config_block() {
  local config_file="$1"
  local block="$2"
  local tmp_file

  mkdir -p "$(dirname "${config_file}")"
  touch "${config_file}"
  tmp_file="$(mktemp)"
  awk '
    $0 == "# >>> sshc setup >>>" { skip = 1; next }
    $0 == "# <<< sshc setup <<<" { skip = 0; next }
    !skip { print }
  ' "${config_file}" > "${tmp_file}"
  {
    cat "${tmp_file}"
    printf "\n%s\n" "${block}"
  } > "${config_file}"
  rm -f "${tmp_file}"
  CONFIGURED_FILES+=("${config_file}")
}

configure_shells() {
  local shell_name
  shell_name="$(basename "${SHELL:-}")"

  local zsh_block
  zsh_block="$(cat <<'EOF'
# >>> sshc setup >>>
export PATH="$HOME/.local/bin:$PATH"
fpath=("$HOME/.local/share/zsh/site-functions" $fpath)
autoload -Uz compinit
compinit
# <<< sshc setup <<<
EOF
)"

  local bash_block
  bash_block="$(cat <<'EOF'
# >>> sshc setup >>>
export PATH="$HOME/.local/bin:$PATH"
if [ -r "$HOME/.local/share/bash-completion/completions/sshc" ]; then
  source "$HOME/.local/share/bash-completion/completions/sshc"
fi
# <<< sshc setup <<<
EOF
)"

  if [[ "${shell_name}" == "zsh" || -f "${HOME}/.zshrc" ]]; then
    upsert_config_block "${HOME}/.zshrc" "${zsh_block}"
  fi
  if [[ "${shell_name}" == "bash" || -f "${HOME}/.bashrc" ]]; then
    upsert_config_block "${HOME}/.bashrc" "${bash_block}"
  fi
  if [[ "${#CONFIGURED_FILES[@]}" -eq 0 ]]; then
    upsert_config_block "${HOME}/.zshrc" "${zsh_block}"
  fi
}

ensure_default_config() {
  if [[ -f "${CONFIG_PATH}" ]]; then
    chmod 0600 "${CONFIG_PATH}" 2>/dev/null || true
    return
  fi

  umask 077
  cat > "${CONFIG_PATH}" <<'EOF'
{
  "prod_username": "",
  "prod_password_md5": "",
  "test_username": "",
  "test_password_md5": "",
  "keyfile": "~/.ssh/id_ed25519"
}
EOF
}

configure_shells
ensure_default_config

echo "installed ${APP_NAME}: ${COMMAND_PATH}"
echo "configured shell startup: ${CONFIGURED_FILES[*]}"
echo "config file: ${CONFIG_PATH}"
cat <<EOF

Path and completion loading were configured automatically.

Configure your XiaoZhu account with sshc:

  sshc config --prod-username "prod_username" --prod-password "prod_password"
  sshc config --test-username "test_username" --test-password "test_password"

Optional private key override:

  sshc config -k "~/.ssh/id_ed25519"

Then reload your shell config:

  source ~/.zshrc or source ~/.bashrc
EOF
