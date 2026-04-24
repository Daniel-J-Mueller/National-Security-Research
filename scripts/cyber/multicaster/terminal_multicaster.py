#!/usr/bin/env python3
"""
Raw SSH terminal multicaster for owner-authorized server administration.

The tool opens one interactive terminal per exact target, clusters sessions by
recent terminal-screen similarity, shows one master terminal, and multicasts
typed bytes to the master plus the currently similar followers. Followers that
drift away from the master are split into their own similarity cohorts.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import ipaddress
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

if os.name != "nt":
    import fcntl
    import pty
    import selectors
    import termios
    import tty
else:
    import msvcrt


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TARGETS = (
    ROOT / "data" / "private" / "cybersecurity" / "multicaster-targets.txt"
)

TARGET_FIELD_NAMES = ("target", "ip", "host", "hostname", "address")
LABEL_FIELD_NAMES = ("target_label", "label", "name", "asset_id", "server")

ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
ISO_TIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[ t]\d{2}:\d{2}(?::\d{2})?(?:z|[+-]\d{2}:?\d{2})?)?\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
HEX_RE = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

ESCAPE_PREFIX = 0x1D  # Ctrl-]


@dataclass(frozen=True)
class TargetSpec:
    target: str
    label: str


@dataclass
class ManagedSession:
    index: int
    spec: TargetSpec
    command: list[str]
    process: subprocess.Popen[bytes] | None = None
    fd: int | None = None
    output_queue: "queue.Queue[bytes | None]" = field(default_factory=queue.Queue)
    buffer: bytearray = field(default_factory=bytearray)
    started_at: float = field(default_factory=time.monotonic)
    last_output_at: float = field(default_factory=time.monotonic)

    @property
    def display_name(self) -> str:
        return f"{self.index}:{self.spec.label}"

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def record_output(self, data: bytes, history_bytes: int) -> None:
        if not data:
            return
        self.buffer.extend(data)
        if len(self.buffer) > history_bytes:
            del self.buffer[: len(self.buffer) - history_bytes]
        self.last_output_at = time.monotonic()

    def write(self, data: bytes) -> bool:
        if not data or not self.is_alive():
            return False
        try:
            if self.fd is not None:
                os.write(self.fd, data)
                return True
            if self.process and self.process.stdin:
                self.process.stdin.write(data)
                self.process.stdin.flush()
                return True
        except (BrokenPipeError, OSError):
            return False
        return False


@dataclass
class Cohort:
    session_ids: list[int]
    seed_id: int


@dataclass
class MulticastState:
    cohorts: list[Cohort] = field(default_factory=list)
    active_cohort: int = 0
    master_id: int | None = None
    active_ids: set[int] = field(default_factory=set)
    prefix_pending: bool = False
    pending_similarity_check_at: float | None = None
    running: bool = True


def status(message: str) -> None:
    write_stdout(f"\r\n[multicaster] {message}\r\n".encode("utf-8", errors="replace"))


def write_stdout(data: bytes) -> None:
    try:
        stdout = getattr(sys.stdout, "buffer", None)
        if stdout is not None:
            stdout.write(data)
            stdout.flush()
        else:
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()
    except OSError:
        pass


def clean_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return label.strip("._") or "server"


def looks_like_single_target(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if any(marker in stripped for marker in ("/", "*", ",", "@")):
        return False
    if re.search(r"\s", stripped):
        return False
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass
    if len(stripped) > 253:
        return False
    labels = stripped.rstrip(".").split(".")
    if not labels:
        return False
    label_regex = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    return all(label_regex.match(label) for label in labels)


def validate_target(value: str) -> str:
    target = value.strip()
    if not looks_like_single_target(target):
        raise ValueError(
            f"Refusing target {value!r}. Provide one exact IP or DNS name per entry; "
            "ranges, CIDR blocks, wildcards, comma lists, user@host values, and "
            "whitespace targets are not accepted."
        )
    return target


def target_identity(value: str) -> str:
    stripped = value.strip()
    try:
        return ipaddress.ip_address(stripped).compressed.lower()
    except ValueError:
        return stripped.rstrip(".").lower()


def first_present(row: dict[str, Any], names: Iterable[str]) -> str | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def read_json_targets(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("targets", "servers", "hosts"):
            values = payload.get(key)
            if isinstance(values, list):
                return values
    raise ValueError(
        "JSON target file must be a list, or an object with a targets, servers, or hosts list."
    )


def read_jsonl_targets(path: Path) -> list[Any]:
    entries: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL on line {line_number}: {exc}") from exc
    return entries


def read_csv_targets(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        return [dict(row) for row in reader]


def read_text_targets(path: Path) -> list[str]:
    entries: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            entries.append(stripped)
    return entries


def read_targets(path: Path, max_targets: int) -> list[TargetSpec]:
    if not path.exists():
        raise FileNotFoundError(f"Target file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        raw_entries = read_json_targets(path)
    elif suffix == ".jsonl":
        raw_entries = read_jsonl_targets(path)
    elif suffix == ".csv":
        raw_entries = read_csv_targets(path)
    else:
        raw_entries = read_text_targets(path)

    targets: list[TargetSpec] = []
    seen: set[str] = set()
    for entry in raw_entries:
        if isinstance(entry, str):
            target_value = entry
            label_value = entry
        elif isinstance(entry, dict):
            target_value = first_present(entry, TARGET_FIELD_NAMES)
            label_value = first_present(entry, LABEL_FIELD_NAMES) or target_value
        else:
            raise ValueError(f"Unsupported target entry: {entry!r}")
        if not target_value:
            continue

        target = validate_target(str(target_value))
        identity = target_identity(target)
        if identity in seen:
            continue
        seen.add(identity)
        targets.append(TargetSpec(target=target, label=clean_label(str(label_value or target))))
        if len(targets) > max_targets:
            raise ValueError(f"Refusing more than --max-targets={max_targets} targets.")

    if not targets:
        raise ValueError(f"No usable targets found in {path}")
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open raw SSH terminals for authorized servers, cluster sufficiently "
            "similar screens, and multicast keystrokes to the active cluster."
        )
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=DEFAULT_TARGETS,
        help=(
            "Path to a JSON, JSONL, CSV, or TXT list of exact server IPs/hostnames. "
            "CSV columns may include target/ip/host and target_label/label/name. "
            "Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before opening live sessions. Confirms authorization for every target.",
    )
    parser.add_argument("--user", help="SSH username to prepend to every target.")
    parser.add_argument(
        "--ssh-path",
        default="ssh",
        help="Path to the ssh executable. Default: %(default)s",
    )
    parser.add_argument("--port", type=int, help="SSH port for every target.")
    parser.add_argument("--identity-file", type=Path, help="SSH private key path.")
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        help="Additional ssh -o option. Repeat for multiple options.",
    )
    parser.add_argument(
        "--ssh-arg",
        action="append",
        default=[],
        help="Additional raw ssh argument appended before the destination. Repeat as needed.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=10,
        help="SSH ConnectTimeout value in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--command-template",
        help=(
            "Advanced: replace the default ssh command with a tokenized template. "
            "Available fields: {target}, {label}, {destination}."
        ),
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.87,
        help="Screen similarity required to join or stay in a cohort. Default: %(default)s",
    )
    parser.add_argument(
        "--min-snapshot-chars",
        type=int,
        default=8,
        help="Minimum normalized screen length before drift-based cohort splitting. Default: %(default)s",
    )
    parser.add_argument(
        "--compare-chars",
        type=int,
        default=4000,
        help="Normalized terminal tail length used for similarity. Default: %(default)s",
    )
    parser.add_argument(
        "--history-bytes",
        type=int,
        default=12000,
        help="Raw output history retained per session. Default: %(default)s",
    )
    parser.add_argument(
        "--initial-settle-seconds",
        type=float,
        default=2.0,
        help="Seconds to collect initial terminal output before first clustering. Default: %(default)s",
    )
    parser.add_argument(
        "--settle-after-enter",
        type=float,
        default=0.45,
        help="Seconds to wait after Enter before checking follower drift. Default: %(default)s",
    )
    parser.add_argument(
        "--ignore-regex",
        action="append",
        default=[],
        help="Regex to blank before similarity scoring. Repeat for host-specific noise.",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=64,
        help="Safety cap for one multicaster run. Default: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate target input and print planned session commands without connecting.",
    )
    return parser


def check_ssh(path: str) -> str:
    resolved = shutil.which(path)
    if resolved:
        return resolved
    candidate = Path(path)
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        "ssh was not found. Install OpenSSH or pass --ssh-path with the executable path."
    )


def destination_for(args: argparse.Namespace, target: TargetSpec) -> str:
    if args.user:
        return f"{args.user}@{target.target}"
    return target.target


def split_template_command(template: str) -> list[str]:
    return shlex.split(template, posix=os.name != "nt")


def build_command(args: argparse.Namespace, target: TargetSpec, ssh_path: str) -> list[str]:
    destination = destination_for(args, target)
    if args.command_template:
        formatted = args.command_template.format(
            target=target.target,
            label=target.label,
            destination=destination,
        )
        command = split_template_command(formatted)
        if not command:
            raise ValueError("--command-template produced an empty command")
        return command

    command = [
        ssh_path,
        "-tt",
        "-o",
        f"ConnectTimeout={args.connect_timeout}",
        "-o",
        "ServerAliveInterval=30",
    ]
    if args.identity_file:
        command.extend(["-i", str(args.identity_file)])
    if args.port:
        command.extend(["-p", str(args.port)])
    for option in args.ssh_option:
        command.extend(["-o", option])
    command.extend(args.ssh_arg)
    command.append(destination)
    return command


def shell_join(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def copy_terminal_size(slave_fd: int) -> None:
    if os.name == "nt":
        return
    try:
        packed = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, packed)
    except OSError:
        pass


def resize_pty_sessions(sessions: list[ManagedSession]) -> None:
    if os.name == "nt":
        return
    try:
        packed = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return
    for session in sessions:
        if session.fd is None:
            continue
        try:
            fcntl.ioctl(session.fd, termios.TIOCSWINSZ, packed)
        except OSError:
            continue


def start_posix_session(session: ManagedSession) -> None:
    master_fd, slave_fd = pty.openpty()
    copy_terminal_size(slave_fd)
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    process = subprocess.Popen(
        session.command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        env=env,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)
    session.process = process
    session.fd = master_fd


def pipe_reader(session: ManagedSession) -> None:
    assert session.process is not None
    assert session.process.stdout is not None
    try:
        while True:
            data = session.process.stdout.read(4096)
            if not data:
                break
            session.output_queue.put(data)
    finally:
        session.output_queue.put(None)


def start_windows_session(session: ManagedSession) -> None:
    process = subprocess.Popen(
        session.command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    session.process = process
    thread = threading.Thread(target=pipe_reader, args=(session,), daemon=True)
    thread.start()


def start_sessions(sessions: list[ManagedSession]) -> None:
    for session in sessions:
        if os.name == "nt":
            start_windows_session(session)
        else:
            start_posix_session(session)


def terminate_sessions(sessions: list[ManagedSession]) -> None:
    for session in sessions:
        if session.fd is not None:
            try:
                os.close(session.fd)
            except OSError:
                pass
            session.fd = None
        process = session.process
        if process is None or process.poll() is not None:
            continue
        try:
            process.terminate()
        except OSError:
            continue
    deadline = time.monotonic() + 1.5
    for session in sessions:
        process = session.process
        if process is None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass


def unregister_posix_session(selector: Any, session: ManagedSession) -> None:
    if session.fd is None:
        return
    try:
        selector.unregister(session.fd)
    except Exception:
        pass
    try:
        os.close(session.fd)
    except OSError:
        pass
    session.fd = None


class RawTerminal:
    def __init__(self) -> None:
        self.fd: int | None = None
        self.original: list[Any] | None = None

    def __enter__(self) -> "RawTerminal":
        if os.name != "nt" and sys.stdin.isatty():
            self.fd = sys.stdin.fileno()
            self.original = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if os.name != "nt" and self.fd is not None and self.original is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original)


def compile_ignore_regexes(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"Invalid --ignore-regex {pattern!r}: {exc}") from exc
    return compiled


def normalized_snapshot(
    session: ManagedSession,
    ignore_regexes: list[re.Pattern[str]],
    compare_chars: int,
) -> str:
    text = bytes(session.buffer).decode("utf-8", errors="replace")
    text = ANSI_RE.sub(" ", text)
    text = ISO_TIME_RE.sub("<time>", text)
    text = TIME_RE.sub("<time>", text)
    text = HEX_RE.sub("<hex>", text)
    for value in (session.spec.target, session.spec.label):
        if value:
            text = re.sub(re.escape(value), "<host>", text, flags=re.IGNORECASE)
    for regex in ignore_regexes:
        text = regex.sub(" ", text)
    text = CONTROL_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip().lower()
    if compare_chars > 0:
        text = text[-compare_chars:]
    return text


def similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(a=left, b=right, autojunk=False).ratio()


def cluster_sessions(
    sessions: list[ManagedSession],
    threshold: float,
    ignore_regexes: list[re.Pattern[str]],
    compare_chars: int,
    preferred_seed_id: int | None = None,
) -> list[Cohort]:
    live = [session for session in sessions if session.is_alive()]
    if preferred_seed_id is not None:
        live.sort(key=lambda session: (session.index != preferred_seed_id, session.index))
    snapshots = {
        session.index: normalized_snapshot(session, ignore_regexes, compare_chars)
        for session in live
    }
    unassigned = {session.index for session in live}
    cohorts: list[Cohort] = []

    for seed in live:
        if seed.index not in unassigned:
            continue
        group = [seed.index]
        unassigned.remove(seed.index)
        seed_snapshot = snapshots[seed.index]
        for other in live:
            if other.index not in unassigned:
                continue
            score = similarity(seed_snapshot, snapshots[other.index])
            if score >= threshold:
                group.append(other.index)
                unassigned.remove(other.index)
        cohorts.append(Cohort(session_ids=group, seed_id=seed.index))

    cohorts.sort(key=lambda cohort: (-len(cohort.session_ids), cohort.session_ids))
    return cohorts


def session_by_id(sessions: list[ManagedSession], session_id: int) -> ManagedSession | None:
    for session in sessions:
        if session.index == session_id:
            return session
    return None


def select_cohort(
    state: MulticastState,
    sessions: list[ManagedSession],
    cohort_index: int,
) -> None:
    if not state.cohorts:
        state.active_cohort = 0
        state.master_id = None
        state.active_ids = set()
        return
    state.active_cohort = cohort_index % len(state.cohorts)
    cohort = state.cohorts[state.active_cohort]
    state.active_ids = set(cohort.session_ids)
    state.master_id = cohort.seed_id


def regroup(
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
    preferred_master: int | None = None,
) -> None:
    state.cohorts = cluster_sessions(
        sessions,
        args.similarity_threshold,
        ignore_regexes,
        args.compare_chars,
        preferred_master,
    )
    if not state.cohorts:
        state.active_ids = set()
        state.master_id = None
        status("No live sessions remain.")
        return

    selected_index = 0
    if preferred_master is not None:
        for index, cohort in enumerate(state.cohorts):
            if preferred_master in cohort.session_ids:
                selected_index = index
                cohort.seed_id = preferred_master
                break
    select_cohort(state, sessions, selected_index)
    describe_active_cohort(state, sessions)


def describe_active_cohort(state: MulticastState, sessions: list[ManagedSession]) -> None:
    if state.master_id is None:
        status("No active master.")
        return
    master = session_by_id(sessions, state.master_id)
    names = [
        session_by_id(sessions, session_id).display_name
        for session_id in sorted(state.active_ids)
        if session_by_id(sessions, session_id)
    ]
    status(
        "Active cohort "
        f"{state.active_cohort + 1}/{len(state.cohorts)}: "
        f"master={master.display_name if master else state.master_id}, "
        f"members={', '.join(names)}"
    )


def list_sessions(
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    snapshots = {
        session.index: normalized_snapshot(session, ignore_regexes, args.compare_chars)
        for session in sessions
    }
    lines = ["Session status:"]
    for session in sessions:
        live = "up" if session.is_alive() else f"down({session.process.returncode if session.process else '?'})"
        role = []
        if session.index == state.master_id:
            role.append("master")
        if session.index in state.active_ids:
            role.append("active")
        snapshot_len = len(snapshots[session.index])
        lines.append(
            f"  {session.display_name:<22} {live:<8} "
            f"snapshot={snapshot_len:<5} {'; '.join(role)}"
        )
    if state.cohorts:
        lines.append("Cohorts:")
        for index, cohort in enumerate(state.cohorts, start=1):
            marker = "*" if index - 1 == state.active_cohort else " "
            labels = []
            for session_id in cohort.session_ids:
                session = session_by_id(sessions, session_id)
                labels.append(session.display_name if session else str(session_id))
            lines.append(f" {marker} {index}: {', '.join(labels)}")
    status("\r\n".join(lines))


def show_help() -> None:
    status(
        "\r\n".join(
            [
                "Control prefix: Ctrl-]",
                "  Ctrl-] ?  show this help",
                "  Ctrl-] l  list sessions and cohorts",
                "  Ctrl-] g  regroup all live sessions by screen similarity",
                "  Ctrl-] n  switch to the next cohort",
                "  Ctrl-] m  rotate the master inside the active cohort",
                "  Ctrl-] q  quit and close local session processes",
                "  Ctrl-] Ctrl-]  send a literal Ctrl-] to the active cohort",
            ]
        )
    )


def display_master_tail(
    state: MulticastState,
    sessions: list[ManagedSession],
    max_bytes: int = 4096,
) -> None:
    if state.master_id is None:
        return
    master = session_by_id(sessions, state.master_id)
    if not master or not master.buffer:
        return
    write_stdout(bytes(master.buffer[-max_bytes:]))


def check_active_divergence(
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    if state.master_id is None:
        regroup(state, sessions, args, ignore_regexes)
        return
    master = session_by_id(sessions, state.master_id)
    if not master or not master.is_alive():
        status("Active master exited; regrouping live sessions.")
        regroup(state, sessions, args, ignore_regexes)
        return

    master_snapshot = normalized_snapshot(master, ignore_regexes, args.compare_chars)
    diverged: list[str] = []
    for session_id in sorted(list(state.active_ids)):
        if session_id == state.master_id:
            continue
        session = session_by_id(sessions, session_id)
        if not session or not session.is_alive():
            state.active_ids.discard(session_id)
            continue
        follower_snapshot = normalized_snapshot(session, ignore_regexes, args.compare_chars)
        if (
            len(master_snapshot) < args.min_snapshot_chars
            or len(follower_snapshot) < args.min_snapshot_chars
        ):
            continue
        score = similarity(master_snapshot, follower_snapshot)
        if score < args.similarity_threshold:
            diverged.append(f"{session.display_name} ({score:.2f})")
    if diverged:
        status(
            "Screen drift detected; splitting follower"
            + ("s" if len(diverged) > 1 else "")
            + f" into cohorts: {', '.join(diverged)}"
        )
        regroup(state, sessions, args, ignore_regexes, preferred_master=state.master_id)


def active_recipients(
    state: MulticastState,
    sessions: list[ManagedSession],
) -> list[ManagedSession]:
    recipients: list[ManagedSession] = []
    for session_id in sorted(state.active_ids):
        session = session_by_id(sessions, session_id)
        if session and session.is_alive():
            recipients.append(session)
    return recipients


def broadcast(
    data: bytes,
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
) -> None:
    recipients = active_recipients(state, sessions)
    if not recipients:
        status("No active live recipients; press Ctrl-] g to regroup.")
        return
    for session in recipients:
        session.write(data)
    if b"\r" in data or b"\n" in data:
        state.pending_similarity_check_at = time.monotonic() + args.settle_after_enter


def handle_prefix_command(
    command_byte: int,
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    state.prefix_pending = False
    if command_byte == ESCAPE_PREFIX:
        broadcast(bytes([ESCAPE_PREFIX]), state, sessions, args)
        return
    command = chr(command_byte).lower()
    if command == "?":
        show_help()
    elif command == "l":
        list_sessions(state, sessions, args, ignore_regexes)
    elif command == "g":
        regroup(state, sessions, args, ignore_regexes, preferred_master=state.master_id)
    elif command == "n":
        if state.cohorts:
            select_cohort(state, sessions, state.active_cohort + 1)
            describe_active_cohort(state, sessions)
            display_master_tail(state, sessions)
        else:
            status("No cohorts are available.")
    elif command == "m":
        if not state.active_ids:
            status("No active cohort to rotate.")
            return
        ordered = sorted(state.active_ids)
        current_index = ordered.index(state.master_id) if state.master_id in ordered else -1
        state.master_id = ordered[(current_index + 1) % len(ordered)]
        describe_active_cohort(state, sessions)
        display_master_tail(state, sessions)
    elif command == "q":
        state.running = False
    else:
        status(f"Unknown Ctrl-] command {command!r}; press Ctrl-] ? for help.")


def handle_input_bytes(
    data: bytes,
    state: MulticastState,
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    for value in data:
        if state.prefix_pending:
            handle_prefix_command(value, state, sessions, args, ignore_regexes)
            continue
        if value == ESCAPE_PREFIX:
            state.prefix_pending = True
            continue
        broadcast(bytes([value]), state, sessions, args)


def read_posix_initial(
    sessions: list[ManagedSession],
    args: argparse.Namespace,
) -> None:
    selector = selectors.DefaultSelector()
    for session in sessions:
        if session.fd is not None:
            selector.register(session.fd, selectors.EVENT_READ, session)
    deadline = time.monotonic() + args.initial_settle_seconds
    while time.monotonic() < deadline:
        timeout = max(0.0, deadline - time.monotonic())
        for key, _ in selector.select(timeout=timeout):
            session: ManagedSession = key.data
            try:
                data = os.read(session.fd, 4096) if session.fd is not None else b""
            except BlockingIOError:
                continue
            except OSError:
                data = b""
            if data:
                session.record_output(data, args.history_bytes)
            else:
                unregister_posix_session(selector, session)
    selector.close()


def read_windows_initial(
    sessions: list[ManagedSession],
    args: argparse.Namespace,
) -> None:
    deadline = time.monotonic() + args.initial_settle_seconds
    while time.monotonic() < deadline:
        drain_windows_output(sessions, args, None)
        time.sleep(0.02)


def drain_windows_output(
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    state: MulticastState | None,
) -> None:
    for session in sessions:
        while True:
            try:
                item = session.output_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            session.record_output(item, args.history_bytes)
            if state is not None and session.index == state.master_id:
                write_stdout(item)


def posix_loop(
    sessions: list[ManagedSession],
    state: MulticastState,
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ, "stdin")
    for session in sessions:
        if session.fd is not None:
            selector.register(session.fd, selectors.EVENT_READ, session)

    while state.running:
        timeout = 0.05
        if state.pending_similarity_check_at is not None:
            timeout = max(0.0, min(timeout, state.pending_similarity_check_at - time.monotonic()))
        for key, _ in selector.select(timeout=timeout):
            if key.data == "stdin":
                try:
                    data = os.read(sys.stdin.fileno(), 1024)
                except OSError:
                    data = b""
                if not data:
                    state.running = False
                    break
                handle_input_bytes(data, state, sessions, args, ignore_regexes)
                continue

            session: ManagedSession = key.data
            try:
                data = os.read(session.fd, 4096) if session.fd is not None else b""
            except BlockingIOError:
                continue
            except OSError:
                data = b""
            if not data:
                unregister_posix_session(selector, session)
                continue
            session.record_output(data, args.history_bytes)
            if session.index == state.master_id:
                write_stdout(data)

        if (
            state.pending_similarity_check_at is not None
            and time.monotonic() >= state.pending_similarity_check_at
        ):
            state.pending_similarity_check_at = None
            check_active_divergence(state, sessions, args, ignore_regexes)

        if state.master_id is not None:
            master = session_by_id(sessions, state.master_id)
            if master and not master.is_alive():
                status("Active master exited; regrouping.")
                regroup(state, sessions, args, ignore_regexes)
        if not any(session.is_alive() for session in sessions):
            status("All sessions exited.")
            state.running = False

    selector.close()


def windows_key_to_bytes() -> bytes:
    char = msvcrt.getwch()
    if char in ("\x00", "\xe0"):
        key = msvcrt.getwch()
        mapping = {
            "H": b"\x1b[A",
            "P": b"\x1b[B",
            "M": b"\x1b[C",
            "K": b"\x1b[D",
            "G": b"\x1b[H",
            "O": b"\x1b[F",
            "R": b"\x1b[2~",
            "S": b"\x1b[3~",
            "I": b"\x1b[5~",
            "Q": b"\x1b[6~",
        }
        return mapping.get(key, b"")
    if char == "\r":
        return b"\r"
    if char == "\x08":
        return b"\x7f"
    code = ord(char)
    if code <= 0xFF:
        return bytes([code])
    return char.encode("utf-8", errors="ignore")


def windows_loop(
    sessions: list[ManagedSession],
    state: MulticastState,
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> None:
    while state.running:
        drain_windows_output(sessions, args, state)
        if msvcrt.kbhit():
            data = windows_key_to_bytes()
            if data:
                handle_input_bytes(data, state, sessions, args, ignore_regexes)
        if (
            state.pending_similarity_check_at is not None
            and time.monotonic() >= state.pending_similarity_check_at
        ):
            state.pending_similarity_check_at = None
            check_active_divergence(state, sessions, args, ignore_regexes)
        if state.master_id is not None:
            master = session_by_id(sessions, state.master_id)
            if master and not master.is_alive():
                status("Active master exited; regrouping.")
                regroup(state, sessions, args, ignore_regexes)
        if not any(session.is_alive() for session in sessions):
            status("All sessions exited.")
            state.running = False
        time.sleep(0.01)


def run_interactive(
    sessions: list[ManagedSession],
    args: argparse.Namespace,
    ignore_regexes: list[re.Pattern[str]],
) -> int:
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive multicasting requires a real terminal on stdin.")

    start_sessions(sessions)
    status(f"Started {len(sessions)} session(s). Collecting initial screens...")

    if os.name == "nt":
        read_windows_initial(sessions, args)
    else:
        read_posix_initial(sessions, args)

    state = MulticastState()
    regroup(state, sessions, args, ignore_regexes)
    show_help()
    display_master_tail(state, sessions)

    old_winch_handler = None
    if os.name != "nt":
        old_winch_handler = signal.getsignal(signal.SIGWINCH)

        def handle_winch(signum: int, frame: object) -> None:
            resize_pty_sessions(sessions)

        signal.signal(signal.SIGWINCH, handle_winch)

    try:
        with RawTerminal():
            if os.name == "nt":
                windows_loop(sessions, state, args, ignore_regexes)
            else:
                posix_loop(sessions, state, args, ignore_regexes)
    finally:
        if os.name != "nt" and old_winch_handler is not None:
            signal.signal(signal.SIGWINCH, old_winch_handler)
        terminate_sessions(sessions)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not 0.0 <= args.similarity_threshold <= 1.0:
            raise ValueError("--similarity-threshold must be between 0.0 and 1.0")
        targets = read_targets(args.targets, args.max_targets)
        ignore_regexes = compile_ignore_regexes(args.ignore_regex)
        ssh_path = (
            args.ssh_path
            if args.dry_run or args.command_template
            else check_ssh(args.ssh_path)
        )
        sessions = [
            ManagedSession(
                index=index,
                spec=target,
                command=build_command(args, target, ssh_path),
            )
            for index, target in enumerate(targets, start=1)
        ]

        if args.dry_run:
            for session in sessions:
                print(f"{session.display_name}: {shell_join(session.command)}")
            return 0

        if not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to open live sessions without --i-own-these-servers. "
                "Only multicast terminals to systems you own or are explicitly authorized to administer."
            )

        return run_interactive(sessions, args, ignore_regexes)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
