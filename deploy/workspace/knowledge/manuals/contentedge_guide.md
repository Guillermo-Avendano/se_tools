# ContentEdge Operator Guide (Current)

This guide is for practical SE Tools and MobiusRemoteCLI usage.
Only active, validated behavior is documented.

## Repository Context

If a request includes context_hint like:

tool=MobiusRemoteCLI | repo=SOURCE | worker=worker-3 | operation=adelete | command=...

the returned answer should prefer an executable command line.

## adelete Date Rules

The adelete timestamp cutoff uses:

- -t YYYYMMDDHHMMSS

Important behavior:

- -t is inclusive (equal-or-older).

### Common conversions

- Before March 2021 -> -t 20210228235959
- Before 2026-01-01 -> -t 20251231235959
- Before year 2024 -> -t 20231231235959

### Full command example

Input template:

adelete -s Mobius -u ADMIN -r {CONTENT_CLASS} -c -n -y ALL -o

Output for "before March 2021":

adelete -s Mobius -u ADMIN -r {CONTENT_CLASS} -c -n -y ALL -o -t 20210228235959

## vdrdbxml File Location Rules

Generated/import workflow files should use:

- /workspace/export-import

File names should include timestamp format:

- YYYY-MM-DD.HH.mm.ss

Purpose:

- Avoid collisions across multiple workers.

## LST Validation Rule

For .lst plans:

- If TOPIC-ID belongs to an index group, all members of that index group must be present in the same entry.
- Missing members make the entry invalid.

## Safety Guidance

- Validate repository and worker context before issuing destructive commands.
- Prefer explicit content class targeting with -r.
- Do not assume index-expression filters for adelete unless validated by docs.
