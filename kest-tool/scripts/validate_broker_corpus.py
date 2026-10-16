"""Validate real, locally held broker PDFs or text extracts against reviewed expectations.

No documents or extracted customer data are uploaded or printed. Public text cases can
be downloaded explicitly with --public. Never put private PDFs/manifests into Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kest_tool.importers.pdf_importer import extract_pdf, parse_text


def check_case(case: dict, data: bytes) -> list[str]:
    failures = []
    if case.get('sha256') and hashlib.sha256(data).hexdigest() != case['sha256']:
        return ['sha256']
    ex = extract_pdf(data, allow_download=False) if data.startswith(b'%PDF-') else parse_text(data.decode('utf-8'))
    for key, expected in case['expected'].items():
        actual = getattr(ex, key) if key in ('tx_type', 'complete', 'broker') else ex.value(key)
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            matches = actual is not None and math.isclose(float(actual), expected, abs_tol=1e-6)
        else:
            matches = (actual.isoformat() if hasattr(actual, 'isoformat') else actual) == expected
        if not matches:
            failures.append(key)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--public', action='store_true', help='Explicitly download pinned public text fixtures')
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text(encoding='utf-8'))
    failed = 0
    for case in cases:
        try:
            if args.public:
                url = case['url']
                if not url.startswith('https://raw.githubusercontent.com/portfolio-performance/portfolio/f84ff1a432ec9ba61c17aa2ae4191c8b068643a7/'):
                    raise ValueError('Only the pinned public fixture source is allowed')
                with urlopen(url, timeout=30) as response:
                    data = response.read(10 * 1024 * 1024 + 1)
                if len(data) > 10 * 1024 * 1024:
                    raise ValueError('Fixture too large')
            else:
                data = (args.manifest.parent / case['file']).read_bytes()
            failures = check_case(case, data)
            failed += bool(failures)
            # Case index avoids leaking private filenames, names or account references.
            print(json.dumps({'case': cases.index(case) + 1, 'ok': not failures, 'failed_fields': failures}))
        except Exception as exc:
            failed += 1
            print(json.dumps({'case': cases.index(case) + 1, 'ok': False, 'error': type(exc).__name__}))
    print(json.dumps({'cases': len(cases), 'failed': failed}))
    return 1 if failed or not cases else 0


if __name__ == '__main__':
    raise SystemExit(main())
