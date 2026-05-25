"""Extract public site CSS/JS from new_stite.html."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / 'new_stite.html').read_text(encoding='utf-8')

i0 = src.index('<style>') + 7
i1 = src.index('</style>')
(ROOT / 'static/css/public_site.css').write_text(src[i0:i1].strip() + '\n', encoding='utf-8')

i2 = src.rindex('<script>') + 8
i3 = src.rindex('</script>')
js = src[i2:i3]
js = js.replace("lbl.textContent = 'מצב הדגמה';", "if (lbl) { lbl.style.display = 'none'; } if (dot) { dot.style.display = 'none'; }")
js = js.replace('(מצב הדגמה)', '')
(ROOT / 'static/js/public_site.js').write_text(js, encoding='utf-8')
print('done', (ROOT / 'static/css/public_site.css').stat().st_size, (ROOT / 'static/js/public_site.js').stat().st_size)
