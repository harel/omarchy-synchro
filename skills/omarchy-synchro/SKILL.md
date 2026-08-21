---
name: omarchy-synchro
description: Safely manage a separate private Omarchy configuration repository using preview-first snapshot, restore, Git status, and seed workflows.
---

# Omarchy Synchro

Use the bundled `bin/omarchy-synchro` CLI. Always show previews before applying snapshots or restores. Never stage, commit, or push configuration automatically. Keep the reusable plugin repository and selected configuration repository separate. Treat device-scoped configuration as non-portable and require explicit user approval before restoring it.

Typical workflow:

```bash
bin/omarchy-synchro config show
bin/omarchy-synchro --json status
bin/omarchy-synchro snapshot
bin/omarchy-synchro snapshot --apply
git -C /path/to/config-repo diff
bin/omarchy-synchro restore
```

