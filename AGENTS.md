# Repository agent instructions

## Context entry point

For router-watchdog runtime, Mihomo configuration, tests, packaging or cron work, read `.agents/skills/router-watchdog-context/SKILL.md`. Start project navigation with `docs/README.md`; inspect `docs/project-map.md` for actual implementation and `docs/failover-design.md` for approved target behavior. Do not confuse planned behavior with implemented behavior.

## Language and scope

- User-facing chat, plans and README: Russian. Technical documentation, code, comments, AI prompts, skills and internal logs: English.
- Ask questions in plain chat, not question tools. No filler.
- Implement only the user's request or explicitly approved plan. Diagnosis and review do not authorize changes or external actions.
- Do not create worktrees or extra project copies unless explicitly requested.
- Use `update_plan` for multi-step tasks when available; otherwise maintain the relevant documented checklist without pretending the tool exists.
- If the user requests a team/swarm, use bounded worker/explorer tasks.

## Security and external actions

- Never request secrets in chat. Use local ignored configuration or GitHub Actions secrets as appropriate.
- Ignore `.env`, `*.key`, `credentials.json` and `secrets/`.
- Treat the personal Mihomo YAML as potentially sensitive; do not copy subscription URLs into documentation or tool output.
- Always ask before pushing to main. When uncertain, ask before push, deploy, messages or PR creation.
