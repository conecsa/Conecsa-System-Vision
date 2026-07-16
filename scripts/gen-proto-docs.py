#!/usr/bin/env python3
"""Generate a Markdown reference for the Protocol Buffers under ``proto/``.

Stdlib-only, intentionally lightweight: it does not depend on ``protoc`` or any
descriptor library. It scans each ``.proto`` file line by line, attaches the
leading ``//`` comment block to the following ``message`` / ``enum`` / ``service``
/ ``rpc`` / field declaration, and renders one Markdown section per file.

Two ways to use it:

* **Standalone** — ``python scripts/gen-proto-docs.py`` writes
  ``docs/reference/proto.md`` to disk (handy to preview on GitHub or commit).
* **As a library** — the MkDocs ``gen-files`` hook (``docs/gen_api_pages.py``)
  imports :func:`render_all` and emits the same Markdown as a virtual page, so
  the reference is always rebuilt from the live ``.proto`` files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = REPO_ROOT / "proto"
OUTPUT = REPO_ROOT / "docs" / "reference" / "proto.md"

# Order the files so the most important contracts come first.
FILE_ORDER = [
    "inference.proto",
    "hardware.proto",
    "training.proto",
    "detection.proto",
    "shm.proto",
]

_BLOCK_RE = re.compile(r"^\s*(message|enum|service)\s+(\w+)")
_RPC_RE = re.compile(r"^\s*rpc\s+(\w+)\s*\((stream\s+)?([\w.]+)\)\s*returns\s*\((stream\s+)?([\w.]+)\)")
_FIELD_RE = re.compile(r"^\s*(repeated\s+|optional\s+)?([\w.]+)\s+(\w+)\s*=\s*(\d+)\s*;(?:\s*//\s*(.*))?")
_ENUM_VALUE_RE = re.compile(r"^\s*(\w+)\s*=\s*(\d+)\s*;(?:\s*//\s*(.*))?")
_RESERVED_RE = re.compile(r"^\s*reserved\b.*//\s*(.*)")


@dataclass
class Member:
    """A field of a message, a value of an enum, or an RPC of a service."""

    kind: str  # "field" | "enum_value" | "rpc"
    signature: str
    doc: str = ""


@dataclass
class Block:
    """A top-level ``message``, ``enum`` or ``service`` declaration."""

    kind: str  # "message" | "enum" | "service"
    name: str
    doc: str = ""
    members: list[Member] = field(default_factory=list)


@dataclass
class ProtoFile:
    """One parsed ``.proto`` file: its header comment and top-level blocks."""

    path: Path
    package: str = ""
    header: str = ""
    blocks: list[Block] = field(default_factory=list)


def _flush_comment(buffer: list[str]) -> str:
    """Join an accumulated ``//`` comment block into a single docstring.

    Strips the decorative box-drawing runs used as section separators, so a
    line like ``── Detection control ──────`` collapses to ``Detection control``
    and a pure separator line is dropped entirely.
    """
    cleaned: list[str] = []
    for line in buffer:
        stripped = line.strip(" ─-=")
        if stripped:
            cleaned.append(stripped)
    buffer.clear()
    return "\n".join(cleaned).strip()


def parse_proto(path: Path) -> ProtoFile:
    """Parse a single ``.proto`` file into a :class:`ProtoFile`."""
    pf = ProtoFile(path=path)
    pending: list[str] = []
    current: Block | None = None
    header_done = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if line.startswith("//"):
            pending.append(line[2:].strip())
            continue

        if line.startswith("syntax"):
            pending.clear()
            continue
        if line.startswith("package"):
            pf.package = line.split()[1].rstrip(";")
            # A comment block *above* the package line is the file header.
            if not header_done and pending:
                pf.header = _flush_comment(pending)
                header_done = True
            continue

        if not line:
            # A comment block followed by a blank line (commonly just below the
            # package declaration) is the file header, not a block's docstring.
            if not header_done and pending:
                pf.header = _flush_comment(pending)
                header_done = True
            continue

        inline_body: str | None = None
        if "{" in line and "}" in line:
            before, rest = line.split("{", 1)
            body, _after = rest.split("}", 1)
            inline_body = body.strip()
            line = before.strip()

        block_match = _BLOCK_RE.match(line)
        if block_match:
            current = Block(
                kind=block_match.group(1),
                name=block_match.group(2),
                doc=_flush_comment(pending),
            )
            pf.blocks.append(current)
            header_done = True

            # Handle inline declarations like: message Foo { string bar = 1; }
            if inline_body is not None:
                for stmt in (s.strip() for s in inline_body.split(";")):
                    if not stmt:
                        continue
                    stmt_line = stmt + ";"
                    if current.kind == "service":
                        m = _RPC_RE.match(stmt_line)
                        if m:
                            name, c_in, t_in, c_out, t_out = m.groups()
                            sig = (
                                f"{name}({'stream ' if c_in else ''}{t_in}) → "
                                f"{'stream ' if c_out else ''}{t_out}"
                            )
                            current.members.append(Member("rpc", sig, ""))
                    elif current.kind == "enum":
                        m = _ENUM_VALUE_RE.match(stmt_line)
                        if m:
                            name, num, trailing = m.groups()
                            current.members.append(
                                Member("enum_value", f"{name} = {num}", trailing or "")
                            )
                    else:  # message
                        m = _FIELD_RE.match(stmt_line)
                        if m:
                            rep, ftype, fname, num, trailing = m.groups()
                            prefix = (rep or "").strip()
                            sig = f"{(prefix + ' ') if prefix else ''}{ftype} {fname} = {num}"
                            current.members.append(Member("field", sig, trailing or ""))
                current = None

            continue
        if line.startswith("}"):
            current = None
            pending.clear()
            continue

        if current is not None:
            doc = _flush_comment(pending)
            if current.kind == "service":
                m = _RPC_RE.match(line)
                if m:
                    name, c_in, t_in, c_out, t_out = m.groups()
                    sig = (f"{name}({'stream ' if c_in else ''}{t_in}) → "
                           f"{'stream ' if c_out else ''}{t_out}")
                    current.members.append(Member("rpc", sig, doc))
                    continue
            elif current.kind == "enum":
                m = _ENUM_VALUE_RE.match(line)
                if m:
                    name, num, trailing = m.groups()
                    current.members.append(
                        Member("enum_value", f"{name} = {num}", trailing or doc))
                    continue
            else:  # message
                m = _FIELD_RE.match(line)
                if m:
                    rep, ftype, fname, num, trailing = m.groups()
                    prefix = (rep or "").strip()
                    sig = f"{(prefix + ' ') if prefix else ''}{ftype} {fname} = {num}"
                    current.members.append(Member("field", sig, trailing or doc))
                    continue
                r = _RESERVED_RE.match(line)
                if r:
                    current.members.append(Member("field", "*reserved*", r.group(1)))
                    continue
        pending.clear()

    return pf


def _render_file(pf: ProtoFile) -> list[str]:
    """Render one parsed file into Markdown lines."""
    out: list[str] = [f"## `proto/{pf.path.name}`", ""]
    if pf.package:
        out.append(f"*Package:* `{pf.package}`")
        out.append("")
    if pf.header:
        out.append(pf.header)
        out.append("")

    for block in pf.blocks:
        label = {"message": "message", "enum": "enum", "service": "service"}[block.kind]
        out.append(f"### `{label} {block.name}`")
        out.append("")
        if block.doc:
            out.append(block.doc)
            out.append("")
        if block.members:
            if block.kind == "service":
                out.append("| RPC | Description |")
                out.append("|---|---|")
                for mem in block.members:
                    out.append(f"| `{mem.signature}` | {mem.doc or ''} |")
            else:
                head = "Value" if block.kind == "enum" else "Field"
                out.append(f"| {head} | Description |")
                out.append("|---|---|")
                for mem in block.members:
                    out.append(f"| `{mem.signature}` | {mem.doc or ''} |")
            out.append("")
    return out


def render_all(proto_dir: Path = PROTO_DIR) -> str:
    """Render every ``.proto`` file in *proto_dir* to a single Markdown document."""
    files = sorted(
        proto_dir.glob("*.proto"),
        key=lambda p: (FILE_ORDER.index(p.name) if p.name in FILE_ORDER else 99, p.name),
    )
    lines = [
        "# Protocol Buffers reference",
        "",
        "Auto-generated from the `.proto` files under `proto/` by "
        "`scripts/gen-proto-docs.py`. Do not edit by hand — update the `.proto` "
        "comments instead.",
        "",
    ]
    for path in files:
        lines.extend(_render_file(parse_proto(path)))
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_all(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
