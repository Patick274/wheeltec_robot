"""更新 A/B 教程并生成四页操作卡；不执行 Git、SSH 或联网操作。"""
from pathlib import Path
import re
import json
import sys
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output/pdf/GitHub_AB两机上传下拉简明手册.pdf'
MD = '03_另一台电脑拉取与上传/GitHub_AB两机同步简明流程.md'
CASE = '04_常见问题/13_本次实际问题与处理.md'
HTTPS = 'https://github.com/Patick274/wheeltec_robot.git'
SSH = 'git@github.com:Patick274/wheeltec_robot.git'
WIN = r'C:\Users\thunderobot\OneDrive\Desktop\项目\轮式升降机\PHM'
FINGERPRINTS = 'https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints'

GUIDE = r'''# GitHub A/B 两机同步简明流程

2026-10-19；基于本次真实仓库与报错整理。步骤供人工逐段执行，报错先停；不代表已经执行。

| 变量 | 本次确定值 |
| --- | --- |
| GitHub 仓库 | Patick274/wheeltec_robot |
| 网页 | https://github.com/Patick274/wheeltec_robot |
| A 电脑 | Windows / PowerShell；本地文件夹仍叫 PHM |
| A 路径 | C:\Users\thunderobot\OneDrive\Desktop\项目\轮式升降机\PHM |
| B 电脑 | Linux / Bash；本教程选择 ~/projects/wheeltec_robot |
| 工作分支 | main，每次用命令核对 |
| 远程别名 | origin，本地别名与仓库名是两回事 |
| A 地址 | https://github.com/Patick274/wheeltec_robot.git |
| B 地址 | git@github.com:Patick274/wheeltec_robot.git |

两种地址指向同一 GitHub 仓库，A/B 本地路径和文件夹名可以不同。
[四页 PDF 操作卡](../output/pdf/GitHub_AB两机上传下拉简明手册.pdf)。

## 1. 查变量、查状态

```bash
git remote -v
git branch --show-current
git branch -vv
git status
```

`origin 地址 (fetch)/(push)` 是同一远程的获取/推送地址；`* main ... [origin/main]` 表示当前 main 已关联上游。
作者姓名和邮箱不是 GitHub 登录身份。`git status` 干净不等于已经上传；还要确认 push 成功。

## 2. A：已有本地代码首次连接空仓库

前提：远程确实为空，本地 main 已有提交，没有进行中的 merge/rebase。
远程创建时不额外添加 README、license 等初始文件，避免与现成项目形成独立历史。

```powershell
Set-Location -LiteralPath 'C:\Users\thunderobot\OneDrive\Desktop\项目\轮式升降机\PHM'
git status
git remote -v
git log -1 --oneline
```

只有 remote -v 没有输出时才添加：

```powershell
git remote add origin https://github.com/Patick274/wheeltec_robot.git
```

如果 origin 已存在但地址错误，改用下面一条；不是两条都执行：

```powershell
git remote set-url origin https://github.com/Patick274/wheeltec_robot.git
```

已有正确本地提交且 clean 时，不必为上传重复 commit。确认后首次推送：

```powershell
git push -u origin main
```

成功后建立上游，日常通常直接 git push。首次 push 被拒不能据此认为上游已建立。
若尚有需要纳入的修改，先按第 4 节暂存、检查、commit，再首次 push。
远程已经有历史时先比较、整合；不强推覆盖。

## 3. B：Linux 首次认证和 clone

先在网页 main 确认 A 的代码已上传。Linux 使用系统终端 Git + SSH，可以不登录 GitHub 插件。
先检查 `git --version`；只有 Git 未安装且系统是 Ubuntu/Debian 时才执行 `sudo apt update` 和 `sudo apt install git`。
每台电脑各自配置作者，**先替换下面邮箱占位文字**：

```bash
git config --global user.name "Patick274"
git config --global user.email "替换成你的提交邮箱"
```

邮箱用 GitHub 已验证邮箱或实际提供的 noreply 邮箱。

### B 的 SSH 只配置一次

```bash
ls -al ~/.ssh
```

先检查已有密钥。仅在没有 id_ed25519 与 .pub 时生成；出现覆盖提示先停，建议设置密钥口令：

```bash
ssh-keygen -t ed25519 -C "Patick274-linux"
```

确认默认保存路径后：

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

复制完整公钥到 GitHub → Settings → SSH and GPG keys → New SSH key，类型 Authentication Key。
可在 A 已登录的浏览器添加 B 的公钥，B 不用登录插件；私钥不复制、不上传。

```bash
ssh -T git@github.com
```

首次连接先核对[官方主机指纹](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)，匹配后再确认。
`Hi Patick274! You've successfully authenticated ... does not provide shell access` 表示成功；无 shell 提示正常。
密钥设了口令时可能询问口令，ssh-agent 可在会话中保存；这不是 GitHub 插件登录。

### 首次克隆，只做一次

```bash
mkdir -p ~/projects
cd ~/projects
git clone git@github.com:Patick274/wheeltec_robot.git
cd ~/projects/wheeltec_robot
git remote -v
git branch -vv
git status
```

目标目录须尚不存在；已有目录先保留并核对。成功 clone 已有 main 时通常已建立 origin 和上游，不再 init 或重复 add origin。
如果 B 已经用 HTTPS 克隆，进入那份仓库后仅切换地址：

```bash
git remote set-url origin git@github.com:Patick274/wheeltec_robot.git
```

## 4. 每日 A/B 交接

A 先用 PowerShell 进入：

```powershell
Set-Location -LiteralPath 'C:\Users\thunderobot\OneDrive\Desktop\项目\轮式升降机\PHM'
```

B 用 Bash 进入：

```bash
cd ~/projects/wheeltec_robot
```

### 开工：先查状态，再拉取

```bash
git branch --show-current
git status
git pull --ff-only
git log -1 --oneline
```

确认 main，工作区干净、无进行中的 merge/rebase，再拉取；有本地修改或报错先处理。
核对另一台电脑的提交后，再编辑、保存代码。

### 收工：检查、提交、上传

```bash
git status
git diff
git add .
git diff --cached
git commit -m "说明本次修改"
git push
git log -1 --oneline
```

git add . 会暂存当前目录内所有未忽略的新增、修改与删除；先确认都需要提交。
只提交某个文件可用 `git add -- '实际文件路径'`。按项目说明完成必要检查。
无新修改就不必创建新 commit；已有未推送提交仍可能需要 push。

### 交接完成的标志

1. A push 成功；网页 main 能看到提交短编号。
2. B 在干净的 main 上 pull，核对 git log -1 --oneline。
3. B 收工也 commit + push；A 接手先 pull。

stash、.venv、被忽略数据和整套运行环境不随普通 push 同步。

## 5. 遇到报错

参见[本次实际问题与处理](../04_常见问题/13_本次实际问题与处理.md)。
独立历史合并、merge --abort、删除重建仓库都不是日常交接动作，不反复套用。

## 来源与边界

- [GitHub：克隆仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
- [GitHub：SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/about-ssh)
- [GitHub：测试 SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection)
- [Git：pull](https://git-scm.com/docs/git-pull)、[merge](https://git-scm.com/docs/git-merge)、[换行配置](https://git-scm.com/docs/git-config)

以本次对话提供的地址和实际错误为依据；不据此宣称 A 已最终上传成功或 B 的认证、clone 已实测通过。
'''

