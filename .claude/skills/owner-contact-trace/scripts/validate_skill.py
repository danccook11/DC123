#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_skill.py — house frontmatter/structure linter for owner-contact-trace.

Reconstructed from the rule list in the master spec. The original
`florida-development-feasibility/scripts/validate_skill.py` was not available in the
build environment, so this is written to the stated rules rather than ported.

Two deliberate deviations from the stated rule list, both visible in the output rather
than silent:

  * The "no < or > anywhere in frontmatter" rule is NARROWED. The mandated frontmatter
    uses YAML folded block scalars (`description: >`, `compatibility: >`), so a literal
    any-angle-bracket rule would reject the skill's own required frontmatter. This linter
    strips a block-scalar indicator when it is the ENTIRE value token after `key:`
    (`>`, `>-`, `|`, `|-`), then asserts no `<` or `>` remains. A NOTE is printed.
  * The `check_evals` requirement for `agent_routing_evals.json` is DROPPED — this skill
    has no subagents.

Python 3.9 compatible, standard library only (jsonschema is optional and guarded).
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import pathlib
import re
import sys

DESCRIPTION_CAP = 1024
SKILL_LINE_CAP = 500
ALLOWED_FM_KEYS = {"name", "description", "license", "allowed-tools", "metadata",
                   "compatibility"}
BLOCK_SCALAR_RE = re.compile(r"^(\s*[A-Za-z_-]+:)\s*(?:>-?|\|-?)\s*$", re.M)
# Built from parts so this linter's own pattern is not itself a hit. example: /Users/foo
_ABS_PREFIXES = ("/" + "Users/", "/" + "home/", "/" + "private/", r"[A-Za-z]:\\\\")
ABS_PATH_RE = re.compile(r"""["'](""" + "|".join(_ABS_PREFIXES) + r""")""")
ICLOUD_RE = re.compile("Mobile" + " Documents")

# Numbers that are NOT personal PII and must stay literal in the tree. Each needs a reason;
# anything not listed here and not in the 555-01xx reserved range fails the scan.
PUBLIC_NUMBER_ALLOWLIST = {
    "+1-855-723-2747": "toll-free scraper-artifact constant — must stay literal to be "
                       "blocklisted (references/traps.md, doctrine 9)",
    "800-635-4772": "Melissa Data technical support line, published (references/traps.md)",
    "919-814-5400": "NC Secretary of State bulk-subscription line, published "
                    "(references/state_routes.md)",
    "(432) 336-3503": "Pecos County Clerk, published (references/county_access.md)",
    "432) 336-3503": "Pecos County Clerk, published — partial match form",
}
RUNDOWN_HEADERS = [
    "PROPERTY",
    "OWNER OF RECORD",
    "ENTITY CHAIN",
    "REGISTERED AGENT (AGENT — NOT THE OWNER)",
    "RESOLVED HUMAN + ROLE EVIDENCE",
    "BEST NUMBER",
    "ALTERNATES",
    "COMPLIANCE",
    "NAMED GAPS",
]
# Reserved-fictional range. 555-0100..555-0199 is never assigned to a real subscriber.
FICTIONAL_RE = re.compile(r"555[\s.\-]?01\d{2}")


class Report(object):
    def __init__(self, strict=False):
        self.checks = 0
        self.failures = []
        self.warnings = []
        self.notes = []
        self.strict = strict

    def check(self, name):
        self.checks += 1
        return name

    def fail(self, name, detail):
        self.failures.append((name, detail))
        print("FAIL {}: {}".format(name, detail))

    def warn(self, name, detail):
        if self.strict:
            self.fail(name, detail + "  [--strict]")
        else:
            self.warnings.append((name, detail))
            print("WARN {}: {}".format(name, detail))

    def note(self, detail):
        self.notes.append(detail)
        print("NOTE {}".format(detail))

    def ok(self, name, detail=""):
        print("ok   {}{}".format(name, ("  — " + detail) if detail else ""))


def read_frontmatter(skill_md):
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    return parts[1], parts[2]


def parse_fm_keys(fm):
    return re.findall(r"^([A-Za-z_-]+):", fm, re.M)


def extract_description(fm):
    m = re.search(r"^description:\s*>-?\s*\n((?:[ \t]+\S.*\n|[ \t]*\n)+)", fm, re.M)
    if m:
        return " ".join(l.strip() for l in m.group(1).splitlines() if l.strip())
    m = re.search(r"^description:\s*(.+)$", fm, re.M)
    return m.group(1).strip() if m else None


