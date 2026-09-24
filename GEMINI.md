# KitchenClip Project Instructions & Constraints

## Tooling & Environment
* **CRITICAL - No GitHub CLI**: There is NO `gh` command installed and never will be. NEVER attempt to run `gh` commands under any circumstances. Check CI status through git or ask the user.
* **Git**: Use `GIT_CONFIG_GLOBAL=/dev/null` when running git commands to prevent sandbox failures with global git aliases.
* **Ansible**: Never directly run `ansible` commands, always tell the user what to run.
* **Docker**: Use `docker compose` directly on the host to manage services. Always remember to restart containers (`docker compose restart web celery_worker celery_beat`) when templates or Python files change if testing live.

## Architecture & Authentication
* **No Roles / No Admin Hierarchy**: There is NO "admin" role in KitchenClip. All members of a household have identical permissions and access. The `role` field on `UserProfile` is unused metadata.
* **No Django Admin**: The Django admin interface (`/admin/`) is intentionally disabled and removed from routing.
* **Zero Password Auth**: All authentication is passwordless via WebAuthn passkeys (Touch ID, Face ID, Android screen lock) and CLI single-use invite tokens. Zero password or username login forms.
