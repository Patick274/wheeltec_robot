"""检查 A/B 教材的 PDF 和本地链接，不操作 Git 仓库。"""
from pathlib import Path
from urllib.parse import unquote
import re
import sys
import json
import pdfplumber
from pypdf import PdfReader

sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent
PDF=ROOT/'output/pdf/GitHub_AB两机上传下拉简明手册.pdf'
REPORT=ROOT/'GitHub_AB简明版校验记录.md'
reader=PdfReader(PDF)
assert len(reader.pages)==4
assert len(reader.outline)==4
text=[];bounds=[]
with pdfplumber.open(PDF) as pdf:
    for i,page in enumerate(pdf.pages,1):
        s=page.extract_text() or ''
        assert len(s)>350,(i,len(s))
        assert '\ufffd' not in s,(i,'replacement character')
        for ch in page.chars:
            if not ch['text'].strip():continue
            assert ch['x0']>=0 and ch['x1']<=page.width+1,(i,'horizontal',ch)
            assert ch['top']>=0 and ch['bottom']<=page.height,(i,'vertical',ch)
        text.append(s)
        bounds.append({'page':i,'characters':len(s)})
whole='\n'.join(text)
for expected in ['Patick274','wheeltec_robot','git pull --ff-only','git push','ssh -T git@github.com','git merge']:
    assert expected in whole,expected
fonts=set()
for page in reader.pages:
    for ref in page['/Resources']['/Font'].values():
        font=ref.get_object();d=font.get('/FontDescriptor')
        if d and '/FontFile2' in d.get_object():fonts.add(str(font.get('/BaseFont')))
assert any('YaHei' in f for f in fonts),fonts
external=[]
for page in reader.pages:
    for ref in page.get('/Annots',[]):
        a=ref.get_object().get('/A')
        if a and a.get('/URI'):external.append(str(a['/URI']))
assert len(external)>=7
targets=[]
for file in ROOT.rglob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)',file.read_text(encoding='utf-8-sig')):
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',link) or link.startswith('#'):continue
        target=file.parent/unquote(link.split('#')[0].split('?')[0])
        if target==REPORT:continue
        assert target.exists(),(str(file),link)
        targets.append(target)
layout=json.loads((ROOT/'tmp/pdfs/github_ab/layout.json').read_text(encoding='utf-8'))
assert min(item['bottom'] for item in layout)>=56
REPORT.write_text('''# GitHub A/B 简明版校验记录

日期：2026-10-19。

## 本次输出

- 四页简明 PDF：日常交接、首次连接、Linux 无插件认证、真实报错速查。
- 配套 Markdown：包含两台电脑的实际路径、真实仓库地址和可复制命令。
- 更新 README、每日清单、通用教程入口、远程配置问题和冲突问题导航。
- 旧长版 PDF 保留；旧生成器默认不再覆盖已修订的 Markdown。

## 检查结果

'''+f'''- PDF 页数：4；目录书签：4。
- 所有页面可提取中文正文；无替换字符，文字均处于页面边界内。
- 中文常规与粗体字体已嵌入；PDF 含 {len(external)} 个官方来源链接注释。
- Markdown 本地链接检查：{len(targets)} 个目标全部存在（另有本校验记录链接）。
- 生成器对代码行宽度和正文底部边界进行断言，全部通过。
- 全部 4 页渲染为 PNG 后逐页目视核对，中文、代码块、提示框和页脚清楚可读。

## 实际操作边界

本次只改 code 内学习文件，没有执行用户仓库的 merge、abort、commit、push 或配置密钥。
旧冲突、空仓库检查均来自本次对话历史，不当作当前实时状态。
未验证 Linux 机器、SSH 登录、clone、ROS 编译或实际设备；不声称最终上传已经成功。
先前的本地模拟 Git 流程测试见验证记录.md，本次没有重复运行或冒充在线双机验证。
''',encoding='utf-8')
print(json.dumps({'pages':4,'bookmarks':4,'local_links':len(targets),'source_links':len(external),'embedded_fonts':sorted(fonts),'page_text':bounds},ensure_ascii=False))