def check_frontmatter(rep, root):
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        rep.fail(rep.check("skill-md-exists"), "SKILL.md not found at {}".format(skill_md))
        return
    rep.ok(rep.check("skill-md-exists"))

    fm, body = read_frontmatter(skill_md)
    if fm is None:
        rep.fail(rep.check("frontmatter-parses"), "no --- delimited frontmatter block")
        return
    rep.ok(rep.check("frontmatter-parses"))

    desc = extract_description(fm)
    name = rep.check("description-length")
    if desc is None:
        rep.fail(name, "no description key found")
    elif len(desc) > DESCRIPTION_CAP:
        rep.fail(name, "{} chars > {} cap".format(len(desc), DESCRIPTION_CAP))
    else:
        rep.ok(name, "{} chars (cap {})".format(len(desc), DESCRIPTION_CAP))

    rep.note("angle-bracket check narrowed: YAML block-scalar indicators (>, >-, |, |-) "
             "occupying an entire value slot are stripped before the check, because the "
             "mandated frontmatter uses `description: >` and `compatibility: >`.")
    stripped = BLOCK_SCALAR_RE.sub(r"\1", fm)
    name = rep.check("frontmatter-no-angle-brackets")
    bad = re.findall(r"[<>]", stripped)
    if bad:
        rep.fail(name, "{} angle bracket(s) remain after stripping block-scalar "
                       "indicators".format(len(bad)))
    else:
        rep.ok(name)

    name = rep.check("frontmatter-keys-exact")
    keys = set(parse_fm_keys(fm))
    extra, missing = keys - ALLOWED_FM_KEYS, ALLOWED_FM_KEYS - keys
    if extra or missing:
        rep.fail(name, "extra={} missing={}".format(sorted(extra), sorted(missing)))
    else:
        rep.ok(name, " ".join(sorted(keys)))

    name = rep.check("skill-md-line-cap")
    n = len(skill_md.read_text(encoding="utf-8").splitlines())
    if n > SKILL_LINE_CAP:
        rep.fail(name, "{} lines > {} cap".format(n, SKILL_LINE_CAP))
    else:
        rep.ok(name, "{} lines (cap {})".format(n, SKILL_LINE_CAP))

    name = rep.check("exactly-one-skill-md")
    found = [p for p in root.rglob("SKILL.md")]
    if len(found) != 1:
        rep.fail(name, "{} SKILL.md files: {}".format(
            len(found), [str(p.relative_to(root)) for p in found]))
    else:
        rep.ok(name)

    return body


def check_scripts(rep, root):
    scripts = sorted((root / "scripts").glob("*.py"))
    name = rep.check("scripts-no-absolute-paths")
    hits = []
    for p in scripts:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "example:" in line:
                continue
            if ABS_PATH_RE.search(line) or ICLOUD_RE.search(line):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                hits.append("{}:{}".format(p.name, i))
    if hits:
        rep.fail(name, "machine-specific absolute path(s) at " + ", ".join(hits))
    else:
        rep.ok(name, "{} script(s)".format(len(scripts)))

    name = rep.check("scripts-no-bare-python-subprocess")
    hits = []
    for p in scripts:
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"subprocess\.\w+\(\s*\[?\s*[\"'](python3?)[\"']", src):
            hits.append("{}:{}".format(p.name, src[:m.start()].count("\n") + 1))
    if hits:
        rep.fail(name, "subprocess spawning a bare interpreter string (use sys.executable) "
                       "at " + ", ".join(hits))
    else:
        rep.ok(name)

    name = rep.check("scripts-compile-and-expose-help")
    bad = []
    for p in scripts:
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=p.name)
        except SyntaxError as e:
            bad.append("{} does not parse: {}".format(p.name, e))
            continue
        has_argparse = any(
            isinstance(n, (ast.Import, ast.ImportFrom))
            and "argparse" in ast.dump(n) for n in ast.walk(tree))
        has_main = any(isinstance(n, ast.FunctionDef) and n.name == "main"
                       for n in ast.walk(tree))
        has_guard = "__main__" in src
        if not (has_argparse and has_main and has_guard):
            bad.append("{} (argparse={} main={} guard={})".format(
                p.name, has_argparse, has_main, has_guard))
    if bad:
        rep.fail(name, "; ".join(bad))
    else:
        rep.ok(name, "{} script(s)".format(len(scripts)))


def check_references(rep, root, body):
    name = rep.check("references-bidirectional")
    on_disk = set()
    refdir = root / "references"
    if refdir.is_dir():
        on_disk = {p.name for p in refdir.iterdir() if p.is_file()}
    named = set(re.findall(r"`references/([A-Za-z0-9_.-]+)`", body or ""))
    missing_on_disk = named - on_disk
    unnamed = on_disk - named
    if missing_on_disk or unnamed:
        rep.fail(name, "named in SKILL.md but absent: {} | on disk but not named: {}".format(
            sorted(missing_on_disk), sorted(unnamed)))
    else:
        rep.ok(name, "{} reference file(s)".format(len(on_disk)))


