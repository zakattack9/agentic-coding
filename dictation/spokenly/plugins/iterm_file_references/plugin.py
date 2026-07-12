#!/usr/bin/env python3
"""Optional file-reference plugin for local Codex and Claude Code iTerm panes."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


STATE_VERSION = 1
MAX_CONTEXT_AGE_SECONDS = 5.0
MAX_PENDING_AGE_SECONDS = 120.0
MAX_PROJECT_FILES = 200_000
MAX_REFERENCE_WORDS = 24

DEFAULT_CONTEXT_STATE = (
    Path(tempfile.gettempdir()) / f"spokenly-iterm-context-{os.getuid()}.json"
)
DEFAULT_PENDING_DIR = (
    Path(tempfile.gettempdir()) / f"spokenly-file-references-{os.getuid()}"
)

REFERENCE_TRIGGER = re.compile(
    r"(?<!\w)(?:"
    r"@\s*(?:file\s+)?|"
    r"at\s+file(?=[^\s]+(?:\.|\s+dot\b))|"
    r"at\s+(?:file|reference|path)\s+|"
    r"(?:mention|reference|tag)\s+(?:the\s+)?file\s+"
    r")",
    re.IGNORECASE,
)
FILE_REFERENCE_ID = re.compile(r"^FILE_REF_([A-F0-9]{16})_([1-9][0-9]*)$")
ANY_FILE_REFERENCE_ID = re.compile(r"FILE_REF_([A-F0-9]{16})_([1-9][0-9]*)")
LEXICAL_TOKEN = re.compile(r"[^\W_]+|[./_-]", re.UNICODE)

EXTENSION_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    # Programming languages and web formats.
    "py": (("pie",), ("python",), ("python", "script")),
    "php": (("php", "script"), ("hypertext", "preprocessor")),
    "js": (("javascript",), ("java", "script"), ("ecmascript",)),
    "jsx": (("javascript", "xml"), ("react", "javascript")),
    "mjs": (("module", "javascript"), ("javascript", "module")),
    "cjs": (("common", "js"), ("common", "javascript")),
    "ts": (("typescript",), ("type", "script")),
    "tsx": (("typescript", "xml"), ("react", "typescript")),
    "rb": (("ruby",),),
    "rs": (("rust",),),
    "go": (("golang",), ("go", "language")),
    "java": (("java",),),
    "kt": (("kotlin",),),
    "kts": (("kotlin", "script"),),
    "swift": (("swift",),),
    "cs": (("c", "sharp"), ("see", "sharp")),
    "fs": (("f", "sharp"), ("eff", "sharp")),
    "fsx": (("f", "sharp", "script"), ("eff", "sharp", "script")),
    "c": (("c", "source"), ("see", "source")),
    "h": (("header",), ("c", "header"), ("see", "header")),
    "cc": (("c", "plus", "plus"), ("see", "plus", "plus")),
    "cpp": (("c", "plus", "plus"), ("see", "plus", "plus")),
    "cxx": (("c", "plus", "plus"), ("see", "plus", "plus")),
    "hpp": (("c", "plus", "plus", "header"),),
    "hxx": (("c", "plus", "plus", "header"),),
    "m": (("objective", "c"), ("objective", "see"), ("matlab",)),
    "mm": (("objective", "c", "plus", "plus"),),
    "scala": (("scala",),),
    "lua": (("lua",),),
    "dart": (("dart",),),
    "r": (("r", "language"), ("are", "language")),
    "ex": (("elixir",),),
    "exs": (("elixir", "script"),),
    "erl": (("erlang",),),
    "hrl": (("erlang", "header"),),
    "clj": (("clojure",),),
    "cljs": (("clojure", "script"),),
    "hs": (("haskell",),),
    "pl": (("perl",), ("prolog",)),
    "pm": (("perl", "module"),),
    "sol": (("solidity",),),
    "zig": (("zig",),),
    "asm": (("assembly",),),
    "s": (("assembly",),),
    "wasm": (("web", "assembly"),),
    "vue": (("vue",), ("view",)),
    "svelte": (("svelte",),),
    "css": (("cascading", "style", "sheet"), ("style", "sheet")),
    "scss": (("sass",), ("sassy", "css")),
    "sass": (("sass",),),
    "less": (("less",),),
    "html": (("hypertext", "markup", "language"),),
    "htm": (("html",), ("hypertext", "markup")),
    "svg": (
        ("scalable", "vector", "graphic"),
        ("scalable", "vector", "graphics"),
    ),
    "graphql": (("graph", "q", "l"), ("graph", "cue", "el")),
    "gql": (("graph", "q", "l"), ("graph", "cue", "el")),
    "sql": (("sequel",), ("structured", "query", "language")),
    "proto": (("protobuf",), ("protocol", "buffer")),
    "ipynb": (("jupyter", "notebook"), ("python", "notebook")),
    # Shells, configuration, infrastructure, and build files.
    "sh": (("shell",), ("shell", "script"), ("bash", "script")),
    "bash": (("bash",), ("bash", "script")),
    "zsh": (("z", "shell"), ("zed", "shell"), ("zsh", "script")),
    "fish": (("fish", "shell"),),
    "ps1": (("powershell",), ("power", "shell"), ("powershell", "script")),
    "tf": (("terraform",),),
    "tftest": (("terraform", "test"), ("tee", "eff", "test")),
    "tfvars": (
        ("terraform", "vars"),
        ("terraform", "variables"),
        ("tee", "eff", "vars"),
        ("tee", "eff", "variables"),
    ),
    "hcl": (
        ("hashicorp", "configuration", "language"),
        ("hashi", "corp", "configuration", "language"),
    ),
    "pkr": (("packer",),),
    "nix": (("nix",),),
    "gradle": (("gradle",),),
    "groovy": (("groovy",),),
    "mk": (("make",), ("makefile",)),
    "cmake": (("c", "make"), ("see", "make")),
    "conf": (("config",), ("configuration",)),
    "cfg": (("config",), ("configuration",)),
    "ini": (("initialization",), ("config",)),
    "env": (("environment",), ("environment", "file")),
    "properties": (("properties",), ("property", "file")),
    "service": (
        ("systemd", "service"),
        ("system", "d", "service"),
        ("service", "unit"),
    ),
    "path": (("systemd", "path"), ("system", "d", "path"), ("path", "unit")),
    "socket": (("systemd", "socket"), ("socket", "unit")),
    "timer": (("systemd", "timer"), ("timer", "unit")),
    "lock": (("lockfile",), ("lock", "file")),
    "dist": (("distribution",),),
    "tpl": (("template",),),
    "tmpl": (("template",),),
    "neon": (("neon",),),
    # Structured data and text.
    "md": (("markdown",), ("markdown", "file")),
    "mdx": (("markdown", "x"), ("markdown", "ex")),
    "txt": (("text",), ("text", "file"), ("plain", "text")),
    "log": (("log",), ("log", "file")),
    "json": (
        ("jason",),
        ("jay", "son"),
        ("javascript", "object", "notation"),
    ),
    "jsonl": (("json", "lines"), ("jason", "lines")),
    "ndjson": (("newline", "delimited", "json"),),
    "xml": (("extensible", "markup", "language"),),
    "yaml": (("yam", "ul"), ("why", "a", "em", "el")),
    "yml": (("yaml",), ("yam", "ul"), ("why", "em", "el")),
    "toml": (("tom", "el"), ("toms", "obvious", "minimal", "language")),
    "csv": (("comma", "separated", "values"), ("comma", "separated", "value")),
    "tsv": (("tab", "separated", "values"), ("tab", "separated", "value")),
    "map": (("source", "map"),),
    "avro": (("avro",),),
    "parquet": (("parquet",),),
    # Images, design assets, and fonts.
    "jpg": (("jpeg",), ("jay", "peg"), ("j", "peg")),
    "jpeg": (("jpg",), ("jay", "peg"), ("j", "peg")),
    "png": (("ping",), ("portable", "network", "graphic")),
    "gif": (("jif",), ("graphics", "interchange", "format")),
    "webp": (("web", "p"), ("web", "pee"), ("web", "picture")),
    "avif": (("a", "v", "image", "format"),),
    "bmp": (("bitmap",),),
    "tif": (("tiff",), ("tagged", "image", "file")),
    "tiff": (("tiff",), ("tagged", "image", "file")),
    "heic": (("high", "efficiency", "image"),),
    "ico": (("icon",), ("windows", "icon")),
    "drawio": (
        ("draw", "io"),
        ("draw", "eye", "oh"),
        ("draw", "dot", "io"),
        ("draw", "dot", "eye", "oh"),
        ("diagrams", "net"),
    ),
    "fla": (("flash", "authoring"), ("flash",)),
    "swf": (("shockwave", "flash"), ("flash",)),
    "woff": (("web", "open", "font", "format"),),
    "woff2": (
        ("woff", "two"),
        ("web", "open", "font", "format", "two"),
    ),
    "ttf": (("true", "type", "font"), ("truetype", "font")),
    "otf": (("open", "type", "font"), ("opentype", "font")),
    "eot": (("embedded", "open", "type"), ("embedded", "opentype")),
    # Documents and office files.
    "pdf": (("portable", "document", "format"),),
    "rtf": (("rich", "text", "format"),),
    "doc": (("word", "document"),),
    "docx": (("word", "document"), ("word", "doc")),
    "xls": (("excel",), ("excel", "spreadsheet")),
    "xlsx": (("excel",), ("excel", "spreadsheet")),
    "ppt": (("powerpoint",), ("power", "point")),
    "pptx": (("powerpoint",), ("power", "point")),
    "odt": (("open", "document", "text"),),
    "ods": (("open", "document", "spreadsheet"),),
    # Archives, databases, certificates, audio, and video.
    "zip": (("zip", "archive"),),
    "tar": (("tar", "archive"),),
    "gz": (("gzip",), ("g", "zip")),
    "tgz": (("tar", "gzip"), ("tar", "g", "zip")),
    "bz2": (("bzip", "two"), ("b", "zip", "two")),
    "xz": (("x", "z"), ("ex", "zee"), ("ex", "zed")),
    "7z": (("seven", "zip"),),
    "db": (("database",),),
    "sqlite": (("sqlite",), ("s", "q", "lite")),
    "sqlite3": (("sqlite", "three"), ("s", "q", "lite", "three")),
    "pem": (("pem",), ("certificate",)),
    "crt": (("certificate",),),
    "cer": (("certificate",),),
    "key": (("key", "file"), ("private", "key")),
    "mp3": (("m", "p", "three"), ("audio",)),
    "mp4": (("m", "p", "four"), ("video",)),
    "m4a": (("m", "four", "a"), ("audio",)),
    "wav": (("wave",), ("waveform", "audio")),
    "flac": (("flack",), ("lossless", "audio")),
    "mov": (("quicktime",), ("movie",)),
    "avi": (("audio", "video", "interleave"),),
    "mkv": (("matroska",),),
    "webm": (("web", "m"), ("web", "video")),
}

SPOKEN_CHARACTERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "a": (("a",),),
    "b": (("bee",),),
    "c": (("see",), ("sea",)),
    "d": (("dee",),),
    "e": (("ee",),),
    "f": (("eff",),),
    "g": (("gee",),),
    "h": (("aitch",),),
    "i": (("eye",),),
    "j": (("jay",),),
    "k": (("kay",),),
    "l": (("el",),),
    "m": (("em",),),
    "n": (("en",),),
    "o": (("oh",),),
    "p": (("pee",),),
    "q": (("cue",), ("queue",)),
    "r": (("are",),),
    "s": (("ess",),),
    "t": (("tee",),),
    "u": (("you",),),
    "v": (("vee",),),
    "w": (("double", "you"), ("double", "u")),
    "x": (("ex",),),
    "y": (("why",),),
    "z": (("zee",), ("zed",)),
    "0": (("zero",),),
    "1": (("one",),),
    "2": (("two",), ("too",)),
    "3": (("three",),),
    "4": (("four",), ("for",)),
    "5": (("five",),),
    "6": (("six",),),
    "7": (("seven",),),
    "8": (("eight",),),
    "9": (("nine",),),
}


@dataclass(frozen=True)
class ItermContext:
    window_id: str
    tab_id: str
    session_id: str
    tty: str
    job_pid: int
    process_title: str
    path: Path
    hostname: str
    ssh_integration_level: int
    observed_at: float


@dataclass(frozen=True)
class ProjectContext:
    session: ItermContext
    harness: str
    harness_pid: int
    cwd: Path
    project_root: Path


@dataclass(frozen=True)
class ProjectFile:
    relative_path: Path
    canonical_path: Path


@dataclass(frozen=True)
class SpeechToken:
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class AliasEntry:
    candidate: ProjectFile
    kind: int


@dataclass(frozen=True)
class ResolvedReference:
    start: int
    end: int
    phrase: str
    expansion: str
    canonical_path: Path


@dataclass
class PendingReferences:
    nonce: str
    pointer_path: Path | None
    manifest_path: Path
    expansions: dict[str, str]
    expected_counts: dict[str, int]
    context: ProjectContext | None
    original_transcript: str
    resolved_transcript: str | None


@dataclass
class PreparedReferences:
    snippets: list[dict[str, object]]
    pending: PendingReferences | None
    warnings: list[str]


def is_iterm_app(active_app: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", active_app.casefold())
    return (
        normalized in {"iterm", "iterm2", "comgooglecodeiterm2"}
        or normalized.startswith("iterm2")
        or normalized.endswith("itermapp")
        or "comgooglecodeiterm2" in normalized
    )


def _read_private_json(path: Path) -> object:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"state is not a regular file: {path}")
    if info.st_uid != os.getuid():
        raise ValueError(f"state is not owned by the current user: {path}")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError(f"state is writable by another user: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_iterm_context(
    state_path: Path = DEFAULT_CONTEXT_STATE,
    max_age_seconds: float = MAX_CONTEXT_AGE_SECONDS,
) -> ItermContext:
    data = _read_private_json(state_path)
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise ValueError("unsupported iTerm context state")

    required_strings = (
        "window_id",
        "tab_id",
        "session_id",
        "tty",
        "process_title",
        "path",
        "hostname",
    )
    values: dict[str, str] = {}
    for key in required_strings:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"iTerm context is missing {key}")
        values[key] = value

    job_pid = data.get("job_pid")
    observed_at = data.get("observed_at")
    ssh_level = data.get("ssh_integration_level", 0)
    if not isinstance(job_pid, int) or job_pid <= 1:
        raise ValueError("iTerm context has an invalid foreground job")
    if not isinstance(observed_at, (int, float)):
        raise ValueError("iTerm context has an invalid observation time")
    if not isinstance(ssh_level, int) or ssh_level < 0:
        raise ValueError("iTerm context has an invalid SSH integration level")
    age = time.time() - float(observed_at)
    if age < -1 or age > max_age_seconds:
        raise ValueError("iTerm context is stale")
    if ssh_level:
        raise ValueError("remote iTerm sessions are not supported")

    context_path = Path(values["path"]).expanduser()
    if not context_path.is_absolute():
        raise ValueError("iTerm context path is not absolute")

    return ItermContext(
        window_id=values["window_id"],
        tab_id=values["tab_id"],
        session_id=values["session_id"],
        tty=values["tty"],
        job_pid=job_pid,
        process_title=values["process_title"],
        path=context_path,
        hostname=values["hostname"],
        ssh_integration_level=ssh_level,
        observed_at=float(observed_at),
    )


def _process_record(pid: int) -> tuple[int, str, str] | None:
    """Read parent, TTY, and arguments in one bounded `ps` invocation."""
    try:
        completed = subprocess.run(
            [
                "/bin/ps",
                "-p",
                str(pid),
                "-o",
                "ppid=",
                "-o",
                "tty=",
                "-o",
                "args=",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    fields = completed.stdout.strip().split(maxsplit=2)
    if len(fields) < 2:
        return None
    try:
        parent = int(fields[0])
    except ValueError:
        return None
    arguments = fields[2] if len(fields) == 3 else ""
    return parent, fields[1], arguments


def _harness_name(*identifiers: str) -> str | None:
    normalized = tuple(value.casefold() for value in identifiers if value)
    if any(re.search(r"(?:^|\b)claude(?:\b|$)", value) for value in normalized):
        return "claude"
    if any(
        re.search(r"(?:^|\b)codex(?:[-a-z0-9]*)(?:\b|$)", value) for value in normalized
    ):
        return "codex"
    return None


def _normalized_tty(value: str) -> str:
    return Path(value).name if value.startswith("/dev/") else value.strip()


def detect_harness(
    context: ItermContext, verify_process: bool = True
) -> tuple[str, int]:
    try:
        os.kill(context.job_pid, 0)
    except OSError as error:
        if verify_process:
            raise ValueError(
                "the focused iTerm process is no longer running"
            ) from error

    if not verify_process:
        harness = _harness_name(context.process_title)
        if harness:
            return harness, context.job_pid
        raise ValueError("the focused iTerm pane is not running Codex or Claude Code")

    # iTerm's jobPid may point at a foreground child owned by the harness, such
    # as an MCP server, language server, or shell command. Walk only ancestors
    # on the same TTY and bind to the stable Codex/Claude process.
    expected_tty = _normalized_tty(context.tty)
    pid = context.job_pid
    visited: set[int] = set()
    for depth in range(16):
        if pid <= 1 or pid in visited:
            break
        visited.add(pid)
        record = _process_record(pid)
        if record is None:
            harness = _harness_name(context.process_title if depth == 0 else "")
            if harness:
                return harness, pid
            break
        parent, process_tty, arguments = record
        process_tty = _normalized_tty(process_tty)
        if (
            process_tty
            and process_tty not in {"?", "??"}
            and process_tty != expected_tty
        ):
            break
        argument_name = Path(arguments.split(maxsplit=1)[0]).name if arguments else ""
        title = context.process_title if depth == 0 else ""
        harness = _harness_name(title, argument_name)
        if harness:
            return harness, pid
        pid = parent
    raise ValueError("the focused iTerm pane is not running Codex or Claude Code")


def _process_cwd(pid: int) -> Path | None:
    executable = shutil.which("lsof")
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [executable, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("n/"):
            candidate = Path(line[1:])
            if candidate.is_dir():
                return candidate.resolve()
    return None


def _git_toplevel(cwd: Path) -> Path:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("unable to discover the active Git worktree") from error
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ValueError("the focused harness is not inside a Git worktree")
    root = Path(completed.stdout.strip()).resolve()
    if not root.is_dir():
        raise ValueError("the active Git worktree no longer exists")
    return root


def resolve_project_context(
    active_app: str,
    state_path: Path = DEFAULT_CONTEXT_STATE,
    verify_process: bool = True,
    max_age_seconds: float = MAX_CONTEXT_AGE_SECONDS,
) -> ProjectContext:
    if not is_iterm_app(active_app):
        raise ValueError("the focused application is not iTerm2")
    session = read_iterm_context(state_path, max_age_seconds=max_age_seconds)
    harness, harness_pid = detect_harness(session, verify_process=verify_process)

    session_cwd = session.path.resolve()
    if not session_cwd.is_dir():
        raise ValueError("the focused iTerm working directory no longer exists")
    process_cwd = _process_cwd(harness_pid) if verify_process else None
    cwd = process_cwd or session_cwd
    root = _git_toplevel(cwd)
    try:
        cwd.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "the harness working directory is outside its worktree"
        ) from error

    return ProjectContext(
        session=session,
        harness=harness,
        harness_pid=harness_pid,
        cwd=cwd,
        project_root=root,
    )


def list_project_files(
    project_root: Path,
    max_files: int = MAX_PROJECT_FILES,
    include_ignored: bool = True,
    include_standard: bool = True,
) -> list[ProjectFile]:
    commands: list[list[str]] = []
    if include_standard:
        commands.append(
            [
                "git",
                "-C",
                str(project_root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ]
        )
    if include_ignored:
        commands.append(
            [
                "git",
                "-C",
                str(project_root),
                "ls-files",
                "-z",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--directory",
            ]
        )
    outputs: list[bytes] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=8.0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(
                "unable to enumerate files in the active worktree"
            ) from error
        if completed.returncode != 0:
            raise ValueError("unable to enumerate files in the active worktree")
        outputs.append(completed.stdout)

    root = project_root.resolve()
    result: list[ProjectFile] = []
    seen: set[str] = set()
    for encoded in b"\0".join(outputs).split(b"\0"):
        if not encoded:
            continue
        relative_text = os.fsdecode(encoded)
        if relative_text.endswith("/"):
            # `--directory` collapses ignored directories so caches and
            # dependency trees are not recursively indexed. Individually
            # ignored files remain referenceable.
            continue
        if relative_text in seen:
            continue
        if any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in relative_text
        ):
            # Never insert a path containing a newline, tab, or other terminal
            # control character into an interactive agent prompt.
            continue
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        absolute = root / relative
        if not absolute.is_file():
            continue
        canonical = absolute.resolve()
        try:
            canonical.relative_to(root)
        except ValueError:
            # Do not let an in-project symlink attach a file outside the worktree.
            continue
        seen.add(relative_text)
        result.append(ProjectFile(relative, canonical))
        if len(result) > max_files:
            raise ValueError(
                "the active worktree contains too many referenceable files"
            )
    return result


def _identifier_words(value: str) -> tuple[str, ...]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    return tuple(
        match.group(0).casefold()
        for match in re.finditer(r"[^\W_]+", value, re.UNICODE)
    )


def _spelled_extension_variants(
    extension: str,
) -> tuple[tuple[str, ...], ...]:
    if (
        not 1 <= len(extension) <= 8
        or not extension.isascii()
        or not extension.isalnum()
    ):
        return ()

    spoken_by_character = [SPOKEN_CHARACTERS[character] for character in extension]
    spoken: list[tuple[str, ...]] = []
    for selected in itertools.product(*spoken_by_character):
        spoken.append(
            tuple(word for character_words in selected for word in character_words)
        )
    return (tuple(extension), *spoken)


@lru_cache(maxsize=None)
def _extension_variants(extension: str) -> tuple[tuple[str, ...], ...]:
    normalized = extension.casefold()
    configured = EXTENSION_ALIASES.get(normalized, ())
    defaults = ((normalized,),)
    spelled = _spelled_extension_variants(normalized)
    return tuple(dict.fromkeys(defaults + spelled + configured))


def _filename_variants(
    name: str, include_stem: bool
) -> list[tuple[tuple[str, ...], bool]]:
    leading_dot = name.startswith(".")
    working_name = name[1:] if leading_dot else name
    prefix = ("dot",) if leading_dot else ()
    if "." not in working_name or working_name.endswith("."):
        words = prefix + _identifier_words(working_name)
        return [(words, False)] if words else []

    components = working_name.split(".")
    extension = components[-1]
    component_variants: list[tuple[tuple[str, ...], ...]] = []
    for index, component in enumerate(components[:-1]):
        identifier = _identifier_words(component)
        if not identifier:
            return []
        if index == 0 or (
            len(component) > 1 and component.casefold() not in EXTENSION_ALIASES
        ):
            # Treat only known suffixes (plus single-letter suffixes such as
            # the `d` in `.d.ts`) as extensions. Spelling every ordinary
            # internal word makes names like `.complete.min.js.map` expand
            # combinatorially without improving realistic speech matching.
            component_variants.append((identifier,))
        else:
            component_variants.append(
                tuple(dict.fromkeys((identifier,) + _extension_variants(component)))
            )
    if not component_variants:
        return []

    stem_variants: set[tuple[str, ...]] = set()
    for selected_components in itertools.product(*component_variants):
        stem_with_dots: list[str] = list(prefix)
        stem_without_dots: list[str] = list(prefix)
        for index, words in enumerate(selected_components):
            if index:
                stem_with_dots.append("dot")
            stem_with_dots.extend(words)
            stem_without_dots.extend(words)
        stem_variants.add(tuple(stem_with_dots))
        stem_variants.add(tuple(stem_without_dots))
    variants = []
    for stem_words in stem_variants:
        variants.extend(
            (stem_words + ("dot",) + extension_words, False)
            for extension_words in _extension_variants(extension)
        )
    if include_stem:
        variants.extend((stem_words, True) for stem_words in stem_variants)
    return list(dict.fromkeys(variants))


def _path_component_words(component: str) -> tuple[str, ...]:
    if component.startswith("."):
        return ("dot",) + _identifier_words(component[1:])
    return _identifier_words(component)


def build_alias_index(
    files: Iterable[ProjectFile],
    wanted_aliases: set[tuple[str, ...]] | None = None,
) -> dict[tuple[str, ...], list[AliasEntry]]:
    aliases: dict[tuple[str, ...], list[AliasEntry]] = {}

    def add(tokens: tuple[str, ...], entry: AliasEntry) -> None:
        if (
            tokens
            and len(tokens) <= MAX_REFERENCE_WORDS
            and (wanted_aliases is None or tokens in wanted_aliases)
        ):
            aliases.setdefault(tokens, []).append(entry)

    for candidate in files:
        parts = candidate.relative_path.parts
        filename_variants = _filename_variants(parts[-1], include_stem=True)
        for tokens, is_stem in filename_variants:
            add(tokens, AliasEntry(candidate, 1 if is_stem else 2))

        parent_parts = parts[:-1]
        if not parent_parts:
            # A root-level basename is still only a basename. Treating it as a
            # higher-priority full path would silently beat duplicate basenames
            # in subdirectories even though no directory was spoken.
            continue
        # Include the full path and up to three trailing path components. This
        # makes spoken directory qualifiers deterministic without exploding the
        # alias index for deeply nested monorepos.
        starts = {0}
        for depth in range(1, min(3, len(parent_parts)) + 1):
            starts.add(len(parent_parts) - depth)
        for start in sorted(starts):
            selected_parents = parent_parts[start:]
            parent_words = [_path_component_words(part) for part in selected_parents]
            if any(not words for words in parent_words):
                continue
            for filename_tokens, is_stem in filename_variants:
                with_slashes: list[str] = []
                without_slashes: list[str] = []
                for words in parent_words:
                    if with_slashes:
                        with_slashes.append("slash")
                    with_slashes.extend(words)
                    without_slashes.extend(words)
                if with_slashes:
                    with_slashes.append("slash")
                with_slashes.extend(filename_tokens)
                without_slashes.extend(filename_tokens)
                kind = 3 if start else 4
                if is_stem:
                    kind -= 1
                add(tuple(with_slashes), AliasEntry(candidate, kind))
                add(tuple(without_slashes), AliasEntry(candidate, kind))
    return aliases


def speech_tokens(text: str, start: int) -> list[SpeechToken]:
    raw: list[SpeechToken] = []
    for match in LEXICAL_TOKEN.finditer(text, start):
        value = match.group(0).casefold()
        if value in {"_", "-", "underscore", "dash", "hyphen"}:
            continue
        if value == "." or value == "period":
            value = "dot"
        elif value == "/":
            value = "slash"
        raw.append(SpeechToken(value, match.start(), match.end()))
        if len(raw) >= MAX_REFERENCE_WORDS + 2:
            break

    result: list[SpeechToken] = []
    index = 0
    while index < len(raw):
        token = raw[index]
        if (
            token.value == "forward"
            and index + 1 < len(raw)
            and raw[index + 1].value == "slash"
        ):
            result.append(SpeechToken("slash", token.start, raw[index + 1].end))
            index += 2
            continue
        result.append(token)
        index += 1
    return result[:MAX_REFERENCE_WORDS]


def _candidate_under_cwd(candidate: ProjectFile, cwd_relative: Path) -> bool:
    try:
        candidate.relative_path.relative_to(cwd_relative)
        return True
    except ValueError:
        return False


def _select_alias(entries: list[AliasEntry], cwd_relative: Path) -> ProjectFile:
    best_kind = max(entry.kind for entry in entries)
    candidates = {
        entry.candidate.relative_path.as_posix(): entry.candidate
        for entry in entries
        if entry.kind == best_kind
    }
    if len(candidates) == 1:
        return next(iter(candidates.values()))

    under_cwd = {
        path: candidate
        for path, candidate in candidates.items()
        if _candidate_under_cwd(candidate, cwd_relative)
    }
    if under_cwd:
        return next(iter(under_cwd.values()))
    return next(iter(candidates.values()))


def _render_reference(candidate: ProjectFile, context: ProjectContext) -> str:
    absolute = context.project_root / candidate.relative_path
    relative = Path(os.path.relpath(absolute, context.cwd))
    round_trip = (context.cwd / relative).resolve()
    if round_trip != candidate.canonical_path:
        raise ValueError("a resolved file reference failed canonical path verification")
    try:
        candidate.canonical_path.relative_to(context.project_root)
    except ValueError as error:
        raise ValueError(
            "a resolved file reference escaped the active worktree"
        ) from error
    return "@" + relative.as_posix()


def resolve_references(
    text: str,
    context: ProjectContext,
    files: Iterable[ProjectFile],
) -> tuple[list[ResolvedReference], list[str]]:
    trigger_tokens = [
        (trigger, speech_tokens(text, trigger.end()))
        for trigger in REFERENCE_TRIGGER.finditer(text)
    ]
    wanted_aliases = {
        tuple(token.value for token in tokens[:length])
        for _trigger, tokens in trigger_tokens
        for length in range(1, len(tokens) + 1)
    }
    aliases = build_alias_index(files, wanted_aliases)
    cwd_relative = context.cwd.relative_to(context.project_root)
    resolved: list[ResolvedReference] = []
    warnings: list[str] = []
    consumed_until = 0

    for trigger, tokens in trigger_tokens:
        if trigger.start() < consumed_until:
            continue
        match_entries: list[AliasEntry] | None = None
        matched_length = 0
        for length in range(len(tokens), 0, -1):
            entries = aliases.get(tuple(token.value for token in tokens[:length]))
            if entries:
                match_entries = entries
                matched_length = length
                break
        if not match_entries:
            warnings.append(
                "unresolved spoken file reference near: "
                f"{text[trigger.start():trigger.end()].strip()} "
                f"(cwd={context.cwd}, worktree={context.project_root})"
            )
            continue

        candidate = _select_alias(match_entries, cwd_relative)
        phrase_end = tokens[matched_length - 1].end
        phrase = text[trigger.start() : phrase_end]

        expansion = _render_reference(candidate, context)
        resolved.append(
            ResolvedReference(
                start=trigger.start(),
                end=phrase_end,
                phrase=phrase,
                expansion=expansion,
                canonical_path=candidate.canonical_path,
            )
        )
        consumed_until = phrase_end
    return resolved, warnings


def _ensure_private_directory(path: Path, *, parents: bool = False) -> None:
    try:
        path.mkdir(mode=0o700, parents=parents, exist_ok=False)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"file-reference state is not a directory: {path}")
    if info.st_uid != os.getuid():
        raise ValueError(
            f"file-reference state is not owned by the current user: {path}"
        )
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)


def _ensure_pending_directories(pending_dir: Path) -> tuple[Path, Path]:
    _ensure_private_directory(pending_dir, parents=True)
    runs = pending_dir / "runs"
    sessions = pending_dir / "sessions"
    _ensure_private_directory(runs)
    _ensure_private_directory(sessions)
    return runs, sessions


def _session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


def _atomic_json_write(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _context_record(context: ProjectContext) -> dict[str, object]:
    return {
        "window_id": context.session.window_id,
        "tab_id": context.session.tab_id,
        "session_id": context.session.session_id,
        "tty": context.session.tty,
        "harness_pid": context.harness_pid,
        "harness": context.harness,
        "cwd": str(context.cwd),
        "project_root": str(context.project_root),
        "hostname": context.session.hostname,
    }


def clear_pending(
    pointer_path: Path,
    manifest_path: Path | None = None,
) -> None:
    pointer_nonce: str | None = None
    if pointer_path.exists():
        try:
            pointer = _read_private_json(pointer_path)
            if isinstance(pointer, dict) and isinstance(pointer.get("nonce"), str):
                pointer_nonce = pointer["nonce"]
                if manifest_path is None:
                    manifest_path = (
                        pointer_path.parents[1] / "runs" / f"{pointer_nonce}.json"
                    )
        except (OSError, ValueError):
            pass
    manifest_nonce = manifest_path.stem if manifest_path is not None else None
    if (
        manifest_path is None
        or pointer_nonce is None
        or pointer_nonce == manifest_nonce
    ):
        pointer_path.unlink(missing_ok=True)
    if manifest_path is not None:
        manifest_path.unlink(missing_ok=True)
        manifest_path.with_suffix(".fallback").unlink(missing_ok=True)


def clear_pending_for_session(
    session_id: str, pending_dir: Path = DEFAULT_PENDING_DIR
) -> None:
    _runs, sessions = _ensure_pending_directories(pending_dir)
    pointer = sessions / f"{_session_key(session_id)}.json"
    clear_pending(pointer)


def _replace_reference_occurrences(
    text: str,
    occurrences: object,
    expansions: dict[str, str],
    original_texts: dict[str, str],
) -> tuple[str, dict[str, int]]:
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError("file-reference manifest has invalid occurrences")

    pieces: list[str] = []
    counts: dict[str, int] = {}
    cursor = 0
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError("file-reference manifest has an invalid occurrence")
        start = occurrence.get("start")
        end = occurrence.get("end")
        reference_id = occurrence.get("reference_id")
        if (
            type(start) is not int
            or type(end) is not int
            or not isinstance(reference_id, str)
            or reference_id not in expansions
            or reference_id not in original_texts
            or start < cursor
            or end <= start
            or end > len(text)
        ):
            raise ValueError("file-reference manifest has an invalid occurrence")
        if text[start:end] != original_texts[reference_id]:
            raise ValueError("file-reference occurrence does not match its source")
        pieces.extend((text[cursor:start], expansions[reference_id]))
        counts[reference_id] = counts.get(reference_id, 0) + 1
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), counts


def prepare_file_references(
    text: str,
    active_app: str,
    context_path: Path = DEFAULT_CONTEXT_STATE,
    pending_dir: Path = DEFAULT_PENDING_DIR,
    verify_process: bool = True,
    max_context_age_seconds: float = MAX_CONTEXT_AGE_SECONDS,
) -> PreparedReferences:
    if not is_iterm_app(active_app):
        # Focus can legitimately move before Spokenly invokes the processor,
        # so an explicitly unrelated app makes this optional enrichment a
        # silent no-op rather than an error.
        return PreparedReferences([], None, [])

    if not REFERENCE_TRIGGER.search(text):
        # Clear a prior interrupted invocation without paying for project
        # discovery when this transcript has no file-reference directive.
        if is_iterm_app(active_app):
            try:
                session = read_iterm_context(
                    context_path, max_age_seconds=max_context_age_seconds
                )
                clear_pending_for_session(session.session_id, pending_dir)
            except (OSError, ValueError):
                pass
        return PreparedReferences([], None, [])

    context = resolve_project_context(
        active_app,
        context_path,
        verify_process=verify_process,
        max_age_seconds=max_context_age_seconds,
    )
    clear_pending_for_session(context.session.session_id, pending_dir)
    files = list_project_files(context.project_root, include_ignored=False)
    references, warnings = resolve_references(text, context, files)
    if warnings:
        # Ignored directories may contain enormous dependency/cache trees, so
        # pay for Git's ignored-file query only when the normal project index
        # did not resolve every explicit reference. `--directory` still keeps
        # ignored directories collapsed.
        ignored_files = list_project_files(
            context.project_root,
            include_ignored=True,
            include_standard=False,
        )
        files.extend(ignored_files)
        if len(files) > MAX_PROJECT_FILES:
            raise ValueError(
                "the active worktree contains too many referenceable files"
            )
        references, warnings = resolve_references(text, context, files)
    if not references:
        return PreparedReferences([], None, warnings)

    nonce = secrets.token_hex(8).upper()
    snippets: list[dict[str, object]] = []
    expansion_records: dict[str, dict[str, object]] = {}
    expected_counts: dict[str, int] = {}
    occurrences: list[dict[str, object]] = []
    by_phrase: dict[tuple[str, str], str] = {}

    for reference in references:
        key = (reference.phrase.casefold(), reference.expansion)
        reference_id = by_phrase.get(key)
        if reference_id is None:
            reference_id = f"FILE_REF_{nonce}_{len(by_phrase) + 1}"
            by_phrase[key] = reference_id
            snippets.append(
                {
                    "id": reference_id,
                    "triggers": [reference.phrase],
                    "text": reference.expansion,
                    "consume_trailing_punctuation": False,
                }
            )
            expansion_records[reference_id] = {
                "text": reference.expansion,
                "canonical_path": str(reference.canonical_path),
                "original_text": reference.phrase,
            }
        expected_counts[reference_id] = expected_counts.get(reference_id, 0) + 1
        occurrences.append(
            {
                "start": reference.start,
                "end": reference.end,
                "reference_id": reference_id,
            }
        )

    resolved_transcript, occurrence_counts = _replace_reference_occurrences(
        text,
        occurrences,
        {
            reference_id: str(record["text"])
            for reference_id, record in expansion_records.items()
        },
        {
            reference_id: str(record["original_text"])
            for reference_id, record in expansion_records.items()
        },
    )
    if occurrence_counts != expected_counts:
        raise ValueError("file-reference occurrence counts do not match expansions")

    runs, sessions = _ensure_pending_directories(pending_dir)
    manifest_path = runs / f"{nonce}.json"
    pointer_path = sessions / f"{_session_key(context.session.session_id)}.json"
    created_at = time.time()
    manifest = {
        "version": STATE_VERSION,
        "nonce": nonce,
        "created_at": created_at,
        "context": _context_record(context),
        "expansions": expansion_records,
        "expected_counts": expected_counts,
        "occurrences": occurrences,
        "original_transcript": text,
    }
    fallback_manifest = {
        "version": STATE_VERSION,
        "nonce": nonce,
        "created_at": created_at,
        "original_transcript": text,
        "expansions": {
            reference_id: str(record["original_text"])
            for reference_id, record in expansion_records.items()
        },
        "expected_counts": expected_counts,
    }
    pointer = {
        "version": STATE_VERSION,
        "nonce": nonce,
        "session_id": context.session.session_id,
        "created_at": created_at,
    }
    try:
        _atomic_json_write(manifest_path.with_suffix(".fallback"), fallback_manifest)
        _atomic_json_write(manifest_path, manifest)
        _atomic_json_write(pointer_path, pointer)
    except Exception:
        clear_pending(pointer_path, manifest_path)
        raise

    pending = PendingReferences(
        nonce=nonce,
        pointer_path=pointer_path,
        manifest_path=manifest_path,
        expansions={
            reference_id: str(record["text"])
            for reference_id, record in expansion_records.items()
        },
        expected_counts=expected_counts,
        context=context,
        original_transcript=text,
        resolved_transcript=resolved_transcript,
    )
    return PreparedReferences(snippets, pending, warnings)


def _validate_pending_age(created_at: object, max_age_seconds: float) -> None:
    if not isinstance(created_at, (int, float)):
        raise ValueError("file-reference state has no valid creation time")
    age = time.time() - float(created_at)
    if age < -1 or age > max_age_seconds:
        raise ValueError("file-reference state is stale")


def _load_manifest(
    nonce: str,
    pending_dir: Path,
    max_age_seconds: float,
) -> tuple[Path, dict[str, object]]:
    if not re.fullmatch(r"[A-F0-9]{16}", nonce):
        raise ValueError("file-reference state has an invalid nonce")
    manifest_path = pending_dir / "runs" / f"{nonce}.json"
    data = _read_private_json(manifest_path)
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise ValueError("invalid file-reference manifest")
    if data.get("nonce") != nonce:
        raise ValueError("file-reference manifest nonce mismatch")
    _validate_pending_age(data.get("created_at"), max_age_seconds)
    return manifest_path, data


def _nonce_from_model_output(text: str) -> str | None:
    nonces = {match.group(1) for match in ANY_FILE_REFERENCE_ID.finditer(text)}
    if len(nonces) > 1:
        raise ValueError("multiple file-reference runs appeared in one transcript")
    return next(iter(nonces), None)


def _recent_manifest_nonces(pending_dir: Path, max_age_seconds: float) -> set[str]:
    runs = pending_dir / "runs"
    if not runs.is_dir():
        return set()
    result: set[str] = set()
    for path in runs.glob("*.json"):
        try:
            data = _read_private_json(path)
            if not isinstance(data, dict):
                raise ValueError("invalid manifest")
            _validate_pending_age(data.get("created_at"), max_age_seconds)
            nonce = data.get("nonce")
            if isinstance(nonce, str) and re.fullmatch(r"[A-F0-9]{16}", nonce):
                result.add(nonce)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            path.with_suffix(".fallback").unlink(missing_ok=True)
    return result


def load_pending_file_references(
    model_output: str,
    active_app: str,
    context_path: Path = DEFAULT_CONTEXT_STATE,
    pending_dir: Path = DEFAULT_PENDING_DIR,
    verify_process: bool = True,
    max_context_age_seconds: float = MAX_CONTEXT_AGE_SECONDS,
    max_pending_age_seconds: float = MAX_PENDING_AGE_SECONDS,
) -> PendingReferences | None:
    output_nonce = _nonce_from_model_output(model_output)
    if output_nonce is None and not is_iterm_app(active_app):
        return None
    try:
        session = read_iterm_context(
            context_path, max_age_seconds=max_context_age_seconds
        )
    except (OSError, ValueError):
        if output_nonce:
            raise ValueError(
                "cannot verify the iTerm pane for a protected file reference"
            )
        return None

    _runs, sessions = _ensure_pending_directories(pending_dir)
    pointer_path = sessions / f"{_session_key(session.session_id)}.json"
    pointer_nonce: str | None = None
    try:
        pointer = _read_private_json(pointer_path)
        if not isinstance(pointer, dict) or pointer.get("version") != STATE_VERSION:
            raise ValueError("invalid file-reference session pointer")
        _validate_pending_age(pointer.get("created_at"), max_pending_age_seconds)
        value = pointer.get("nonce")
        if not isinstance(value, str):
            raise ValueError("file-reference session pointer has no nonce")
        if pointer.get("session_id") != session.session_id:
            raise ValueError("file-reference session pointer belongs to another pane")
        pointer_nonce = value
    except FileNotFoundError:
        pointer = None

    recent: set[str] = set()
    if output_nonce is None and pointer_nonce is None:
        recent = _recent_manifest_nonces(pending_dir, max_pending_age_seconds)

    nonce = pointer_nonce or output_nonce
    if nonce is None:
        if len(recent) == 1:
            # Even if Qwen removed every structural marker, retain enough
            # out-of-band state to detect a pane switch and fail closed.
            nonce = next(iter(recent))
        elif len(recent) > 1:
            raise ValueError("cannot identify the pending file-reference pane")
        else:
            return None
    if pointer_nonce and output_nonce and pointer_nonce != output_nonce:
        raise ValueError("protected file reference does not belong to the focused pane")

    manifest_path: Path | None = None
    try:
        manifest_path, manifest = _load_manifest(
            nonce, pending_dir, max_pending_age_seconds
        )
        current = resolve_project_context(
            active_app,
            context_path,
            verify_process=verify_process,
            max_age_seconds=max_context_age_seconds,
        )
        expected_context = manifest.get("context")
        if not isinstance(expected_context, dict):
            raise ValueError("file-reference manifest has no pane context")
        if expected_context != _context_record(current):
            raise ValueError("the focused iTerm pane or harness workspace changed")

        expansion_data = manifest.get("expansions")
        counts_data = manifest.get("expected_counts")
        occurrences = manifest.get("occurrences")
        original_transcript = manifest.get("original_transcript")
        if not isinstance(expansion_data, dict) or not isinstance(counts_data, dict):
            raise ValueError("file-reference manifest has invalid expansions")
        if not isinstance(original_transcript, str):
            raise ValueError("file-reference manifest has no original transcript")
        expansions: dict[str, str] = {}
        counts: dict[str, int] = {}
        original_texts: dict[str, str] = {}
        for reference_id, record in expansion_data.items():
            id_match = (
                FILE_REFERENCE_ID.fullmatch(reference_id)
                if isinstance(reference_id, str)
                else None
            )
            if id_match is None or id_match.group(1) != nonce:
                raise ValueError("file-reference manifest has an invalid identifier")
            if not isinstance(record, dict):
                raise ValueError("file-reference manifest has an invalid record")
            expansion = record.get("text")
            canonical_value = record.get("canonical_path")
            original_text = record.get("original_text")
            count = counts_data.get(reference_id)
            if not isinstance(expansion, str) or not expansion.startswith("@"):
                raise ValueError("file-reference manifest has an invalid expansion")
            if (
                not isinstance(canonical_value, str)
                or not isinstance(original_text, str)
                or not original_text
                or not isinstance(count, int)
                or count < 1
            ):
                raise ValueError("file-reference manifest has invalid path metadata")
            canonical = Path(canonical_value).resolve()
            if not canonical.is_file():
                raise ValueError("a referenced file no longer exists")
            try:
                canonical.relative_to(current.project_root)
            except ValueError as error:
                raise ValueError(
                    "a referenced file escaped the active worktree"
                ) from error
            rendered = (current.cwd / expansion[1:]).resolve()
            if rendered != canonical:
                raise ValueError(
                    "a protected file reference no longer resolves correctly"
                )
            expansions[reference_id] = expansion
            counts[reference_id] = count
            original_texts[reference_id] = original_text

        if set(counts_data) != set(expansion_data):
            raise ValueError(
                "file-reference manifest counts do not match its expansions"
            )
        resolved_transcript, occurrence_counts = _replace_reference_occurrences(
            original_transcript,
            occurrences,
            expansions,
            original_texts,
        )
        if occurrence_counts != counts:
            raise ValueError(
                "file-reference occurrence counts do not match its expansions"
            )
        return PendingReferences(
            nonce=nonce,
            pointer_path=pointer_path,
            manifest_path=manifest_path,
            expansions=expansions,
            expected_counts=counts,
            context=current,
            original_transcript=original_transcript,
            resolved_transcript=resolved_transcript,
        )
    except Exception:
        # Post-AI may still need the manifest to restore the original spoken
        # phrase. Cleanup happens after the verified or fallback expansion.
        raise


def _pointer_for_nonce(pending_dir: Path, nonce: str) -> Path | None:
    sessions = pending_dir / "sessions"
    if not sessions.is_dir():
        return None
    for path in sessions.glob("*.json"):
        try:
            pointer = _read_private_json(path)
            if isinstance(pointer, dict) and pointer.get("nonce") == nonce:
                return path
        except (OSError, ValueError):
            continue
    return None


def load_fallback_file_references(
    model_output: str,
    pending_dir: Path = DEFAULT_PENDING_DIR,
    max_pending_age_seconds: float = MAX_PENDING_AGE_SECONDS,
    nonce_hint: str | None = None,
) -> PendingReferences | None:
    """Load original spoken phrases without trusting pane or path state."""
    nonce = nonce_hint or _nonce_from_model_output(model_output)
    if nonce is None:
        recent = _recent_manifest_nonces(pending_dir, max_pending_age_seconds)
        if len(recent) != 1:
            return None
        nonce = next(iter(recent))
    if not re.fullmatch(r"[A-F0-9]{16}", nonce):
        raise ValueError("file-reference fallback has an invalid nonce")

    manifest_path = pending_dir / "runs" / f"{nonce}.json"
    fallback_path = manifest_path.with_suffix(".fallback")
    try:
        data = _read_private_json(fallback_path)
    except (OSError, ValueError):
        # The main manifest redundantly carries recovery data so losing either
        # one state file does not make this optional plugin block dictation.
        main_data = _read_private_json(manifest_path)
        if not isinstance(main_data, dict):
            raise ValueError("invalid file-reference manifest")
        main_expansions = main_data.get("expansions")
        if not isinstance(main_expansions, dict):
            raise ValueError("file-reference manifest has invalid expansions")
        data = {
            "version": main_data.get("version"),
            "nonce": main_data.get("nonce"),
            "created_at": main_data.get("created_at"),
            "original_transcript": main_data.get("original_transcript"),
            "expansions": {
                reference_id: record.get("original_text")
                for reference_id, record in main_expansions.items()
                if isinstance(record, dict)
            },
            "expected_counts": main_data.get("expected_counts"),
        }
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise ValueError("invalid file-reference fallback manifest")
    if data.get("nonce") != nonce:
        raise ValueError("file-reference fallback nonce mismatch")
    _validate_pending_age(data.get("created_at"), max_pending_age_seconds)

    original_transcript = data.get("original_transcript")
    expansion_data = data.get("expansions")
    counts_data = data.get("expected_counts")
    if not isinstance(original_transcript, str):
        raise ValueError("file-reference fallback has no original transcript")
    if not isinstance(expansion_data, dict) or not isinstance(counts_data, dict):
        raise ValueError("file-reference fallback has invalid expansions")

    expansions: dict[str, str] = {}
    counts: dict[str, int] = {}
    for reference_id, original_text in expansion_data.items():
        id_match = (
            FILE_REFERENCE_ID.fullmatch(reference_id)
            if isinstance(reference_id, str)
            else None
        )
        count = counts_data.get(reference_id)
        if id_match is None or id_match.group(1) != nonce:
            raise ValueError("file-reference fallback has an invalid identifier")
        if not isinstance(original_text, str) or not original_text:
            raise ValueError("file-reference fallback has invalid original text")
        if not isinstance(count, int) or count < 1:
            raise ValueError("file-reference fallback has invalid counts")
        expansions[reference_id] = original_text
        counts[reference_id] = count
    if set(counts_data) != set(expansion_data):
        raise ValueError("file-reference fallback counts do not match expansions")

    return PendingReferences(
        nonce=nonce,
        pointer_path=_pointer_for_nonce(pending_dir, nonce),
        manifest_path=manifest_path,
        expansions=expansions,
        expected_counts=counts,
        context=None,
        original_transcript=original_transcript,
        resolved_transcript=None,
    )


def finish_pending_file_references(pending: PendingReferences | None) -> None:
    if pending is not None:
        if pending.pointer_path is not None:
            clear_pending(pending.pointer_path, pending.manifest_path)
        else:
            pending.manifest_path.unlink(missing_ok=True)
            pending.manifest_path.with_suffix(".fallback").unlink(missing_ok=True)
