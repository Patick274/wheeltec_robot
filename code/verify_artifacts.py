"""验证教学资料链接、原件完整性、PDF 文本与页面边界。"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote
import re, hashlib, json, sys
import pdfplumber
from pypdf import PdfReader
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parent
bad=[]; checked=0
def check(file,link):
    global checked
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',link) or link.startswith('#'):return
    checked+=1
    link=unquote(link.split('#')[0].split('?')[0])
    if link and not (file.parent/link).exists():bad.append((str(file.relative_to(root)),link))
for f in root.rglob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)',f.read_text(encoding='utf-8')):check(f,link)
class Links(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for k,v in attrs:
            if k in ['href','src'] and v:check(self.file,v)
for f in list((root/'lessons').glob('*.html'))+list((root/'reference').glob('*.html')):
    parser=Links();parser.file=f;parser.feed(f.read_text(encoding='utf-8'))
assert not bad,bad
for name in ['小白github.txt','要求.txt']:
    assert (root/'00_原始材料'/name).read_bytes()==(Path('C:/Users/thunderobot/OneDrive/Desktop')/name).read_bytes()
pdf=root/'output/pdf/GitHub_PHM_双机协作与仓库图解.pdf'
reader=PdfReader(pdf);assert len(reader.pages)==19
assert len(reader.outline)==19
assert len([a for p in reader.pages for a in p.get('/Annots',[])])>=20
pages=[]
with pdfplumber.open(pdf) as doc:
    for i,page in enumerate(doc.pages,1):
        text=page.extract_text() or ''
        assert len(text)>250,(i,len(text))
        assert '\ufffd' not in text,(i,'replacement character')
        chars=[ch for ch in page.chars if ch.get('text','').strip()]
        assert all(ch['x0']>=0 and ch['x1']<=page.width+1 for ch in chars),(i,'horizontal overflow')
        assert all(ch['top']>=0 and ch['bottom']<=page.height for ch in chars),(i,'vertical overflow')
        pages.append({'page':i,'characters':len(text)})
fontfiles=[]
for page in reader.pages:
    for name,ref in page['/Resources']['/Font'].items():
        font=ref.get_object();descriptor=font.get('/FontDescriptor')
        if descriptor:
            d=descriptor.get_object()
            if '/FontFile2' in d:fontfiles.append(str(font.get('/BaseFont')))
assert any('YaHei' in f for f in fontfiles),fontfiles
(root/'tmp/pdfs/artifact_checks.json').write_text(json.dumps({'local_links_checked':checked,'pages':pages,'embedded_fonts':sorted(set(fontfiles))},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':19,'local_links_checked':checked,'source_copies_identical':True,'embedded_fonts':sorted(set(fontfiles))},ensure_ascii=False))
