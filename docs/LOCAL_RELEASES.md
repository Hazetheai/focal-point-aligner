# Local releases (gitignored)

Unsigned macOS `.app` builds stay on this machine under `releases/`. Nothing is
uploaded to GitHub or Apple.

## One-time setup

```bash
./scripts/install-git-hooks.sh
git branch release   # once; tracks what you ship locally
```

## Ship a build

From any feature work already on `main`:

```bash
git checkout release
git merge main
```

The `post-merge` hook runs `./scripts/release.sh`, which:

1. Builds the unsigned Tauri app (`./build_macos.sh`)
2. Copies it to `releases/vX.Y.Z/Focal Point Aligner.app`
3. Points `releases/latest` at that version
4. Creates a **local** git tag `vX.Y.Z` (does not push)

Skip the auto-build for a merge:

```bash
FPA_SKIP_RELEASE=1 git merge main
```

Or release manually anytime:

```bash
./scripts/release.sh
./scripts/release.sh --bump patch   # bump package + tauri version, commit, then build
```

## Open the latest local release

```bash
./scripts/open-app.sh
```

First Gatekeeper open: Finder → right-click the `.app` → **Open**.
The app still needs this checkout + `./venv`.

## Later (optional)

When you want shared/CI releases, add a remote workflow that publishes the same
artifact; keep this local path until then.
