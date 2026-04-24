- Skills are located in ./claude/ folder.
- Python environment for project — use uv env
    - When debugging Python/uv issues, explicitly inspect .uv-cache or .venv with hidden/ignored files enabled; do not assume
    default file search will include it.
- Don't commit or run git write operations — user handles git themselves; don't run commit/push/reset/etc.
- Before deleting any files not managed by Git (e.g., ignored files or files outside the workspace), you must warn me and wait for my manual confirmation, unless they are test files created by AGENT.