# Security policy

Please report vulnerabilities privately through the repository's GitHub
Security Advisory page. Do not attach real event logs: they contain filesystem
paths and metadata.

The scanner does not follow symbolic links and does not log file bytes. With
`--no-magika`, it does not read file contents at all. Security fixes are made
for the current minor release; there is not yet a long-term-support branch.
