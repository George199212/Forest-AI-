#!/usr/bin/env python3
"""Redaction for committed test fixtures and docs (owner 2026-11-18). The terms are NOT stored in git:
they are read at run time from a DB copy (client organisations = sectors.contractor; property names =
sectors.object_name / boundary_plans.object_name) and from an untracked terms file (one `kind: term` per line,
kinds: client | property | surname). Rules:

  client organisation  -> "<client>"
  property/homestead   -> "<property name>"
  personal surname     -> "<redacted: personal surname>" (whole word containing the fragment; Stage 0 format)
  cadastral number     -> first 2 digits + "…(" + length + ")", e.g. 60…(11) (11- or 14-digit standalone numbers)
  JSON key "contractor" -> "<client>" whenever it has a value

  python3 -I scripts/fixture_redaction.py --forest-db COPY --terms-file /root/sectors_sandbox/redact_terms.txt FILE...
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

CADASTRE = re.compile(r"(?<![\w.])(\d{14}|\d{11})(?![\w.])")


def mask_cadastre(s):
    return CADASTRE.sub(lambda m: m.group(1)[:2] + "…(" + str(len(m.group(1))) + ")", s)


def load_terms(forest_db=None, terms_file=None):
    terms = {"client": set(), "property": set(), "surname": set()}
    if forest_db:
        c = sqlite3.connect(f"file:{forest_db}?mode=ro", uri=True)
        try:
            for sql, kind in (("SELECT DISTINCT contractor FROM sectors", "client"),
                              ("SELECT DISTINCT object_name FROM sectors", "property"),
                              ("SELECT DISTINCT object_name FROM boundary_plans", "property")):
                for (v,) in c.execute(sql):
                    if v and len(str(v).strip()) >= 4:
                        terms[kind].add(str(v).strip())
        finally:
            c.close()
    if terms_file and Path(terms_file).exists():
        for line in Path(terms_file).read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                kind, term = (x.strip() for x in line.split(":", 1))
                if kind in terms and term:
                    terms[kind].add(term)
    return terms


def compile_rules(terms):
    rules = []
    # longest first so "A B" wins over "A"; short tokens (e.g. 2-letter labels) only as whole words
    for kind, repl in (("client", "<client>"), ("property", "<property name>")):
        for t in sorted(terms[kind], key=len, reverse=True):
            pat = re.escape(t)
            pat = r"(?<!\w)" + pat + r"(?!\w)"
            # short labels (<= 3 characters) are case-sensitive, so they never match ordinary lowercase words or commands
            rules.append((re.compile(pat, re.IGNORECASE if len(t) > 3 else 0), repl))
    for t in terms["surname"]:
        rules.append((re.compile(r"\S*" + re.escape(t) + r"\S*", re.IGNORECASE), "<redacted: personal surname>"))
    return rules


def redact_text(s, rules):
    for rx, repl in rules:
        s = rx.sub(repl, s)
    return mask_cadastre(s)


def redact_json(v, rules, key=None):
    if isinstance(v, dict):
        return {k: redact_json(x, rules, k) for k, x in v.items()}
    if isinstance(v, list):
        return [redact_json(x, rules, key) for x in v]
    if isinstance(v, str):
        if key == "contractor" and v.strip():
            return "<client>"
        return redact_text(v, rules)
    if isinstance(v, int) and not isinstance(v, bool) and CADASTRE.fullmatch(str(v)):
        return mask_cadastre(str(v))
    return v


def redact_file(path, rules):
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        out = json.dumps(redact_json(json.loads(raw), rules), ensure_ascii=False, indent=1) + "\n"
    else:
        out = redact_text(raw, rules)
    if out != raw:
        p.write_text(out, encoding="utf-8")
    return out != raw


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--forest-db")
    ap.add_argument("--terms-file")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    if a.forest_db and a.forest_db.startswith("/root/forest_ai/data/"):
        sys.exit("refusing to read a live DB path; use a .backup copy")
    rules = compile_rules(load_terms(a.forest_db, a.terms_file))
    for f in a.files:
        print(("redacted  " if redact_file(f, rules) else "unchanged ") + f)


if __name__ == "__main__":
    main()
