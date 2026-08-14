#!/usr/bin/env python3
"""Lint every skill in this repository.

Run from the repo root::

    python3 tools/validate_skills.py

Checks, in rough order of how often they catch something real:

* Frontmatter parses, and has the required ``name`` and ``description``.
* ``name`` matches the directory name — a mismatch means the skill will not
  resolve when invoked by name.
* ``description`` is substantial and states *when* to use the skill, not only
  what it does. Description quality is the single biggest determinant of
  whether a skill ever triggers, so it is checked rather than assumed.
* Every relative link and referenced file actually exists. A skill that points
  at a missing reference wastes an agent's turn discovering that.
* Every ``python3 -m gtmkit.<module>`` invocation names a module that exists.
* SKILL.md stays under the length where it stops being loaded usefully.
* No unresolved placeholders (``TODO``, ``TBD``, ``XXX``, ``FIXME``, ``...``)
  left in shipped text.

Exit code is 0 when clean, 1 when any error is found. Warnings do not fail the
build but are printed.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

MAX_SKILL_LINES = 500
MIN_DESCRIPTION_CHARS = 120

# A description that never says when to use the skill will not trigger reliably.
TRIGGER_HINTS = ("use this", "use it", "whenever", "when the user", "when someone")

PLACEHOLDERS = ("TODO", "TBD", "XXX", "FIXME", "PLACEHOLDER", "Lorem ipsum")

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(r"`(references/[^`]+|assets/[^`]+|examples/[^`]+)`")
GTMKIT_RE = re.compile(r"gtmkit\.([a-z_]+)")


class Findings:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, skill: str, message: str) -> None:
        self.errors.append("%s: %s" % (skill, message))

    def warn(self, skill: str, message: str) -> None:
        self.warnings.append("%s: %s" % (skill, message))


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], int]:
    """Parse the leading YAML block without requiring PyYAML.

    Only flat ``key: value`` pairs are supported, which is all a SKILL.md
    frontmatter needs. Keeping this dependency-free means the linter runs
    anywhere Python does.
    """
    if not text.startswith("---"):
        return {}, 0
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, 0

    data: Dict[str, str] = {}
    key = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw.startswith((" ", "\t")) and key:
            data[key] = (data[key] + " " + raw.strip()).strip()
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        data[key] = value.strip()
    return data, end + 1


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans.

    Placeholder tokens legitimately appear inside code samples and inside prose
    that *quotes* them — this file's own spec reference lists "TBD" as a
    rejected source phrase. Scanning raw text flags those as defects, so the
    placeholder check runs against prose only.
    """
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def check_skill(directory: str, findings: Findings) -> None:
    name = os.path.basename(directory)
    skill_path = os.path.join(directory, "SKILL.md")

    if not os.path.isfile(skill_path):
        findings.error(name, "no SKILL.md")
        return

    with open(skill_path, "r", encoding="utf-8") as handle:
        text = handle.read()

    frontmatter, _ = parse_frontmatter(text)
    if not frontmatter:
        findings.error(name, "SKILL.md has no parseable YAML frontmatter")
        return

    # -- name ------------------------------------------------------------
    declared = frontmatter.get("name", "")
    if not declared:
        findings.error(name, "frontmatter is missing 'name'")
    elif declared != name:
        findings.error(
            name,
            "frontmatter name is %r but the directory is %r; the skill will "
            "not resolve when invoked by name" % (declared, name),
        )

    # -- description -----------------------------------------------------
    description = frontmatter.get("description", "")
    if not description:
        findings.error(name, "frontmatter is missing 'description'")
    else:
        if len(description) < MIN_DESCRIPTION_CHARS:
            findings.error(
                name,
                "description is %d chars; under %d it rarely carries enough "
                "trigger surface to fire reliably"
                % (len(description), MIN_DESCRIPTION_CHARS),
            )
        lowered = description.lower()
        if not any(hint in lowered for hint in TRIGGER_HINTS):
            findings.error(
                name,
                "description never says when to use the skill. Add explicit "
                "trigger phrasing ('Use this whenever the user asks to ...') "
                "— triggering is driven entirely by this field",
            )

    # -- length ----------------------------------------------------------
    line_count = len(text.splitlines())
    if line_count > MAX_SKILL_LINES:
        findings.error(
            name,
            "SKILL.md is %d lines, over the %d-line budget; move detail into "
            "references/ and point at it" % (line_count, MAX_SKILL_LINES),
        )
    elif line_count > MAX_SKILL_LINES * 0.85:
        findings.warn(
            name, "SKILL.md is %d lines, approaching the budget" % line_count
        )

    # -- placeholders ----------------------------------------------------
    prose = strip_code(text)
    for placeholder in PLACEHOLDERS:
        if placeholder in prose:
            findings.error(
                name, "contains an unresolved placeholder: %s" % placeholder
            )

    # -- referenced files ------------------------------------------------
    referenced = set()
    for match in LINK_RE.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        referenced.add(target.split("#")[0])
    for match in BACKTICK_PATH_RE.finditer(text):
        referenced.add(match.group(1))

    for target in sorted(referenced):
        if not target:
            continue
        candidates = [
            os.path.join(directory, target),
            os.path.join(REPO_ROOT, target),
        ]
        if not any(os.path.exists(path) for path in candidates):
            findings.error(name, "references a missing file: %s" % target)

    # -- gtmkit module references ----------------------------------------
    for match in GTMKIT_RE.finditer(text):
        module = match.group(1)
        module_path = os.path.join(REPO_ROOT, "gtmkit", "%s.py" % module)
        if not os.path.isfile(module_path):
            findings.error(
                name, "invokes gtmkit.%s, which does not exist" % module
            )

    # -- reference files get a light check of their own -------------------
    references_dir = os.path.join(directory, "references")
    if os.path.isdir(references_dir):
        for entry in sorted(os.listdir(references_dir)):
            if not entry.endswith(".md"):
                continue
            path = os.path.join(references_dir, entry)
            with open(path, "r", encoding="utf-8") as handle:
                body = handle.read()
            if len(body.splitlines()) > 300 and "## Contents" not in body:
                findings.warn(
                    name,
                    "references/%s is over 300 lines without a table of "
                    "contents" % entry,
                )
            reference_prose = strip_code(body)
            for placeholder in PLACEHOLDERS:
                if placeholder in reference_prose:
                    findings.error(
                        name,
                        "references/%s contains an unresolved placeholder: %s"
                        % (entry, placeholder),
                    )


def main() -> int:
    if not os.path.isdir(SKILLS_DIR):
        sys.stderr.write("no skills/ directory at %s\n" % SKILLS_DIR)
        return 1

    directories = sorted(
        os.path.join(SKILLS_DIR, entry)
        for entry in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, entry))
        and not entry.startswith(".")
    )

    if not directories:
        sys.stderr.write("no skills found in %s\n" % SKILLS_DIR)
        return 1

    findings = Findings()
    for directory in directories:
        check_skill(directory, findings)

    for warning in findings.warnings:
        sys.stdout.write("warning: %s\n" % warning)
    for error in findings.errors:
        sys.stdout.write("error:   %s\n" % error)

    sys.stdout.write(
        "\n%d skill(s) checked, %d error(s), %d warning(s)\n"
        % (len(directories), len(findings.errors), len(findings.warnings))
    )
    return 1 if findings.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