CASES = r'''# 本次实际问题与处理

2026-10-19；仓库 Patick274/wheeltec_robot。以下是历史问题归纳，不是当前仓库状态报告。

| 现象 | 原因与下一步 |
| --- | --- |
| remote -v 无输出 | 本地没配置远程；核对目录后 add origin 一次。网页改名不会自动清空本地 remote。 |
| origin/main/仓库名分不清 | origin 是别名，main 是分支，wheeltec_robot 是 GitHub 仓库名；用 remote -v、branch --show-current、branch -vv 查询。 |
| 每次 push 是否都要一长串 | 核对远程后首次 git push -u origin main；成功后建立上游，日常 git push。clone 的默认分支通常已有关联。 |
| LF will be replaced by CRLF | 换行转换 warning 通常不表示 add 失败；用 status 与 diff --cached 核对，先不乱改全局配置。 |
| Untracked files | 新文件尚未纳入 Git，不代表其他代码没提交；按用途决定提交或忽略，不一定阻止 merge。 |
| working tree clean / nothing to commit | 没有待提交修改，不保证已 push；核对网页同分支的提交。 |
| fetch first / non-fast-forward | 远程有本地没有的提交，重复 push 不会合并；先 fetch，检查历史。 |
| unrelated histories | 两边独立初始化，缺共同祖先；先备份并判断，不将 --allow-unrelated-histories 用作日常同步参数。 |
| CONFLICT (add/add) | 两边各自新增同路径文件；比较内容、清理标记、检查代码、暂存并完成合并，不能盲选一边。 |
| Linux 提示插件登录 | 可用系统终端 Git + SSH；插件不登录，SSH 仍负责仓库身份认证。 |

## 1. 本次真实变量

A Windows HTTPS：`https://github.com/Patick274/wheeltec_robot.git`。
B Linux SSH：`git@github.com:Patick274/wheeltec_robot.git`。
本地别名 origin，目标分支 main；Windows 文件夹叫 PHM 不影响 GitHub 仓库名。

```bash
git remote -v
git branch --show-current
git branch -vv
git status
```

## 2. 远程拒绝：先诊断，再整合

工作区干净、无未完成合并时：

```bash
git fetch origin
git log --oneline --graph --decorate --all -15
git merge-base HEAD origin/main
```

有共同祖先的分叉：参考[问题 7 的 merge 路线](7_两台电脑都提交了.md)，保留双方提交；
冲突解决后完成合并提交、检查，再 push。pull --ff-only 在分叉时停止是正常保护。

本次旧仓库曾确认：本地初始提交与远程历史独立。需要有意保留两套历史时，先备份已提交版本，
另存未提交内容，再评估 `git merge origin/main --allow-unrelated-histories --no-commit`。
对新手也可保留旧目录、在新目录 clone 正确仓库、比较复制源码，**不复制旧 .git**，然后提交。
不强推覆盖远程，不删除 .git 试错。

## 3. 本次 5 个 add/add 冲突

当时涉及 kinco_lift_control 的 CMakeLists.txt、README.md、docs/README.md、explain.yaml、canopen.py。
比较显示，本地包含更新的 Kvaser 指南和诊断入口，远程仍含旧 candleLight 说明；应逐项核对，
不能因为标签写着 Current/Incoming 就机械选择，也不能把两套控制代码重复拼接。

若继续 merge：整理内容、删除 <<<<<<< / ======= / >>>>>>> 标记，运行项目检查，
git add 已解决文件后完成 merge commit，再 push。
`backup/before-history-merge` 只保护已提交历史，不保存未提交内容。

比较后用户中断了该轮，随后新建空仓库；**不能声称这 5 处已由助手修复**。

## 4. 新建空远程后，旧 merge 状态不会自动消失

仅当明确要放弃那次尚未完成的 merge，且已核对并保留所需现场修改时：

```bash
git merge --abort
git status
```

开始 merge 前工作区干净时，abort 通常恢复合并前状态，已提交内容仍保留。
确认新远程确实为空、地址正确、本地 main 已有提交并无未完成合并后，才首次 `git push -u origin main`。
重建仓库与 abort 都不属于日常 A/B 同步动作。

## 5. 本次新增工作区文件

`code/code.code-workspace` 当时检查只有相对路径 `.`，可以按需随仓库同步：

```bash
git add -- code/code.code-workspace
git commit -m "添加 VS Code 工作区配置"
```

路径以仓库根目录为起点；它不是所有未跟踪配置文件都应上传的通用结论。

## 6. Linux 不登录插件

在系统终端单独配置 SSH；B 生成自己的密钥，只将公钥登记到 GitHub。
可以在 A 已登录的浏览器添加 B 公钥，B 不用登录插件。私钥不复制、不上传。
测试 `ssh -T git@github.com`，返回 Hi Patick274! 的认证成功消息；不提供 shell 是正常提示。
私有仓库 clone 和正常 push 仍需有效权限。

完整步骤：[A/B 两机同步简明流程](../03_另一台电脑拉取与上传/GitHub_AB两机同步简明流程.md)。
来源：[git merge](https://git-scm.com/docs/git-merge)、[git pull](https://git-scm.com/docs/git-pull)、
[SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/about-ssh)、[换行配置](https://git-scm.com/docs/git-config)。

## 核实边界

Windows 分支与远程地址曾只读核实。旧远程在删除重建后不再作为当前历史依据；
新仓库重建时曾查询为空，不代表现在仍为空。最终上传、Linux 的认证与 clone 暂无完整成功输出。
本次资料更新只改 code 内文件，不执行 merge、abort、commit、push 或修改 SSH 配置。
'''

