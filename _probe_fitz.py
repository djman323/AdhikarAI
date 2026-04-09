import fitz
import glob

files = sorted(glob.glob('*.pdf'))
print(files, flush=True)
total = 0
for f in files:
    doc = fitz.open(f)
    print(f, doc.page_count, flush=True)
    for page in doc:
        _ = page.get_text('text')
        total += 1
    doc.close()
    print('done', f, flush=True)
print('pages', total, flush=True)
