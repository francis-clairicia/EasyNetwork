#!/usr/bin/env bash

set -e

# Working directory must always be the project root.
cd "$(dirname "$0")/../"

GIT_DIFF_VERSION=""
NEXT_VERSION=""
RELEASE_DATE=""
DRY_RUN=""

function display_help {
    echo "$0 [options]"
    echo
    echo "Options:"
    echo "    -h, --help                   Display this help and exit."
    echo "    -d, --date                   Changelog date (default: today)"
    echo "    --bump-my-version            Will read bump-my-version's hook environment variables"
    echo "                                 to create a version with a compare link."
    echo "    --version <version>          The next project version (default: current version)."
    echo "    --compare-diff <old...new>   Wrap version with a link to tag comparison on Github repo."
    echo "                                 --version option becomes mandatory."
    echo "    -n, --dry-run                Do not modify the changelog and print the possible result in terminal."
}

while [[ $# -gt 0 ]]
do
    case "$1" in
        -h | --help)
            display_help
            exit 0
            ;;
        -d | --date)
            [[ -z "$2" || "$2" == -* ]] && { echo "Missing --date argument" >&2; exit 2; }
            RELEASE_DATE="$2"
            shift 2
            ;;
        --bump-my-version)
            NEXT_VERSION="${BVHOOK_NEW_VERSION}"
            GIT_DIFF_VERSION="${BVHOOK_CURRENT_VERSION}...${BVHOOK_NEW_VERSION}"
            shift
            ;;
        --compare-diff)
            [[ -z "$2" || "$2" == -* ]] && { echo "Missing --compare-diff argument" >&2; exit 2; }
            GIT_DIFF_VERSION="$2"
            shift 2
            ;;
        --version)
            [[ -z "$2" || "$2" == -* ]] && { echo "Missing --version argument" >&2; exit 2; }
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

if [[ -n "${GIT_DIFF_VERSION}" ]]
then
    [[ -n "${NEXT_VERSION}" ]] || { echo "--compare-diff option given but missing --version argument" >&2; exit 2; }
    NEXT_VERSION="\`${NEXT_VERSION} <https://github.com/francis-clairicia/EasyNetwork/compare/${GIT_DIFF_VERSION}>\`_"
fi

if [[ -n "${NEXT_VERSION}" ]]
then
    TOWNCRIER_ARGS+=(--version "${NEXT_VERSION}")
fi

if [[ -n "${RELEASE_DATE}" ]]
then
    TOWNCRIER_ARGS+=(--date "${RELEASE_DATE}")
fi

towncrier build "${TOWNCRIER_ARGS[@]}"
exit 0
