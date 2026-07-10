# Distributing Herds CLI via Homebrew

## Tap repository

Public tap: [`herds-social/herds-cli`](https://github.com/herds-social/homebrew-herds-cli)

The GitHub repo follows Homebrew's `homebrew-*` naming convention (`homebrew-herds-cli`), so the shorthand tap works:

```bash
brew tap herds-social/herds-cli
brew trust --formula herds-social/herds-cli/herds   # required on Homebrew 6.0.0+ (5.2.0+)
brew install herds
```

Upgrades after the formula is bumped:

```bash
brew update && brew upgrade herds
```

Source installs via `uv tool` remain the supported path for unreleased worktrees and local development.

## How releases connect to the formula

```text
tag cli-vX.Y.Z on herds-cli main
    → release-cli.yml builds sdist + wheel
    → GitHub Release assets
    → update Formula/herds.rb url + sha256 (+ resources if deps changed)
    → brew update && brew upgrade herds
```

CLI releases use tags matching `cli-v*` (for example `cli-v4.2.1`). The workflow attaches `herds_cli-<version>.tar.gz` and a wheel to each GitHub Release.

## Formula layout

`Formula/herds.rb` in the tap repo:

- `url` — GitHub Release **sdist** (`herds_cli-<version>.tar.gz`)
- `sha256` — from `shasum -a 256 herds_cli-<version>.tar.gz`
- `depends_on "python@3.11"` — matches `requires-python = ">=3.11"`
- `resource` blocks — runtime deps from PyPI (click, requests, rich, pytz, tzlocal and their transitive deps). Do **not** list `herds-cli` itself as a resource; it is the formula `url`.
- `virtualenv_install_with_resources` in `install`
- `test` — assert stable `--help` output (`Usage:`, `herds`)

Generate or refresh dependency `resource` blocks:

```bash
pip install homebrew-pypi-poet
poet click requests rich pytz tzlocal
```

(`poet herds-cli` works only after the package is published to PyPI; until then, generate resources per runtime dependency.)

## Per-release checklist

1. Bump version in `pyproject.toml`, `herds_cli/__init__.py`, and `uv.lock` on the release branch; merge to `main`.
2. Tag and push:

   ```bash
   git tag cli-vX.Y.Z
   git push origin cli-vX.Y.Z
   ```

3. Wait for the **Release CLI** workflow; confirm the GitHub Release has the sdist.
4. Download the sdist and record SHA256:

   ```bash
   gh release download cli-vX.Y.Z --repo herds-social/herds-cli --pattern 'herds_cli-*.tar.gz'
   shasum -a 256 herds_cli-X.Y.Z.tar.gz
   ```

5. In `homebrew-herds-cli`, update `Formula/herds.rb`:
   - `url` → new release sdist URL
   - `sha256` → value from step 4
   - `resource` blocks → regenerate if `pyproject.toml` dependencies changed
6. Push to the tap `main` branch.
7. Smoke test:

   ```bash
   brew update && brew upgrade herds
   herds --help
   brew test herds
   ```

## Troubleshooting

- **`which herds` shows the wrong version** — Homebrew (`/opt/homebrew/bin/herds`) and `uv tool` (`~/.local/bin/herds`) can both install `herds`. Check `which -a herds` and your `PATH` order.
- **Untrusted formula** — run `brew trust --formula herds-social/herds-cli/herds` before `brew install` (required on Homebrew 6.0.0+ / 5.2.0+).

## Optional automation

A follow-up GitHub Action on `herds-cli` release could open a PR on the tap with updated `url`/`sha256` (for example Homebrew's `bump-formula-pr` pattern or a small workflow with a tap deploy key).
