#!/usr/bin/env bash

set -Eeuo pipefail
readonly DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$DIR/start_replay_stack.sh" "$@"
