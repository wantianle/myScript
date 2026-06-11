#!/usr/bin/env bash
set -euo pipefail

APP_NAME="sshc"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/${APP_NAME}"
ZSH_COMPLETION_PATH="${HOME}/.local/share/zsh/site-functions/_${APP_NAME}"
BASH_COMPLETION_PATH="${HOME}/.local/share/bash-completion/completions/${APP_NAME}"

usage() {
  cat <<'EOF'
Usage:
  ./uninstall.sh

Default:
  remove command: ~/.local/bin/sshc
  remove dir:     ~/.local/share/sshc
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "uninstall.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

rm -f "${BIN_DIR}/${APP_NAME}"
rm -f "${ZSH_COMPLETION_PATH}"
rm -f "${BASH_COMPLETION_PATH}"
rm -rf "${APP_DIR}"

remove_config_block() {
  local config_file="$1"
  local tmp_file

  if [[ ! -f "${config_file}" ]]; then
    return
  fi
  tmp_file="$(mktemp)"
  awk '
    $0 == "# >>> sshc setup >>>" { skip = 1; next }
    $0 == "# <<< sshc setup <<<" { skip = 0; next }
    !skip { print }
  ' "${config_file}" > "${tmp_file}"
  cat "${tmp_file}" > "${config_file}"
  rm -f "${tmp_file}"
}

remove_config_block "${HOME}/.zshrc"
remove_config_block "${HOME}/.bashrc"

echo "uninstalled ${APP_NAME} from ${HOME}/.local"
echo "kept config: ${HOME}/.sshc_config"