def read(name):
    return (ROOT/name).read_text(encoding='utf-8-sig')

def write(name,text):
    path=ROOT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text.strip()+'\n',encoding='utf-8')

def update_docs():
    write(MD,GUIDE);write(CASE,CASES)
    text=read('README.md')
    text=text.replace('# GitHub / PHM 双机协作学习包','# GitHub / wheeltec_robot 双机协作学习包',1)
    marker='## 当前优先使用：A/B 简明版'
    intro='''## 当前优先使用：A/B 简明版

- **[4 页 PDF：A/B 两机上传与下拉](output/pdf/GitHub_AB两机上传下拉简明手册.pdf)**。
- **[配套 Markdown：可复制完整步骤](03_另一台电脑拉取与上传/GitHub_AB两机同步简明流程.md)**。
- [本次真实报错与处理顺序](04_常见问题/13_本次实际问题与处理.md)。

实际仓库 Patick274/wheeltec_robot；远程别名 origin，目标分支 main。
A 为 Windows，本地目录仍叫 PHM；B 为 Linux，使用系统终端 Git + SSH，无需登录 GitHub 插件。
原 19 页长版保留作界面与原理参考，其中 YOUR-USER/PHM 为通用示意。

'''
    if marker in text:
        text=text[:text.index(marker)]+intro+text[text.index('## 从这里开始'):]
    else:
        text=text.replace('## 从这里开始',intro+'## 从这里开始',1)
    a=text.index('日期：2026-10-19。');b=text.index('\n---',a)
    text=text[:a]+'''日期：2026-10-19。用户已提供真实 wheeltec_robot 地址，Windows 的 main 与远程配置曾只读核实。
本次只更新 code 内学习文件，不执行 merge/abort、commit/push，也不修改账户、密钥或仓库配置。
不据此宣称最终上传或 Linux 端认证、clone 已成功。旧长版为 PHM 示意，新简明版使用实际地址。
来源见 [官方资料](官方资料.md)；简明版源码为 build_github_ab_brief.py，长版源码为 build_github_guide.py。
新 PDF 检查见 [A/B 简明版校验记录](GitHub_AB简明版校验记录.md)；早前 Git 演练见 [验证记录](验证记录.md)。
'''+text[b:]
    write('README.md',text)
    name='03_另一台电脑拉取与上传/每日交接清单.md'
    text=read(name)
    if '当前仓库：' not in text:
        text=text.replace('## 开工','''当前仓库：Patick274/wheeltec_robot，分支 main，远程别名 origin。
A：Windows/PHM；B：Linux 的 ~/projects/wheeltec_robot（本教程选定路径）。
先看 [A/B 简明流程](GitHub_AB两机同步简明流程.md)，打印使用 [4 页 PDF](../output/pdf/GitHub_AB两机上传下拉简明手册.pdf)。

## 开工''',1)
    text=text.replace('仓库：PHM','仓库：Patick274/wheeltec_robot').replace('分支：\n','分支：main\n')
    write(name,text)
    name='03_另一台电脑拉取与上传/00_双机同步先看这篇.md'
    text=read(name)
    if '本次实际配置' not in text:
        first,rest=text.split('\n',1)
        text=first+'''\n
> 本次实际配置：Patick274/wheeltec_robot；A 为 Windows，B 为 Linux。
> 优先看 [A/B 简明流程](GitHub_AB两机同步简明流程.md) 和 [4 页 PDF](../output/pdf/GitHub_AB两机上传下拉简明手册.pdf)。
> 下文保留通用 PowerShell 示例；YOUR-USER/PHM 为占位值。Linux 不照抄 PowerShell 路径命令。
'''+rest
    write(name,text)
    name='04_常见问题/2_未配置远程或上游.md';text=read(name)
    text=text.replace('https://github.com/YOUR-USER/PHM.git',HTTPS)
    text=text.replace('没有 origin 时（下面 URL 按实际替换）：','没有 origin 时，本次 Windows 仓库使用：')
    if '本次真实配置：' not in text:
        first,rest=text.split('\n',1)
        text=first+'''\n
本次真实配置：仓库 Patick274/wheeltec_robot，origin 为本地远程别名，main 为目标分支。
只有首次 push 成功后才能据此确认上游建立；成功 clone 的默认分支通常已有上游。
Linux SSH 和已有 origin 修改地址的步骤见 [A/B 简明流程](../03_另一台电脑拉取与上传/GitHub_AB两机同步简明流程.md)。
'''+rest
    write(name,text)
    name='04_常见问题/6_推送拒绝与冲突.md';text=read(name)
    if '本次真实问题' not in text:
        first,rest=text.split('\n',1)
        text=first+'''\n
本次真实问题包括独立历史、add/add 冲突和重建远程后残留的本地合并状态，
先看 [实际问题与处理](13_本次实际问题与处理.md)。普通分叉优先参考 [问题 7 的 merge 路线](7_两台电脑都提交了.md)；
下文 rebase 仅在尚未发布本地提交等前提满足时使用。
'''+rest
    write(name,text)
    name='build_github_guide.py';text=read(name)
    text=text.replace("if __name__=='__main__':\n    docs()\n    pdf()", "if __name__=='__main__':\n    # 默认只重建长版 PDF，避免覆盖已按真实问题修订的 Markdown。\n    if '--regenerate-generic-docs' in sys.argv:\n        docs()\n    pdf()")
    write(name,text)
    name='官方资料.md';text=read(name)
    if '## A/B 简明版补充' not in text:
        text+='''\n## A/B 简明版补充

2026-10-19 核对，实际仓库 Patick274/wheeltec_robot；PDF 末页列出可点击官方依据。

- [SSH 认证](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/about-ssh)：不依赖编辑器插件，密钥负责认证。
- [测试 SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection)：判断 Hi Patick274! 与无 shell 提示。
- [主机指纹](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)：首次连接核对。
- [克隆仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)：B 首次独立 clone。
- [git merge](https://git-scm.com/docs/git-merge)：独立历史、冲突与 abort 的适用前提。
- [git config](https://git-scm.com/docs/git-config)：换行转换与配置。
'''
    write(name,text)

