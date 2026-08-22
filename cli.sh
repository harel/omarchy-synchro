#!/usr/bin/env bash
set -euo pipefail
script=$(readlink -f -- "${BASH_SOURCE[0]}")
root=$(cd -- "$(dirname -- "$script")" && pwd -P)
exec "$root/bin/omarchy-synchro" "$@"
