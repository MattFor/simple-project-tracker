#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE=""
PREFIX=""
DESTDIR="${DESTDIR:-}"
INSTALL_DAEMON=false
UNINSTALL=false

print_help() {
    cat <<EOF
Tracker installer

Usage:
    ./install.sh [options]
    sudo ./install.sh [options]

Running as root it installs into /usr/local.
Running as user keeps the settings and the database next to the source.

Options:
    --system
        Copy everything into a prefix, even without root. Uses /usr/local
        unless --prefix says otherwise.

    --user
        Launcher into this checkout under ~/.local, even as root.

    --prefix DIR
        Install under DIR. Implies --system.

    --destdir DIR
        Stage the install under DIR without changing the recorded paths.
        For building a package.

    --daemon, -d
        Also install the daemon autostart entry.

    --uninstall, -u
        Remove whatever this script installed.

    --help, -h
        Show this help message.

Environment:
    DESTDIR     staging directory for packagers, prepended to every path
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --system|system)
            MODE="system"
            ;;
        --user|user)
            MODE="user"
            ;;
        --prefix)
            [[ $# -ge 2 ]] || { echo "[ERROR] --prefix needs a directory"; exit 1; }
            PREFIX="$2"
            MODE="system"
            shift
            ;;
        --prefix=*)
            PREFIX="${1#*=}"
            MODE="system"
            ;;
        --destdir)
            [[ $# -ge 2 ]] || { echo "[ERROR] --destdir needs a directory"; exit 1; }
            DESTDIR="$2"
            shift
            ;;
        --destdir=*)
            DESTDIR="${1#*=}"
            ;;
        --daemon|-d|daemon|d)
            INSTALL_DAEMON=true
            ;;
        --uninstall|-u|uninstall|u)
            UNINSTALL=true
            ;;
        --help|-h|help|h)
            print_help
            exit 0
            ;;
        *)
            echo "[ERROR] unknown option: $1"
            echo
            print_help
            exit 1
            ;;
    esac
    shift
done

if [[ -z "${MODE}" ]]; then
    if [[ "${EUID}" -eq 0 ]]; then
        MODE="system"
    else
        MODE="user"
    fi
fi

if [[ "${MODE}" == "system" ]]; then
    PREFIX="${PREFIX:-/usr/local}"
else
    PREFIX="${HOME}/.local"
fi

ROOT="${DESTDIR}${PREFIX}"

BIN_DIR="${ROOT}/bin"
LIB_DIR="${ROOT}/lib/tracker"
MAN_DIR="${ROOT}/share/man/man1"
BASH_DIR="${ROOT}/share/bash-completion/completions"
FISH_DIR="${ROOT}/share/fish/vendor_completions.d"
LICENSE_DIR="${ROOT}/share/licenses/tracker"

TRACKER_BIN="${BIN_DIR}/tracker"
SHORT_BIN="${BIN_DIR}/t"

if [[ "${MODE}" == "system" ]]; then
    AUTOSTART_FILE="${DESTDIR}/etc/xdg/autostart/tracker-daemon.desktop"
else
    AUTOSTART_FILE="${HOME}/.config/autostart/tracker-daemon.desktop"
fi

if "${UNINSTALL}"; then
    if [[ -x "${TRACKER_BIN}" ]]; then
        "${TRACKER_BIN}" daemon stop >/dev/null 2>&1 || true
    fi

    rm -f "${TRACKER_BIN}" "${SHORT_BIN}"
    rm -f "${MAN_DIR}/tracker.1.gz" "${MAN_DIR}/t.1.gz"
    rm -f "${BASH_DIR}/tracker" "${BASH_DIR}/t"
    rm -f "${FISH_DIR}/tracker.fish"
    rm -f "${AUTOSTART_FILE}"
    rm -rf "${LIB_DIR}" "${LICENSE_DIR}"

    echo "Tracker has been uninstalled from ${PREFIX}."

    if [[ "${MODE}" == "system" ]]; then
        echo "Settings in ~/.config/tracker and database in ~/.local/share/tracker were left alone."
    else
        echo "Settings and database in ${PROJECT_DIR} were left alone."
    fi

    exit 0
fi

PYTHON_BIN=""

