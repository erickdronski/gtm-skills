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
* Every ``gtmkit.<module>`` mention names a module that exists, and every
  ``python3 -m gtmkit.<module>`` command — in SKILL.md and in references/ —
  invokes a runnable module with flags its CLI actually accepts. A documented
  flag that argparse rejects costs the agent a failed run and a guess.
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
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
GTMKIT_DIR = os.path.join(REPO_ROOT, "gtmkit")

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

# A command and everything after it on the same logical line. Shell line
# continuations are joined before matching, so a multi-line invocation in a
# fenced block is checked as the one command it is.
COMMAND_RE = re.compile(r"python3?\s+-m\s+gtmkit\.([a-z_]+)([^\n]*)")
CONTINUATION_RE = re.compile(r"\\\n\s*")
FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
ADD_ARGUMENT_RE = re.compile(r"add_argument\(\s*((?:\"[^\"]*\"\s*,\s*)*\"[^\"]*\")")
QUOTED_RE = re.compile(r"\"([^\"]*)\"")


def module_flags(module: str) -> Optional[Set[str]]:
    """Return the option strings a gtmkit module's CLI declares.

    Read from source rather than by importing, so the linter cannot execute
    anything and does not depend on the engine importing cleanly. Every CLI in
    the package declares options as ``add_argument("--name", ...)``, which this
    matches; ``--help`` comes free with argparse.
    """
    path = os.path.join(GTMKIT_DIR, "%s.py" % module)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    flags = {"--help", "-h"}
    for match in ADD_ARGUMENT_RE.finditer(source):
        for name in QUOTED_RE.findall(match.group(1)):
            if name.startswith("-"):
                flags.add(name)
    return flags


def module_is_runnable(module: str) -> bool:
    path = os.path.join(GTMKIT_DIR, "%s.py" % module)
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    return "def main(" in source and '__name__ == "__main__"' in source


def command_problems(text: str) -> List[str]:
    """Check every ``python3 -m gtmkit.<module>`` command in a document.

    Only flags on the command's own logical line are checked. A flag merely
    mentioned in prose has no command to belong to, and guessing one would
    produce false alarms that teach people to ignore the linter.
    """
    problems: List[str] = []
    joined = CONTINUATION_RE.sub(" ", text)
    for match in COMMAND_RE.finditer(joined):
        module = match.group(1)
        flags = module_flags(module)
        if flags is None:
            # Reported once by the module-existence check; a second error for
            # the same typo is noise.
            continue
        if not module_is_runnable(module):
            problems.append(
                "runs `python3 -m gtmkit.%s`, but that module has no main() "
                "entry point" % module
            )
            continue
        # Strip a trailing shell comment so prose like "# --format json is
        # also available" is not read as part of the command.
        arguments = re.split(r"\s#", match.group(2), maxsplit=1)[0]
        for flag in FLAG_RE.findall(arguments):
            if flag not in flags:
                accepted = ", ".join(sorted(f for f in flags if f.startswith("--")))
                problems.append(
                    "shows `gtmkit.%s %s`, which the CLI does not accept. "
                    "It takes: %s" % (module, flag, accepted)
                )
    return problems


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
        findings.warn(name, "SKILL.md is %d lines, approaching the budget" % line_count)

    # -- placeholders ----------------------------------------------------
    prose = strip_code(text)
    for placeholder in PLACEHOLDERS:
        if placeholder in prose:
            findings.error(name, "contains an unresolved placeholder: %s" % placeholder)

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
        module_path = os.path.join(GTMKIT_DIR, "%s.py" % module)
        if not os.path.isfile(module_path):
            findings.error(name, "invokes gtmkit.%s, which does not exist" % module)
    for problem in command_problems(text):
        findings.error(name, "SKILL.md %s" % problem)

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
            for match in GTMKIT_RE.finditer(body):
                module = match.group(1)
                if not os.path.isfile(os.path.join(GTMKIT_DIR, "%s.py" % module)):
                    findings.error(
                        name,
                        "references/%s invokes gtmkit.%s, which does not exist"
                        % (entry, module),
                    )
            for problem in command_problems(body):
                findings.error(name, "references/%s %s" % (entry, problem))


def main() -> int:
    if not os.path.isdir(SKILLS_DIR):
        sys.stderr.write("no skills/ directory at %s\n" % SKILLS_DIR)
        return 1

    directories = sorted(
        os.path.join(SKILLS_DIR, entry)
        for entry in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, entry)) and not entry.startswith(".")
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