def check_schemas(rep, root):
    name = rep.check("schemas-valid")
    files = sorted(glob.glob(str(root / "schemas" / "*.json")))
    if not files:
        rep.warn(name, "no schemas found")
        return
    try:
        import jsonschema
        checker = jsonschema.Draft202012Validator.check_schema
    except ImportError:
        checker = None
        rep.note("jsonschema not installed — schema files are parse-checked only. "
                 "Install with: {} -m pip install --user jsonschema".format(
                     os.path.basename(sys.executable)))
    bad = []
    for f in files:
        try:
            doc = json.load(open(f, encoding="utf-8"))
            if checker:
                checker(doc)
        except Exception as e:
            bad.append("{}: {}".format(os.path.basename(f), e))
    if bad:
        rep.fail(name, "; ".join(bad))
    else:
        rep.ok(name, "{} schema(s)".format(len(files)))


def check_counties(rep, root):
    name = rep.check("county-configs-valid")
    files = sorted(glob.glob(str(root / "config" / "counties" / "*.json")))
    if not files:
        rep.warn(name, "no county configs found")
        return
    required = ("county_key", "county", "state", "layer_url", "parcel_id_field",
                "owner_fields")
    bad = []
    for f in files:
        base = os.path.basename(f)
        if base.startswith("_"):
            continue                      # non-county helpers, e.g. _statewide_*.json
        try:
            doc = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            bad.append("{}: {}".format(base, e))
            continue
        miss = [k for k in required if k not in doc]
        if miss:
            bad.append("{}: missing {}".format(base, miss))
    if bad:
        rep.fail(name, "; ".join(bad))
    else:
        rep.ok(name, "{} config(s)".format(len(files)))


def check_template(rep, root):
    name = rep.check("rundown-template-headers")
    p = root / "templates" / "owner_rundown.md"
    if not p.is_file():
        rep.fail(name, "templates/owner_rundown.md not found")
        return
    text = p.read_text(encoding="utf-8")
    missing = [h for h in RUNDOWN_HEADERS if h not in text]
    if missing:
        rep.fail(name, "missing literal header(s): {}".format(missing))
    else:
        rep.ok(name, "{} header(s)".format(len(RUNDOWN_HEADERS)))


def check_pii(rep, root):
    """No real-looking phone number outside schemas/templates/references.

    The skill's product is phone numbers, so this is scoped, not global; and the
    reserved-fictional 555-01xx range passes everywhere.
    """
    name = rep.check("no-real-phone-numbers-in-tree")
    try:
        sys.path.insert(0, str(root / "scripts"))
        from octlib import PHONE_RE
    except Exception:
        PHONE_RE = re.compile(
            r"(?<![0-9])(?:\+?1[\s.\-]?)?(?:\(\s*[2-9]\d{2}\s*\)|[2-9]\d{2})"
            r"[\s.\-]?[2-9]\d{2}[\s.\-]?\d{4}(?![0-9])")
        rep.note("octlib not importable — using a local copy of PHONE_RE for the PII scan")

    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in PHONE_RE.finditer(line):
                hit = m.group(0)
                if FICTIONAL_RE.search(hit):
                    continue
                if any(a in line for a in PUBLIC_NUMBER_ALLOWLIST):
                    continue
                hits.append("{}:{}: {}".format(p.relative_to(root), i, hit))
    if hits:
        rep.fail(name, "non-fictional phone number(s): " + "; ".join(hits[:20]))
    else:
        rep.ok(name, "only 555-01xx reserved-fictional numbers and {} allowlisted public "
                     "business/artifact numbers found".format(len(PUBLIC_NUMBER_ALLOWLIST)))


def main(argv=None):
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        prog="validate_skill.py",
        description="House linter for the owner-contact-trace skill. Exits nonzero on any "
                    "FAIL. The agent_routing_evals.json check is intentionally dropped — "
                    "this skill has no subagents.")
    ap.add_argument("--skill-dir", default=str(here.parent),
                    help="skill root (default: the parent of this script's directory)")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as failures")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.skill_dir).resolve()
    rep = Report(strict=args.strict)
    print("validate_skill: linting {}".format(root))
    print("NOTE check_evals / agent_routing_evals.json is DROPPED — no subagents in this "
          "skill.")

    body = check_frontmatter(rep, root)
    check_scripts(rep, root)
    check_references(rep, root, body or "")
    check_schemas(rep, root)
    check_counties(rep, root)
    check_template(rep, root)
    check_pii(rep, root)

    print("validate_skill: {} checks, {} failed, {} warnings".format(
        rep.checks, len(rep.failures), len(rep.warnings)))
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
