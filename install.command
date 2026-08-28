#!/usr/bin/env bash

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
"${script_dir}/install.sh" "$@"
install_status="$?"

printf '\nNhấn Enter để đóng cửa sổ này...'
read -r _
exit "${install_status}"
