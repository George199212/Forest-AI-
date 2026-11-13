"""Instance presentation isolation and runtime English display checks (no live DB or APIs)."""
import ast
import hashlib
import re
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]


def page(monkeypatch, language, review=False, name=''):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv('UI_LANGUAGE', language)
    monkeypatch.setenv('INSTANCE_DISPLAY_NAME', name)
    node = next(n for n in ast.parse((ROOT/'api.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'serve_index')
    node.decorator_list = []
    namespace = {'Path': Path, 'os': os, 'json': json, 'HTMLResponse': HTMLResponse, 're': re, 'hashlib': hashlib,
                 'frontend_deployment': lambda: {'version': 'geo-test'},
                 'review_mode': SimpleNamespace(ENABLED=review)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'serve_index', 'exec'), namespace)
    return namespace['serve_index']().body.decode()


@pytest.mark.parametrize('language', ['', 'lv', 'ru', 'en'])
def test_english_overlay_only_in_english(monkeypatch, language):
    html = page(monkeypatch, language)
    assert ('src="/assets/i18n-en.js' in html) == (language == 'en')
    if language == '':
        # Production serve_index fingerprints assets; the invariant is: no language or review injection.
        assert 'src="/assets/i18n-' not in html
        assert 'review-ui.js' not in html and 'review-satellite.js' not in html
    assert 'window.ForestInstance=' not in html


def test_review_banner_configuration_and_script_safety(monkeypatch):
    html = page(monkeypatch, 'en', review=True, name='Review </script><script>bad()</script>')
    raw = html.split('window.ForestInstance=', 1)[1].split('</script>', 1)[0]
    config = json.loads(raw)
    assert config['readOnly'] is True
    assert config['displayName'].endswith('bad()</script>')
    assert '<' not in raw
    assert 'src="/assets/review-ui.js' in html


def test_pdf_is_review_only_restriction(monkeypatch):
    from services import review_mode
    assert review_mode.classify('GET', '/api/report/pdf/FIELD-TEST-01') == (403, 'not_available_in_review_mode')
    # Normal mode never installs this middleware: covered by test_review_mode.


def test_english_runtime_phrases_and_review_controls():
    subprocess.run(['node', str(ROOT/'tests/review_ui_checks.cjs')], check=True, capture_output=True, text=True)
