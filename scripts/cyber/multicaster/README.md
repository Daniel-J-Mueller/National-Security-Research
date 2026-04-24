# Terminal Multicaster

`terminal_multicaster.py` opens one SSH terminal per exact owner-authorized
server, groups sessions whose recent terminal output is sufficiently similar,
and multicasts typed bytes to the active group.

It shows only the active master terminal. Followers are watched in the
background; if a follower's screen drifts below the similarity threshold after
you press Enter, live sessions are reclustered and drifted followers split into
their own similar cohorts.

## Target Input

Use a private TXT, CSV, JSON, or JSONL file. TXT files are one exact IP or DNS
name per line. CSV files may use `target`, `ip`, `host`, `hostname`, or
`address`, plus optional labels such as `label` or `target_label`.

```text
server-a.example.internal
server-b.example.internal
server-c.example.internal
```

## Dry Run

```powershell
python scripts\cyber\multicaster\terminal_multicaster.py --targets .\targets.txt --user admin --dry-run
```

## Live Run

```powershell
python scripts\cyber\multicaster\terminal_multicaster.py --targets .\targets.txt --user admin --i-own-these-servers
```

Useful options:

- `--similarity-threshold 0.90` to make grouping stricter.
- `--ignore-regex "server-[0-9]+"` to blank host-specific text before scoring.
- `--ssh-option StrictHostKeyChecking=accept-new` to pass an OpenSSH option.
- `--identity-file .\id_ed25519` to use a key.

## Controls

Press `Ctrl-]` as the control prefix, then one command key:

- `?` shows help.
- `l` lists sessions and cohorts.
- `g` regroups all live sessions by current screen similarity.
- `n` switches to the next cohort.
- `m` rotates which session is the visible master inside the active cohort.
- `q` quits and closes the local SSH processes.
- `Ctrl-]` again sends a literal `Ctrl-]`.

## Safety Notes

Only use this for systems you own or are explicitly authorized to administer.
The script rejects ranges, CIDR blocks, wildcards, comma lists, and `user@host`
target values. It does not log commands or terminal output.