W,H=A4;M=42;BW=W-2*M
NAVY=colors.HexColor('#153148');TEAL=colors.HexColor('#007F82');GOLD=colors.HexColor('#B87821')
INK=colors.HexColor('#243E52');MUTED=colors.HexColor('#637A8C');LIGHT=colors.HexColor('#EDF4F7')
pdfmetrics.registerFont(TTFont('AB', 'C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('ABB', 'C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
pdfmetrics.registerFontFamily('AB',normal='AB',bold='ABB',italic='AB',boldItalic='ABB')
C=None;Y=0;PAGE=0;AUDIT=[]

def draw(text,x,y,w,size=10,leading=16,color=INK,bold=False):
    style=ParagraphStyle('ab',fontName='ABB' if bold else 'AB',fontSize=size,leading=leading,textColor=color,wordWrap='CJK')
    q=Paragraph(text,style);_,h=q.wrap(w,1000)
    if y-h<56:raise ValueError(f'Page {PAGE} overflow: {text[:35]}')
    q.drawOn(C,x,y-h)
    AUDIT.append(dict(page=PAGE,bottom=round(y-h,2),text=re.sub('<[^>]+>','',text)[:70]))
    return y-h

def p(text,size=10,leading=16,gap=8):
    global Y
    Y=draw(text,M,Y,BW,size,leading)-gap

def heading(text):
    global Y
    Y=draw(text,M,Y,BW,13,21,TEAL,True)-7

def code(lines,size=9):
    global Y
    if isinstance(lines,str):lines=lines.splitlines()
    h=16*len(lines)+20
    if Y-h<57:raise ValueError(f'code overflow on {PAGE}')
    C.setFillColor(NAVY);C.roundRect(M,Y-h,BW,h,7,fill=1,stroke=0)
    for i,line in enumerate(lines):
        if pdfmetrics.stringWidth(line,'AB',size)>BW-28:raise ValueError('wide code: '+line)
        C.setFont('AB',size);C.setFillColor(colors.HexColor('#ADDCD7') if line.startswith('#') else colors.white)
        C.drawString(M+14,Y-20-i*16,line)
    Y-=h+10

def note(label,text,warm=False):
    global Y
    col=GOLD if warm else TEAL
    style=ParagraphStyle('note',fontName='AB',fontSize=9.5,leading=15,textColor=INK,wordWrap='CJK')
    q=Paragraph(text,style);_,h=q.wrap(BW-30,1000);total=h+39
    if Y-total<57:raise ValueError(f'note overflow on {PAGE}')
    C.setFillColor(colors.HexColor('#FFF5E7') if warm else LIGHT);C.roundRect(M,Y-total,BW,total,7,fill=1,stroke=0)
    C.setFillColor(col);C.rect(M,Y-total,3,total,fill=1,stroke=0)
    draw(label,M+13,Y-9,BW-26,9.5,15,col,True)
    q.drawOn(C,M+13,Y-31-h);Y-=total+11

def rows(data,size=9.5,left=120):
    global Y
    for i,(a,b) in enumerate(data):
        sa=ParagraphStyle('l',fontName='ABB',fontSize=size,leading=15,textColor=TEAL,wordWrap='CJK')
        sb=ParagraphStyle('r',fontName='AB',fontSize=size,leading=15,textColor=INK,wordWrap='CJK')
        qa,qb=Paragraph(a,sa),Paragraph(b,sb)
        ha=qa.wrap(left-18,1000)[1];hb=qb.wrap(BW-left-18,1000)[1];h=max(ha,hb)+14
        if Y-h<57:raise ValueError('row overflow '+str(PAGE)+' '+a)
        C.setFillColor(LIGHT if i%2==0 else colors.white);C.rect(M,Y-h,BW,h,fill=1,stroke=0)
        qa.drawOn(C,M+9,Y-7-ha);qb.drawOn(C,M+left+9,Y-7-hb);Y-=h
    Y-=10

def start(title,subtitle):
    global Y,PAGE
    if PAGE:C.showPage()
    PAGE+=1
    C.setFillColor(TEAL);C.rect(0,H-8,W,8,fill=1,stroke=0)
    C.setFont('ABB',9);C.drawString(M,H-36,'GITHUB A / B  ·  WINDOWS + LINUX')
    C.setFillColor(NAVY);C.setFont('ABB',23);C.drawString(M,H-76,title)
    Y=H-94;Y=draw(subtitle,M,Y,BW,9.6,16,MUTED)-15
    C.setStrokeColor(colors.HexColor('#D6E2E9'));C.line(M,42,W-M,42)
    C.setFillColor(MUTED);C.setFont('AB',8);C.drawString(M,27,'Patick274 / wheeltec_robot   ·   2026-10-19')
    C.drawRightString(W-M,27,f'{PAGE} / 4')
    C.bookmarkPage('p'+str(PAGE));C.addOutlineEntry(title,'p'+str(PAGE),0)

def make_pdf():
    global C,Y
    OUT.parent.mkdir(parents=True,exist_ok=True)
    C=canvas.Canvas(str(OUT),pagesize=A4,pageCompression=1)
    C.setTitle('GitHub A/B 两机上传下拉简明手册')
    C.setAuthor('wheeltec_robot 学习资料')
    start('每天只看这一页','仓库 Patick274/wheeltec_robot；分支 main；远程别名 origin。先完成首次配置；报错先停。')
    note('交接顺序','A（Windows）push → GitHub → B（Linux）pull；B 做完再 push，回 A 先 pull。')
    rows([('A / Windows','PowerShell，进入本地 PHM 文件夹；可继续使用 HTTPS。'),('B / Linux','Bash，教程目录 ~/projects/wheeltec_robot；采用 SSH，不用登录插件。')],size=10)
    p('clone 首次克隆；pull 下拉并整合；commit 形成本地版本；push 上传提交。',size=9.5,leading=15)
    heading('01  开工：先看状态，拉取后再编辑')
    code(['git branch --show-current','git status'])
    p('确认当前 main，工作区干净且无进行中的合并后，再运行下面两条。',size=9.5,leading=15,gap=5)
    code(['git pull --ff-only','git log -1 --oneline'])
    p('核对另一台电脑的提交后，再编辑和保存。',size=9.5,leading=15,gap=5)
    heading('02  收工：检查 → 暂存 → 提交 → 推送')
    code(['git status','git diff','git add .','git diff --cached','git commit -m "说明本次修改"','git push','git log -1 --oneline'])
    p('git add . 会暂存当前目录内所有未忽略修改；先确认文件范围。无新修改不必新 commit，已有提交仍可能待 push。按项目说明完成必要检查。',size=9.5,leading=15)
    note('交接成功的标志','push 成功；网页选 main 看到提交短编号；另一台 pull 后核对同一提交。clean 只表示本地没有待提交修改，不代表已上传。',warm=True)

    start('首次连接：A 上传，B 克隆','首次配置和每日操作分开；以下各段有不同前提，不整页一次执行。')
    heading('A / Windows：已有本地提交 → 空远程')
    code(["Set-Location -LiteralPath '"+WIN+"'",'git status','git remote -v','git branch --show-current'],size=8.0)
    p('仅当 remote -v 无输出时，添加一次：',gap=5)
    code(['git remote add origin '+HTTPS],size=8.7)
    p('已有正确 origin 就跳过 add；地址错误用 set-url，详见配套 MD。确认远程为空、本地 main 已有提交且无未完成合并后：',size=9.5,leading=15,gap=6)
    code(['git push -u origin main'])
    p('-u 成功后记住上游，以后通常 git push。已有提交无需为上传再造一次 commit；远程有历史先看第 4 页。',size=9.5,leading=15)
    heading('B / Linux：作者配置与首次 clone')
    p('先在 GitHub 网页确认 A 已上传；B 的 SSH 认证见第 3 页。检查 git --version；未安装时按发行版安装 Git。先替换邮箱再运行：',size=9.5,leading=15,gap=6)
    code(['git config --global user.name "Patick274"','git config --global user.email "替换成你的提交邮箱"'])
    code(['mkdir -p ~/projects','cd ~/projects','git clone '+SSH,'cd ~/projects/wheeltec_robot','git branch -vv'],size=8.8)
    p('目标目录已存在就先核对，不覆盖。clone 已有 main 时通常自动配置 origin 和上游；不再 init。A/B 路径和认证方式可以不同。',size=9.5,leading=15)
    note('三个变量，随时查','git remote -v 查别名和地址；git branch --show-current 查当前分支；git branch -vv 中 [origin/main] 表示上游已关联。')

    start('Linux 不登录插件：用 SSH','在 Linux 系统终端执行；GitHub 插件可以不登录，SSH 密钥负责仓库认证。')
    heading('01  先检查，再按需生成本机密钥')
    code(['ls -al ~/.ssh'])
    p('已有 id_ed25519 和 .pub 可先评估复用；仅在没有时运行下一条。若提示覆盖先停，保存位置可用默认值，建议设置密钥口令。',size=9.6,leading=16,gap=6)
    code(['ssh-keygen -t ed25519 -C "Patick274-linux"'])
    heading('02  加载密钥，复制公钥到 GitHub')
    code(['eval "$(ssh-agent -s)"','ssh-add ~/.ssh/id_ed25519','cat ~/.ssh/id_ed25519.pub'])
    p('复制输出的完整公钥。可在 A 已登录的浏览器操作：<br/><b>Settings → SSH and GPG keys → New SSH key</b><br/>类型 Authentication Key，标题可写 Linux电脑，粘贴公钥。只复制 .pub；私钥不上传、不复制到另一台电脑。',size=10,leading=17)
    heading('03  测试认证，再用 SSH clone / push')
    code(['ssh -T git@github.com'])
    p('首次连接核对 <a href="'+FINGERPRINTS+'" color="#007F82">GitHub 官方主机指纹（点击）</a>，匹配后再确认。成功消息应含 Hi Patick274!；does not provide shell access 是正常提示。',size=9.5,leading=16)
    note('出现 Permission denied (publickey)','说明密钥认证尚未完成：核对公钥是否加到正确账号、agent 是否加载正确密钥。若成功消息显示别的账号，也先停止核对。',warm=True)
    p('如果 B 已经用 HTTPS 克隆，进入那份仓库，仅将 origin 改为 SSH 地址：',size=9.5,leading=15,gap=5)
    code(['git remote set-url origin '+SSH],size=8.7)
    p('设有口令的密钥可能询问本机口令；agent 会话结束后可能需要重新加载。这不要求登录 GitHub 插件。',size=9.3,leading=15)

    start('遇到报错：查原因，不反复 push','你的实际问题速查。每段报错先停；特殊历史处理不混入每天的操作卡。')
    rows([
        ('LF → CRLF warning','换行提示通常不代表 add 失败；用 status 和 diff --cached 核对，先不乱改全局配置。'),
        ('remote -v 无输出','当前本地仓库无远程。核对目录后 add origin 一次；已有 origin 改地址用 set-url。'),
        ('push 要求指定目标','远程和上游需先设置；首次成功 push -u origin main，之后通常直接 push。'),
        ('Untracked / clean','新文件按需提交或忽略；clean / nothing to commit 只说明无待提交修改，仍可能待上传。'),
        ('fetch first / 分叉','先看 status、fetch 和提交图；有共同历史时合并双方提交。--ff-only 分叉会停止。'),
        ('unrelated histories','两边独立初始化，先备份并诊断；--allow-unrelated-histories 是特殊操作，不是每日参数。'),
        ('CONFLICT (add/add)','同路径文件由双方分别新增。比较内容、清理标记、检查并暂存，再完成合并；不盲选一边。'),
        ('新空仓库仍有旧冲突','仅明确放弃旧 merge 且已保留所需修改时用 merge --abort；确认恢复状态后再首次 push。'),
        ('插件要求登录','Linux 用终端 Git + SSH；插件可不登录，仓库认证仍要完成。详见第 3 页。')
    ],size=9.2,left=133)
    note('历史与范围','你曾遇到两套独立历史和 5 个 add/add 冲突，后改用新空仓库。本手册只更新学习资料，不执行合并、提交或推送；不宣称 Linux 已配置成功。详细分流见配套 MD。',warm=True)
    heading('官方依据 / 点击打开')
    links=[('GitHub 克隆','https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository'),('SSH 认证','https://docs.github.com/en/authentication/connecting-to-github-with-ssh/about-ssh'),('SSH 测试','https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection'),('git pull','https://git-scm.com/docs/git-pull'),('git merge','https://git-scm.com/docs/git-merge'),('换行配置','https://git-scm.com/docs/git-config')]
    p('  /  '.join('<a href="'+url+'" color="#007F82">'+escape(name)+'</a>' for name,url in links),size=8.8,leading=15)
    p('配套：code/03_另一台电脑拉取与上传/GitHub_AB两机同步简明流程.md<br/>详细报错：code/04_常见问题/13_本次实际问题与处理.md',size=8.4,leading=14,gap=0)
    C.save()
    qa=ROOT/'tmp/pdfs/github_ab';qa.mkdir(parents=True,exist_ok=True)
    (qa/'layout.json').write_text(json.dumps(AUDIT,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PDF generated: '+str(OUT)+'; pages='+str(PAGE))

if __name__=='__main__':
    update_docs()
    make_pdf()
