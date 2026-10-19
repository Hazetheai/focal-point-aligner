# Import & batch

## Import

Paste URLs, pick a `.txt` list, or a folder of lists. Downloads land under the destination you choose, then the app continues as Batch.

**List naming** uses a pattern with `{name}` (default `image_urls--{name}` → e.g. `image_urls--cats.txt` → folder from `{name}`).

**Folder name** template (default `{name}`) supports:

| Token | Meaning |
|-------|---------|
| `{name}` | Name captured from the list filename |
| `{n}` / `{nn}` | 1-based job index (`1`, `01`, …) |
| `{stem}` | Full list filename without `.txt` |

## Batch

- Browse a root folder; the queue lists media-bearing subfolders.
- A folder is **done** when `<sub>_aligned` already contains media; auto-advance skips those.
- **Merge** prefixes sources into one folder; optional delete-after-success.
- **Move aligned** gathers `<sub>_aligned` folders into a sibling `<root>_aligned`.
