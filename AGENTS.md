# Agents

Run one named site. Read `skills/aeo-audit/SKILL.md` and the playbook for the check you are doing. Do not paste those files into the prompt.

Commands and exit codes are in `README.md`. Reports are pass, warn, or fail. Do not invent a numeric score, traffic, or a citation rate.

Optional keys are listed in `README.md`. If a key is set, run the matching command. If it is unset, skip that check. Never print or commit a key value.

Write reports under `reports/` in the working directory, or in `AEO_DATA_DIR` when that is set. Do not commit `inventory/sites.toml`, `.env`, or `reports/`.
