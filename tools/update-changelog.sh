#!/usr/bin/env bash

set -e

# Working directory must always be the project root.
cd "$(dirname "$0")/../"

NEXT_VERSION="${BVHOOK_NEW_VERSION}"
DRY_RUN=""

function display_help {
    echo "$0 [options]"
    echo
    echo "Options:"
    echo "    --help         -h : Display this help and exit"
    echo "    --new-version     : The next project version (default: BVHOOK_NEW_VERSION environment variable then current version)"
    echo "    --dry-run      -n : Do not modify the changelog and print the possible result in terminal"
}

while [[ $# -gt 0 ]]
do
    case "$1" in
        -h | --help)
            display_help
            exit 0
            ;;
        --new-version)
            [[ -z "$2" || "$2" == -* ]] && { echo "Missing --new-version argument" >&2; exit 2; }
            NEXT_VERSION="$2"
            shift 2
            ;;
        -n | --dry-run)
            DRY_RUN="dry_run"
            shift
            ;;
        -*)
            echo "Unknown option \"$1\"" >&2
            display_help >&2
            exit 2
            ;;
        *)
            if [[ -n "$1" ]]
            then
                echo "Unknown option \"$1\"" >&2
                display_help >&2
                exit 2
            fi
    esac
done

TOWNCRIER_ARGS=()

if [[ -n "${DRY_RUN}" ]]
then
    TOWNCRIER_ARGS+=(--draft)
else
    TOWNCRIER_ARGS+=(--yes)
fi

if [[ -n "${NEXT_VERSION}" ]]
then
    TOWNCRIER_ARGS+=(--version "${NEXT_VERSION}")
fi

towncrier build "${TOWNCRIER_ARGS[@]}"
exit 0
