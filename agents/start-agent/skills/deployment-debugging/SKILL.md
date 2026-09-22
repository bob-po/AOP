---
name: deployment-debugging
description: Diagnose build/start failures from real logs and apply minimal repairs (max 3).
---

# Deployment Debugging Skill

Process:

1. Read the actual stderr / docker logs (tools only; no guessing).
2. Classify: dependency missing, syntax/config error, port bind, crash-loop, health path wrong.
3. Apply the smallest fix (one dependency pin, one CMD change, one EXPOSE/port map, one env default).
4. Rebuild/restart and re-check with real health HTTP probe.
5. Stop after 3 failed repairs and report the last real error + logs path.

Never claim healthy unless HTTP probe succeeded.
