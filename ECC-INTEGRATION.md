# ECC integration for Rovyn

Source: https://github.com/affaan-m/ECC

Reviewed revision: `76aaa77df6adc5b889e689007bf99b9a4f74af34`.
License: MIT, reproduced in `.agents/ECC-LICENSE`.

This project installs three instruction skills locally, using Codex's
`.agents/skills/<name>/SKILL.md` layout:

| Skill | Upstream path | Use in Rovyn |
| --- | --- | --- |
| search-first | skills/search-first | Look for existing code and maintained integrations before adding abstractions |
| iterative-retrieval | skills/iterative-retrieval | Find relevant context progressively; keep agent handoffs focused |
| verification-loop | .agents/skills/verification-loop | Verify behavior and report actual build, types, lint and test evidence |

The vendored skill files are unchanged. `AGENTS.md` supplies the project-specific
application: Python/FastAPI, React/Vite, existing check commands, focused testing,
VPN isolation invariants and the established Git author. Skills are available
for discovery on the next turn when this repository is the project/work directory;
their instructions were also read and applied during this integration.

ECC includes many other agents, hooks, MCP integrations and memory systems.
These are not prerequisites for the three practices installed here. This
integration does not execute ECC's bootstrap scripts, change global Codex model
or permissions, enable hooks, install MCP servers, send telemetry, or create
background jobs. Future additions should solve a concrete project need and be
reviewed individually.

## Update

1. Inspect upstream changes at a specific commit and read the changed skill
   instructions and any referenced files before using them.
2. Compare only these three skill directories and the license. Review executable
   additions, required external services and changed data handling.
3. Use the built-in skill installer's GitHub helper with `--ref <commit>` and a
   temporary destination. Review the diff before replacing vendored files.
4. Update the revision here, preserve license notices, check local paths and
   review `git diff --check`. Commit the reviewed update.

## Current follow-up

The previously observed Remnawave traffic-history HTTP 404 remains an independent
application issue. This workflow integration does not claim to repair it or to
prove the current state of production.
