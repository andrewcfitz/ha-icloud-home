"""Minimal vCard 3.0 handling: read FN, rewrite the HOME ADR, nothing else."""

from __future__ import annotations

import re

ADR_LINE = re.compile(r"^(?:[^.:;]+\.)?ADR(;[^:]*)?:", re.I)
HOME_TYPE = re.compile(r"type=[^;:]*\bhome\b", re.I)
FN_LINE = re.compile(r"^FN(?:;[^:\n]*)?:(.*)$", re.M | re.I)
GROUP_KIND = re.compile(r"^X-ADDRESSBOOKSERVER-KIND(?:;[^:\n]*)?:\s*group\s*$", re.M | re.I)


def unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def fold(line: str, limit: int = 75) -> str:
    """RFC 6350 folding at 75 octets without splitting a UTF-8 character."""
    parts, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > limit:
            parts.append(cur)
            # Continuation lines spend one octet on the leading space.
            cur, size, limit = ch, 1 + n, 75
        else:
            cur, size = cur + ch, size + n
    parts.append(cur)
    return "\r\n ".join(parts)


def escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def full_name(vcard: str) -> str | None:
    m = FN_LINE.search(unfold(vcard))
    return _unescape(m.group(1).strip()) if m else None


N_LINE = re.compile(r"^N(?:;[^:\n]*)?:(.*)$", re.M | re.I)
ORG_LINE = re.compile(r"^ORG(?:;[^:\n]*)?:(.*)$", re.M | re.I)


def display_name(vcard: str) -> str | None:
    """FN, else the structured name, else the organization."""
    if name := full_name(vcard):
        return name
    text = unfold(vcard)
    if m := N_LINE.search(text):
        family, given, *_ = [*re.split(r"(?<!\\);", m.group(1).strip()), "", ""]
        if name := " ".join(_unescape(p) for p in (given, family) if p):
            return name
    if m := ORG_LINE.search(text):
        if org := _unescape(re.split(r"(?<!\\);", m.group(1).strip())[0]):
            return org
    return None


def is_group(vcard: str) -> bool:
    return bool(GROUP_KIND.search(unfold(vcard)))


def set_home_address(vcard: str, address: dict[str, str]) -> str:
    """Return the vCard with its first HOME ADR replaced (or one appended)."""
    value = ";".join(
        ["", ""]
        + [
            escape(address.get(k) or "")
            for k in ("street", "city", "state", "postal_code", "country")
        ]
    )
    lines = unfold(vcard).replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        m = ADR_LINE.match(line)
        if m and HOME_TYPE.search(m.group(1) or ""):
            lines[i] = line[: m.end()] + value
            break
    else:
        end = max(i for i, line in enumerate(lines) if line.strip().upper() == "END:VCARD")
        lines.insert(end, "ADR;type=HOME:" + value)
    return "\r\n".join(fold(line) for line in lines)


def same(a: str, b: str) -> bool:
    return unfold(a).replace("\r\n", "\n") == unfold(b).replace("\r\n", "\n")
