# Omarchy Synchro

Omarchy Synchro is a distributable Codex plugin, Omarchy Shell widget/native overlay, and standalone CLI. Reusable source stays in this repository; every user's private snapshot lives in a separately selected Git repository.

## Safety contract

- Explicit allowlist with mandatory secret-name/content, cache, browser, keyring, nested-Git, and plugin-tree exclusions.
- Portable and device-specific captures are separated.
- Snapshot and restore default to previews. Applying either requires `--apply`.
- Synchro never stages, commits, or pushes.
- SSH/HTTPS remotes use existing Git authentication; credential-bearing URLs are rejected.
- `/usr/share/omarchy` is never captured or modified.

## First use

```bash
bin/omarchy-synchro config select ~/Work/omarchy-config
bin/omarchy-synchro repo init
bin/omarchy-synchro repo origin set git@github.com:you/omarchy-config.git
bin/omarchy-synchro repo origin test
bin/omarchy-synchro snapshot
bin/omarchy-synchro snapshot --apply
git -C ~/Work/omarchy-config diff
```

Edit `policy/allowlist.tsv` in the configuration repository to approve capture sources. Device-sensitive entries must use the `device` scope.

Restore is dry-run by default:

```bash
bin/omarchy-synchro restore
bin/omarchy-synchro restore --apply
```

Device data is excluded unless `--include-device` is explicitly supplied.

## Git operations

`repo origin show|set|test|remove` manages only `origin`. Synchro exposes ahead/behind and dirty state, but deliberately has no commit or push command.

## New laptop seed

`bin/omarchy-synchro seed` reports the staged workflow. Package/plugin installation and component reload stages remain preview-only until separately approved and implemented.

## Local install and uninstall

Run `scripts/install-local` only after both plugin validators and tests pass. `scripts/uninstall-local` removes the Shell integration but preserves the selected configuration repository and `~/.config/omarchy/omarchy-synchro.json`.

## Tests

```bash
python -m unittest discover -s tests -v
omarchy plugin validate omarchy-shell/harel.omarchy-synchro
python /home/harel/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```
