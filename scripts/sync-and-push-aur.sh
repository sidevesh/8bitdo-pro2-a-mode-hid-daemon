#!/usr/bin/env bash
set -euo pipefail

# Sync PKGBUILD from source-of-truth and push to AUR.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/arch-packaging-files"
AUR_DIR="$ROOT_DIR/arch"
PKGBUILD_FILE="$TEMPLATE_DIR/PKGBUILD"

# Validate template PKGBUILD exists
if [[ ! -f "$PKGBUILD_FILE" ]]; then
  echo "Missing $PKGBUILD_FILE"
  exit 1
fi

# Extract package name from template
pkgname="$(sed -n "s/^pkgname=//p" "$PKGBUILD_FILE" | head -n1)"
if [[ -z "$pkgname" ]]; then
  echo "Could not parse pkgname from $PKGBUILD_FILE"
  exit 1
fi

# Ensure AUR git repo exists
mkdir -p "$AUR_DIR"
if [[ ! -d "$AUR_DIR/.git" ]]; then
  git -C "$AUR_DIR" init
fi

# Set AUR remote if not already set
remote_url="ssh://aur@aur.archlinux.org/${pkgname}.git"
if ! git -C "$AUR_DIR" remote get-url origin >/dev/null 2>&1; then
  git -C "$AUR_DIR" remote add origin "$remote_url"
fi

# Copy PKGBUILD template to AUR working directory
cp "$TEMPLATE_DIR/PKGBUILD" "$AUR_DIR/PKGBUILD"

# Generate .SRCINFO, commit, and push
(
  cd "$AUR_DIR"
  
  # Regenerate .SRCINFO from PKGBUILD
  makepkg --printsrcinfo > .SRCINFO
  
  # Stage files
  git add PKGBUILD .SRCINFO
  
  # Skip if no changes
  if git diff --cached --quiet; then
    echo "No changes to commit"
    exit 0
  fi
  
  # Commit with provided message or default
  commit_msg="${1:-Update AUR packaging}"
  git commit -m "$commit_msg"
  
  # Push to AUR
  current_branch="$(git branch --show-current 2>/dev/null || echo master)"
  git push -u origin "$current_branch"
)
