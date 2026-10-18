"""Minimal S-expression reader/writer for KiCad files.

Lists become Python lists. Unquoted atoms (keywords, numbers) are `Sym`;
quoted strings are plain `str`. `dumps` writes KiCad's layout closely
enough that KiCad's own save produces a small diff.
"""
from __future__ import annotations

import re


class Sym(str):
    """An unquoted atom: keyword, number or yes/no."""


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def loads(text: str):
    stack: list[list] = [[]]
    pos = 0
    end = len(text)
    while pos < end:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad s-expression at {pos}: {text[pos:pos + 40]!r}")
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group(3) is not None:
            stack[-1].append(m.group(3).replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(Sym(m.group(4)))
    if len(stack) != 1:
        raise ValueError("unbalanced parentheses")
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def _atom(x) -> str:
    if isinstance(x, Sym):
        return str(x)
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return fmt_num(x)
    s = str(x).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def fmt_num(v: float) -> str:
    if isinstance(v, int):
        return str(v)
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# Lists whose children stay on one line (KiCad style).
_INLINE = {"at", "xy", "size", "start", "end", "mid", "center", "radius", "length", "width", "type",
           "color", "uuid", "diameter", "offset", "justify", "font", "thickness", "unit", "body_style",
           "exclude_from_sim", "in_bom", "on_board", "in_pos_files", "dnp", "hide", "fields_autoplaced",
           "show_name", "do_not_autoplace", "reference", "page", "shape", "pin_numbers", "pin_names",
           "embedded_fonts", "version", "generator", "generator_version", "paper", "lib_id", "extends",
           "number", "name", "bold", "italic", "fill", "duplicate_pin_numbers_are_jumpers", "power",
           "date", "rev", "title", "company", "comment", "embedded_files", "convert"}


def dumps(node, indent: int = 0) -> str:
    if not isinstance(node, list):
        return _atom(node)
    if not node:
        return "()"
    head = _atom(node[0])
    kids = node[1:]
    simple = all(not isinstance(k, list) for k in kids)
    if simple:
        return "(" + " ".join([head] + [_atom(k) for k in kids]) + ")"
    if node[0] in ("pts",):
        inner = " ".join(dumps(k, 0) for k in kids)
        tab = "\t" * (indent + 1)
        return f"({head}\n{tab}{inner}\n" + "\t" * indent + ")"
    if node[0] in _INLINE and len(dumps_flat(node)) < 100:
        return dumps_flat(node)
    parts = [head]
    # leading atoms stay on the head line
    i = 0
    while i < len(kids) and not isinstance(kids[i], list):
        parts.append(_atom(kids[i]))
        i += 1
    out = "(" + " ".join(parts)
    tab = "\t" * (indent + 1)
    for k in kids[i:]:
        out += "\n" + tab + (dumps(k, indent + 1) if isinstance(k, list) else _atom(k))
    out += "\n" + "\t" * indent + ")"
    return out


def dumps_flat(node) -> str:
    if not isinstance(node, list):
        return _atom(node)
    return "(" + " ".join(dumps_flat(k) for k in node) + ")"


# ---- small query helpers ----------------------------------------------------------
def find(node, key):
    """First child list whose head is `key`."""
    for k in node[1:] if isinstance(node, list) else []:
        if isinstance(k, list) and k and k[0] == key:
            return k
    return None


def find_all(node, key):
    return [k for k in node[1:] if isinstance(k, list) and k and k[0] == key]


def prop(node, name):
    for k in find_all(node, "property"):
        if k[1] == name:
            return k
    return None
