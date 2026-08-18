"""Compile locale/<lang>/LC_MESSAGES/django.po -> django.mo without the GNU
gettext toolchain (`msgfmt`/`xgettext`), which isn't installed on this
machine — confirmed absent anywhere on disk. `manage.py compilemessages`
shells out to `msgfmt` and will fail here; this is a drop-in replacement
for that one step, using nothing beyond the standard library.

Only handles single-line, non-fuzzy, non-plural msgid/msgstr pairs — the
straightforward case this project's .po files use. If translations ever
need plurals or multi-line strings, install a real gettext toolchain (or
`pip install polib`) instead of extending this.

Usage: python scripts/compile_translations.py [lang ...]
       (defaults to every language dir found under locale/)
"""
import re
import struct
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALE_DIR = BASE_DIR / 'locale'

MSG_RE = re.compile(r'^msgid "((?:[^"\\]|\\.)*)"\s*\nmsgstr "((?:[^"\\]|\\.)*)"', re.MULTILINE)


def unescape(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({'n': '\n', '"': '"', '\\': '\\'}.get(nxt, nxt))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def parse_po(path):
    text = path.read_text(encoding='utf-8')
    return {unescape(m.group(1)): unescape(m.group(2)) for m in MSG_RE.finditer(text)}


def compile_mo(entries, out_path):
    entries = dict(entries)
    # Force the header entry so gettext.GNUTranslations sees an explicit
    # UTF-8 charset — without it, CPython's parser defaults to ascii and
    # raises UnicodeDecodeError on the first non-ASCII translated string.
    entries[''] = 'Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n'

    keys = sorted(entries.keys())
    ids, strs, spans = b'', b'', []
    for k in keys:
        k_b, v_b = k.encode('utf-8'), entries[k].encode('utf-8')
        spans.append((len(ids), len(k_b), len(strs), len(v_b)))
        ids += k_b + b'\x00'
        strs += v_b + b'\x00'

    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in spans:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]

    header = struct.pack('Iiiiiii', 0x950412de, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    body = struct.pack('%di' % len(koffsets), *koffsets) + struct.pack('%di' % len(voffsets), *voffsets)
    out_path.write_bytes(header + body + ids + strs)


def main(langs):
    if not langs:
        langs = [d.name for d in LOCALE_DIR.iterdir() if d.is_dir()]
    for lang in langs:
        po_path = LOCALE_DIR / lang / 'LC_MESSAGES' / 'django.po'
        if not po_path.exists():
            print(f'skip {lang}: no {po_path}')
            continue
        entries = parse_po(po_path)
        mo_path = po_path.with_suffix('.mo')
        compile_mo(entries, mo_path)
        print(f'{lang}: compiled {len(entries)} entries -> {mo_path}')


if __name__ == '__main__':
    main(sys.argv[1:])
