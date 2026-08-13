#!/usr/bin/env bash
#
# create-signed-commit.sh -- commit ONE file to a repo branch through the
# GitHub GraphQL API (createCommitOnBranch) instead of git commit+push.
# Local tool (no workflow calls it): typical use is the MANUAL apio
# remote-config bump after publish-release (apio#927).
#
# Why: commits created through the API are signed by GitHub itself and
# show up as "Verified", which satisfies branch rules like apio's
# "commits must have verified signatures" without storing any signing
# key in secrets. The commit is attributed to the owner of GH_TOKEN.
#
# What it does:
#   1. resolves the head of <base-branch> in <owner/repo>;
#   2. creates <branch> there, or force-resets it if it already exists
#      (so a re-run always builds on a fresh base);
#   3. commits <local-file> as <path-in-repo> on <branch> with <message>;
#   4. prints the new commit sha.
#
# Usage:
#   GH_TOKEN=<token> scripts/create-signed-commit.sh \
#     <owner/repo> <branch> <base-branch> <path-in-repo> <local-file> <message>
#
#   Append --dry-run to print the GraphQL payload (with a placeholder
#   head oid) instead of touching the remote — used by the tests.

set -euo pipefail

[ $# -ge 6 ] || {
    echo "usage: $0 <owner/repo> <branch> <base-branch> <path-in-repo> <local-file> <message> [--dry-run]" >&2
    exit 2
}
REPO=$1 BRANCH=$2 BASE=$3 RPATH=$4 LOCAL=$5 MSG=$6
DRY=${7:-}

[ -f "$LOCAL" ] || { echo "local file not found: $LOCAL" >&2; exit 2; }

payload() {  # $1 = expected head oid
    python3 - "$REPO" "$BRANCH" "$1" "$RPATH" "$LOCAL" "$MSG" <<'PYEOF'
import base64, json, sys
repo, branch, head, rpath, local, msg = sys.argv[1:7]
query = ("mutation($input: CreateCommitOnBranchInput!) {"
         " createCommitOnBranch(input: $input) { commit { oid } } }")
variables = {"input": {
    "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
    "expectedHeadOid": head,
    "message": {"headline": msg},
    "fileChanges": {"additions": [{
        "path": rpath,
        "contents": base64.b64encode(open(local, "rb").read()).decode(),
    }]},
}}
json.dump({"query": query, "variables": variables}, sys.stdout)
PYEOF
}

if [ "$DRY" = "--dry-run" ]; then
    payload "0000000000000000000000000000000000000000"
    exit 0
fi

: "${GH_TOKEN:?GH_TOKEN must be set}"

HEAD_OID=$(gh api "repos/$REPO/git/ref/heads/$BASE" --jq .object.sha)

# create the branch at the base head, or force-reset an existing one
if gh api "repos/$REPO/git/ref/heads/$BRANCH" >/dev/null 2>&1; then
    gh api -X PATCH "repos/$REPO/git/refs/heads/$BRANCH" \
        -f sha="$HEAD_OID" -F force=true >/dev/null
else
    gh api "repos/$REPO/git/refs" \
        -f ref="refs/heads/$BRANCH" -f sha="$HEAD_OID" >/dev/null
fi

payload "$HEAD_OID" > /tmp/create-signed-commit-payload.json
gh api graphql --input /tmp/create-signed-commit-payload.json \
    --jq '.data.createCommitOnBranch.commit.oid'
