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

## Test execution approval

- Request approval to run the full test suite separately from all other actions. Never bundle the full-suite command with file edits, documentation updates, graph updates or other commands in the same approval request.

## Security and external actions

- Never request secrets in chat. Use local ignored configuration or GitHub Actions secrets as appropriate.
- Ignore `.env`, `*.key`, `credentials.json` and `secrets/`.
- Treat the personal Mihomo YAML as potentially sensitive; do not copy subscription URLs into documentation or tool output.
- Always ask before pushing to main. When uncertain, ask before push, deploy, messages or PR creation.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
