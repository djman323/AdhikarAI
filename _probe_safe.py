from pypdf import PdfReader
import glob

ok_pages = 0
bad_pages = 0
for f in sorted(glob.glob('*.pdf')):
    print('start', f, flush=True)
    reader = PdfReader(f)
    for page in reader.pages:
        try:
            text = (page.extract_text() or '').strip()
        except Exception:
            bad_pages += 1
            continue
        if text:
            if len(text) > 12000:
                text = text[:12000]
            ok_pages += 1
    print('done', f, flush=True)
print('ok_pages', ok_pages, 'bad_pages', bad_pages, flush=True)
