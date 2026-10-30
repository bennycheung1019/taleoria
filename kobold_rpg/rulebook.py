"""Verified local RPG OS sources, retrieved narrowly by the current task."""
import hashlib
import json
from pathlib import Path
from .engine import RuleError

ROOT = Path(__file__).resolve().parent.parent / "rules" / "rpg_os_v1_01"


def section(text, heading, limit):
    marker = "\n" + heading + "\n"
    start = text.find(marker)
    if start < 0:
        raise RuleError("規則來源缺少預期章節：" + heading)
    start += len(marker)
    next_section = text.find("\n## ", start)
    body = text[start:next_section if next_section >= 0 else len(text)].strip()
    # Whole paragraphs only; do not invent a continuation for a truncated rule.
    paragraphs, selected, size = body.split("\n\n"), [], 0
    for paragraph in paragraphs:
        if selected and size + len(paragraph) > limit:
            break
        selected.append(paragraph)
        size += len(paragraph)
    return "\n\n".join(selected)


def verified_sources():
    manifest = json.loads((ROOT / "sources.json").read_text())
    bodies = {}
    for name, record in manifest["files"].items():
        data = (ROOT / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise RuleError("RPG OS 規則原文已改變；請明確檢查並更新來源紀錄")
        bodies[name] = data.decode("utf-8")
    return bodies


def physical_excerpts():
    bodies=verified_sources()
    paragraph=next(p for p in bodies['ENGINE_freeform.md'].split('\n\n') if p.startswith('Resolve uncertain outcomes by GM judgment'))
    return 'SOURCE: ENGINE/freeform.md — resolution\n'+paragraph


def excerpts(action_kind):
    bodies=verified_sources()
    selected = [
        ("OS/LAW.md — Understand", section(bodies["OS_LAW.md"], "## Understand", 1200)),
        ("OS/LAW.md — Resolve", section(bodies["OS_LAW.md"], "## Resolve", 1500)),
    ]
    if action_kind in {"speak", "interact", "wait", "freeform"}:
        selected.append(("ENGINE/freeform.md — Social requests",
                         section(bodies["ENGINE_freeform.md"], "### Social requests", 1900)))
        selected.append(("OS/AGENT_STATE.md — Personal anchors",
                         section(bodies["OS_AGENT_STATE.md"], "## Personal anchors and decisions (v1.01)", 1000)))
        selected.append(("OS/AGENT_STATE.md — Nature and control",
                         next(p for p in bodies["OS_AGENT_STATE.md"].split("\n\n")
                              if p.startswith("Allow affection, pride, pleasure and hope"))))
        selected.append(("OS/AGENT_STATE.md — Portray and change",
                         section(bodies["OS_AGENT_STATE.md"], "## Portray and change", 1900)))
    return "\n\n".join(f"SOURCE: {name}\n{text}" for name, text in selected)
