"""Write the statutory verification worksheet (GO_LIVE.md D6) to a file.

The builder lives in ``app/services/statutory_worksheet.py`` so the app can
offer the same workbook for download; this is its command-line door:

    python tools/statutory_worksheet.py [output.xlsx]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.statutory_worksheet import build  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "statutory_verification_worksheet.xlsx")
    totals = build(out)
    print(f"wrote {out}")
    for tab, (count, _col, top, bottom) in totals.items():
        print(f"  {tab}: {count} values to verify (rows {top}-{bottom})")
    print(f"  TOTAL: {sum(c for c, *_ in totals.values())}")
