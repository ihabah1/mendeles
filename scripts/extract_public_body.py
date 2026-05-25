"""Extract HTML body chunks from new_stite.html for Django templates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = (ROOT / 'new_stite.html').read_text(encoding='utf-8').splitlines()

def slice_lines(start, end):
    return '\n'.join(lines[start - 1 : end])

out = ROOT / 'templates' / 'web' / '_extracted'
out.mkdir(parents=True, exist_ok=True)
(out / 'nav.txt').write_text(slice_lines(151, 171), encoding='utf-8')
(out / 'lotto.txt').write_text(slice_lines(173, 218), encoding='utf-8')
(out / 'toto.txt').write_text(slice_lines(220, 256), encoding='utf-8')
(out / 'about.txt').write_text(slice_lines(258, 270), encoding='utf-8')
(out / 'legal.txt').write_text(slice_lines(272, 284), encoding='utf-8')
(out / 'a11y.txt').write_text(slice_lines(286, 295), encoding='utf-8')
(out / 'footer.txt').write_text(slice_lines(297, 329), encoding='utf-8')
(out / 'modals_a11y.txt').write_text(slice_lines(310, 337), encoding='utf-8')
print('ok')