if [[ "${MODE}" == "user" && -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
else
    PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
    echo "[ERROR] python3 was not found."
    exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "[ERROR] Python 3.11 or newer is required (found $("${PYTHON_BIN}" -V))."
    exit 1
fi

for required in man/tracker.1 tracker/share/completion.bash tracker/share/completion.fish; do
    if [[ ! -f "${PROJECT_DIR}/${required}" ]]; then
        echo "[ERROR] ${PROJECT_DIR}/${required} was not found."
        exit 1
    fi
done

mkdir -p "${BIN_DIR}" "${MAN_DIR}" "${BASH_DIR}" "${FISH_DIR}"

if [[ "${MODE}" == "system" ]]; then
    rm -rf "${LIB_DIR}"
    mkdir -p "${LIB_DIR}"

    cp -r "${PROJECT_DIR}/tracker" "${LIB_DIR}/tracker"
    find "${LIB_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} +

    cat > "${TRACKER_BIN}" <<EOF
#!/bin/sh

PYTHONPATH="${PREFIX}/lib/tracker\${PYTHONPATH:+:\${PYTHONPATH}}"
export PYTHONPATH

exec "${PYTHON_BIN}" -P -m tracker "\$@"
EOF

    mkdir -p "${LICENSE_DIR}"
    cp "${PROJECT_DIR}/LICENSE" "${LICENSE_DIR}/LICENSE"
else
    cat > "${TRACKER_BIN}" <<EOF
#!/usr/bin/env bash

set -e

if [[ ! -d "${PROJECT_DIR}" ]]; then
    echo "[ERROR] tracker was installed from ${PROJECT_DIR}, which is gone." >&2
    echo "        if you moved or renamed it run install.sh again from there." >&2
    exit 1
fi

cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" -m tracker "\$@"
EOF
fi

chmod +x "${TRACKER_BIN}"
ln -sfn "tracker" "${SHORT_BIN}"

cp "${PROJECT_DIR}/man/tracker.1" "${MAN_DIR}/tracker.1"
gzip -f "${MAN_DIR}/tracker.1"
ln -sfn "tracker.1.gz" "${MAN_DIR}/t.1.gz"

cp "${PROJECT_DIR}/tracker/share/completion.bash" "${BASH_DIR}/tracker"
ln -sfn "tracker" "${BASH_DIR}/t"
cp "${PROJECT_DIR}/tracker/share/completion.fish" "${FISH_DIR}/tracker.fish"

if "${INSTALL_DAEMON}"; then
    mkdir -p "$(dirname "${AUTOSTART_FILE}")"

    cat > "${AUTOSTART_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Tracker Daemon
Comment=Track your projects in the background
Exec=${PREFIX}/bin/tracker daemon
Terminal=false
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
fi

echo
echo "Tracker has been installed. To use type t / tracker."
echo "-  t         [${SHORT_BIN}]"
echo "-  tracker   [${TRACKER_BIN}]"
echo "-  man       [${MAN_DIR}/tracker.1.gz]"
echo "-  bash      [${BASH_DIR}/tracker]"
echo "-  fish      [${FISH_DIR}/tracker.fish]"

if [[ "${MODE}" == "system" ]]; then
    echo
    echo "Installed as a program under ${PREFIX}."
    echo "Settings go to ~/.config/tracker, the database to ~/.local/share/tracker."
else
    echo
    echo "Installed for ${USER} only, running from ${PROJECT_DIR}."
    echo "Settings and the database stay in the checkout."
fi

echo
echo "For zsh completion add this to ~/.zshrc:"
# shellcheck disable=SC2016
echo '    eval "$(tracker completion zsh)"'

if "${INSTALL_DAEMON}"; then
    echo
    echo "Daemon autostart installed to [${AUTOSTART_FILE}]"
fi

case ":${PATH}:" in
    *:"${PREFIX}/bin":*)
        ;;
    *)
        echo
        echo "[WARNING] ${PREFIX}/bin is not in PATH."
        echo
        echo "Add this to your shell configuration:"
        echo "    export PATH=\"${PREFIX}/bin:\$PATH\""
        ;;
esac

if "${INSTALL_DAEMON}" && [[ "${MODE}" == "user" ]]; then
    echo
    "${TRACKER_BIN}" daemon start
fi
