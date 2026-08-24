#!/usr/bin/env bash
#
# Push this project to a GitHub repository (macOS / Linux / Git Bash / WSL).
#
# Before running:
#   1. Create an EMPTY repository on GitHub — no README, no .gitignore, no
#      licence. This project has all three; pre-filling them on GitHub's side
#      creates a conflict on the first push.
#   2. Have the repository URL ready.
#
# Usage:
#   bash scripts/push_to_github.sh
#   bash scripts/push_to_github.sh https://github.com/you/your-repo.git
#
# Credentials are never written by this script.

set -euo pipefail

cd "$(dirname "$0")/.."
echo
echo "=========================================================="
echo "  Clinical Evidence NLP Platform  ·  push to GitHub"
echo "=========================================================="
echo "  Working directory: $(pwd)"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is not installed." >&2
  exit 1
fi

# --- identity ---------------------------------------------------------------
if [ -z "$(git config --global user.name || true)" ]; then
  read -r -p "Your name for commits: " git_name
  git config --global user.name "$git_name"
fi
if [ -z "$(git config --global user.email || true)" ]; then
  read -r -p "Your GitHub email: " git_email
  git config --global user.email "$git_email"
fi

# --- repository -------------------------------------------------------------
[ -d .git ] || { echo "Initialising a new git repository..."; git init; }
git branch -M main

repo_url="${1:-}"
if [ -z "$repo_url" ]; then
  read -r -p "Paste your empty GitHub repository URL: " repo_url
fi
[ -n "$repo_url" ] || { echo "ERROR: no URL given." >&2; exit 1; }

git remote remove origin >/dev/null 2>&1 || true
git remote add origin "$repo_url"

# --- safety check: never ship a real .env -----------------------------------
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "ERROR: .env is tracked by git. Remove it before pushing:" >&2
  echo "  git rm --cached .env" >&2
  exit 1
fi

# --- commit -----------------------------------------------------------------
echo "Staging files..."
git add -A

if git diff --cached --quiet; then
  echo "Nothing new to commit; pushing the existing history."
else
  git commit -m "feat: clinical evidence NLP platform — source-grounded extraction with abstention and evaluation"
fi

# --- push -------------------------------------------------------------------
echo
echo "Pushing to $repo_url ..."
if ! git push -u origin main; then
  cat >&2 <<'MSG'

ERROR: the push failed. The two usual causes:

  1. The repository is not empty (a README was created with it).
     Fix:  git pull --rebase origin main   and run this script again.

  2. Authentication was cancelled or rejected.
     Fix:  run  git push -u origin main  by hand and complete the sign-in.
           On Linux/macOS a personal access token is used as the password:
           https://github.com/settings/tokens  (scope: repo)
MSG
  exit 1
fi

echo
echo "=========================================================="
echo "  Done: $repo_url"
echo "=========================================================="
echo
echo "  Next: set the repository description and topics on GitHub,"
echo "  then pin it to your profile."
echo
