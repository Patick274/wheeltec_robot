"""生成本目录的 GitHub 教材及 PDF；不连接远程、不改动 Git 配置。"""
from pathlib import Path
import re, shutil, json, html, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parent
def write(name, text):
    p = ROOT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + '\n', encoding='utf-8')

SOURCES = [
('S01', 'GitHub 仓库的组成', 'https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories'),
('S02', '浏览 GitHub 代码与文件', 'https://docs.github.com/en/repositories/working-with-files/using-files/navigating-code-on-github'),
('S03', 'Desktop 分支同步', 'https://docs.github.com/en/desktop/working-with-your-remote-repository-on-github-or-github-enterprise/syncing-your-branch-in-github-desktop'),
('S04', 'git pull：快进与整合', 'https://git-scm.com/docs/git-pull'),
('S05', 'Pro Git：Git 基础与快照', 'https://git-scm.com/book/en/v2/Getting-Started-What-is-Git%3F'),
('S06', 'Pro Git：Git 对象', 'https://git-scm.com/book/en/v2/Git-Internals-Git-Objects'),
('S07', 'rebase 与共享历史', 'https://docs.github.com/en/get-started/using-git/about-git-rebase'),
('S08', 'stash：临时保存工作', 'https://git-scm.com/docs/git-stash'),
('S09', 'GitHub flow：分支与 PR', 'https://docs.github.com/en/get-started/using-github/github-flow'),
('S10', 'GitHub 身份认证', 'https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github'),
('S11', '大文件限制', 'https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github'),
('S12', '仓库设置', 'https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings'),
('S13', '仓库活动与数据', 'https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository'),
('S14', 'git revert：反向提交', 'https://git-scm.com/docs/git-revert'),
('S15', 'git reflog：本机引用记录', 'https://git-scm.com/docs/git-reflog'),
('S16', 'GitHub 网页上传文件', 'https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository'),
('S17', 'HTTPS 凭据缓存与 GCM', 'https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git'),
('S18', '管理个人访问令牌', 'https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens'),
('S19', 'SSH 密钥与 agent', 'https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent'),
('S20', 'Desktop 推送提交', 'https://docs.github.com/en/desktop/making-changes-in-a-branch/pushing-changes-to-github-from-github-desktop'),
]

def docs():
    # 保留输入原件；其内容是待核对资料，不作为执行命令。
    for name in ('小白github.txt', '要求.txt'):
        src = Path('C:/Users/thunderobot/OneDrive/Desktop') / name
        dst = ROOT / '00_原始材料' / name
        dst.parent.mkdir(exist_ok=True)
        if not dst.exists(): shutil.copyfile(src, dst)
    write('00_原始材料/阅读说明.md', '''# 原始材料与本次整理
两份 TXT 为用户提供的参考原件，按原样保存。当前聊天请求决定工作范围：分类教程、两台电脑同步、仓库界面与提交原理 PDF。
材料内的命令只是学习示例，不授权实际上传、登录、改配置或执行删除。

主要修订：HTTPS 可用 GCM 浏览器认证，不必强制使用 PAT；不建议明文 credential.helper store；
每台电脑单独生成 SSH 密钥；日常先用 pull --ff-only；分叉时再选择 merge 或有条件的 rebase；
stash 不上传且 -u 不含被忽略文件；远程已有文件时优先 clone；修正 ZIP 与 Git 历史的区别。
现有四类教程保留，新增专题文档补齐交接、恢复、界面与检查清单。
''')
    write('03_另一台电脑拉取与上传/00_双机同步先看这篇.md', r'''# 两台电脑操作同一 PHM：完整交接步骤

最常用规则：**开工先拉，收工先提交、再推送，另一台电脑再拉。**
本例默认实际分支是 main。若你的仓库叫 master 或其他名称，先查清楚再替换；不要为了套教程改分支名。
命令逐段执行，任一步失败先停止。不要整篇复制执行。

## 1. 两台电脑究竟是什么关系

```text
电脑 A 的独立克隆 ──push──> GitHub 上的 PHM ──pull──> 电脑 B 的独立克隆
电脑 A 的独立克隆 <──pull── GitHub 上的 PHM <──push── 电脑 B 的独立克隆
```

两台电脑可以使用同一个 GitHub 账号、同一个仓库和同一个分支。
路径可以不同，例如 A 是 D:\Projects\PHM，B 是 C:\Projects\PHM。
同一账号不会自动同步，编辑器点保存、git add、git commit 都不等于上传。
两台电脑各自 clone 一份；不需要 fork 自己的仓库，不需要每天 clone 或 git init。
建议工作克隆放在非 OneDrive 自动同步目录，避免云盘与 Git 同时管理 .git。
本次只生成教程，不迁移当前目录。若要迁移，先备份未推送提交、未提交文件、忽略文件和 stash。

## 2. B 电脑首次准备（只做一次）

安装 Git，配置本机姓名和邮箱，并选择认证方式。推荐新手 Desktop，或 HTTPS + GCM 浏览器登录。
SSH 用户在 B 单独生成密钥，把 B 的公钥加入同一账号；不要复制 A 的私钥。

```powershell
git --version
git config --global user.name "你的提交显示名"
git config --global user.email "GitHub 已验证邮箱或提供的 noreply 邮箱"
# 上面是作者信息；不是 GitHub 登录。
New-Item -ItemType Directory -Force 'D:\Projects'
Set-Location -LiteralPath 'D:\Projects'
git clone https://github.com/YOUR-USER/PHM.git PHM
# YOUR-USER 换成网页 Code 按钮复制地址里的用户名。
# SSH 方式只替换 clone 地址：git@github.com:YOUR-USER/PHM.git
Set-Location -LiteralPath 'D:\Projects\PHM'
git remote -v
git branch -vv
git status
# 核对 origin、当前分支和上游。若已有同名目录，不覆盖，另选路径。
```

成功标志：能看到项目文件、.git 元数据、正确的当前分支与 origin 地址。
若已有文件夹但没有 Git 历史，先保留它，clone 到新目录，再比较复制源码，不复制旧 .git。

## 3. 每次在 A 开工（B 同理）

```powershell
Set-Location -LiteralPath 'D:\Projects\PHM'
git rev-parse --show-toplevel
git branch --show-current
git status
# 确认仓库、分支正确且没有未处理修改/合并。
git pull --ff-only
# 使用当前分支的上游。分叉会停下，转看问题 7。
```

拉取成功后才编辑并保存文件。如果发现本地有修改，先看问题 8，不要直接丢弃。
不要在 feature 分支随手执行 git pull origin main；它会把 main 整合进当前分支，不是切到 main。

## 4. A 收工：把这次工作交给 B

```powershell
git status
git diff
# 先查看未暂存修改，确认新增文件与删除也符合预期。
git add -- '实际需要提交的文件路径'
# 多个文件可逐个暂存；确认全都应该上传时才在仓库根目录使用 git add .
git diff --cached --stat
git diff --cached
# 检查暂存区；按项目实际说明运行必要检查。
git commit -m "修复传感器数据读取"
git push
# 首次推送新分支需 git push -u origin 分支名。
git status -sb
git log -1 --oneline
```

成功标志：push 成功；GitHub 网页选中**同一分支**能看到相同提交短编号和文件改动。
`working tree clean` 只代表本地没有未提交内容，可能仍然 ahead，不能单独证明上传成功。
只读核对：git fetch origin 后 git status -sb，或按问题 7 查看左右提交数量。

## 5. 换到 B

```powershell
Set-Location -LiteralPath 'D:\Projects\PHM'
git branch --show-current
git status
git pull --ff-only
git log -1 --oneline
# 核对刚才 A 推送的提交，再开始编辑。
```

B 收工同样 add → 检查 → commit → push。回 A 后也先 pull。
如果 B 一直提示 Already up to date，但没看到 A 的文件，按问题 9 排查：A 是否真的 push、分支是否相同、路径是否正确。

## 6. 按场景跳转

| 场景 | 处理位置 |
| --- | --- |
| 两边都改了并 commit，push 拒绝 | [问题 7](../04_常见问题/7_两台电脑都提交了.md) |
| 修改没提交，pull 会覆盖 | [问题 8](../04_常见问题/8_未提交修改与stash.md) |
| A 忘记 push、B 看不到新代码 | [问题 9](../04_常见问题/9_更新不见了与忘记推送.md) |
| merge 或 rebase 冲突 | [冲突逐行练习](冲突逐行练习.md) |
| 同一个功能跨电脑继续做 | [功能分支交接](功能分支跨电脑交接.md) |
| 离线时要换电脑 | 先在原电脑 commit；网络恢复后 push；stash 不会传到 B |
| 不能再访问 A，且 A 没 push | GitHub 无法凭空取回 A 的独有文件，先找 A 本地或既有备份 |

推荐先读一遍流程，再使用 [每日交接清单](每日交接清单.md)。
来源：[Desktop 同步](https://docs.github.com/en/desktop/working-with-your-remote-repository-on-github-or-github-enterprise/syncing-your-branch-in-github-desktop)、[git pull](https://git-scm.com/docs/git-pull)。
''')
    write('03_另一台电脑拉取与上传/每日交接清单.md', '''# 双机每日交接清单

## 开工

- [ ] 终端和编辑器打开的是同一个正确克隆目录。
- [ ] git branch --show-current 显示目标分支。
- [ ] git status 没有未处理修改、merge 或 rebase。
- [ ] git pull --ff-only 成功；有报错先停下。
- [ ] 最新提交符合另一台电脑的交接记录。

## 收工

- [ ] 保存文件，git diff 检查本次修改。
- [ ] 仅暂存所需文件，git diff --cached 检查实际提交内容。
- [ ] 完成项目自己的必要检查；不把不完整功能混进稳定 main。
- [ ] git commit -m "本次改动" 成功。
- [ ] git push 成功，网页相同分支看到新提交。
- [ ] 记录当前分支、提交短编号和未完成事项。

## 交接记录模板（复制填写）

```text
日期：
来源电脑：A / B
仓库：PHM
分支：
最后提交短编号：
push 是否成功：
已完成：
待完成：
验证情况：
未进入 Git 的数据或环境文件：
```

stash、.venv、被忽略数据不会随着普通 push 传到另一台电脑。
''')
    write('04_常见问题/7_两台电脑都提交了.md', r'''# 问题 7：A、B 都提交了，push 被拒绝或 pull 无法快进

适用：两份克隆来自同一仓库、有共同历史，当前是 main。先完成或撤销已有 merge/rebase，再做新操作。
先 git status；有未提交修改看问题 8。`backup/b-before-sync` 是示例备份名，已存在就换一个唯一名称。

## 1. 判断进度

```powershell
git branch --show-current
git status
git branch backup/b-before-sync
# 保护当前已提交版本；不保存未提交、未跟踪、忽略文件。
git fetch origin
git log --oneline --graph --decorate --all -15
git rev-list --left-right --count 'HEAD...@{upstream}'
# 左数 = 本地独有提交，右数 = 上游独有提交。PowerShell 中保留单引号。
# 若没有上游，先按问题 2 核对并设置，不要猜 main。
```

| 左数 / 右数 | 解释 | 下一步 |
| --- | --- | --- |
| 0 / 0 | 同步 | 无需同步提交；另查未提交文件 |
| 0 / 正数 | 本地落后 | git pull --ff-only |
| 正数 / 0 | 本地领先 | 检查后 git push |
| 正数 / 正数 | 分叉 | 下面 merge 或有条件的 rebase，二选一 |

fetch 更新本机掌握的远程信息；离线时这些信息可能过期。

## 2. 初学者默认用 merge，保留双方已存在的提交

```powershell
git merge origin/main
# 工作区应干净，当前确实 main；若是别的分支，请替换成对应远程跟踪分支。
```

没有冲突：完成合并、按项目说明检查，再 git push。
有冲突：打开文件，按 [冲突逐行练习](../03_另一台电脑拉取与上传/冲突逐行练习.md) 合并内容。

```powershell
git status
git add -- '实际冲突文件路径'
# 所有冲突解决并暂存后才继续。
git diff --cached
git commit -m "合并另一台电脑的修改"
# 若出现编辑器，保存合并消息并退出。
git push
```

不继续本次 merge 时执行 git merge --abort。操作开始前保持干净，便于恢复。
若稍后又有人推送，push 仍可能拒绝，重新 fetch 并检查新的差异，不强推。

## 3. 可选：只对未发布的普通本地提交用 rebase

如果本地新增提交未 push、未被另一台电脑或协作者使用，而且没有需要保留的复杂合并历史，可改选：

```powershell
git rebase origin/main
# 前提是刚才已 fetch；不要紧接在已完成的 merge 流程后机械执行。
```

冲突处理后 git add -- '文件路径'，再 git rebase --continue，可能重复多轮；
全部完成并检查后 git push。不需要为了这次同步强推。
放弃时 git rebase --abort。rebase 会生成新提交编号；不要随意重写双方已经共享的提交。

## 4. 图解

```text
共同起点 C0
  ├─ A1（A 已推送，origin/main）
  └─ B1（B 本地，main）

merge：C0→A1→M，且 B1 也是 M 的父提交；保留 A1 和 B1。
rebase：C0→A1→B1'；把 B 的改动重新提交，B1' 的编号不同。
```

来源：[git pull](https://git-scm.com/docs/git-pull)、[rebase 共享历史限制](https://docs.github.com/en/get-started/using-git/about-git-rebase)。
''')
    write('04_常见问题/8_未提交修改与stash.md', r'''# 问题 8：我已经修改代码，还没 commit，怎么 pull？

优先先把当前进度保存到合适的功能分支并 commit；若只是临时挪开修改，可以使用 stash。
stash 是本机临时抽屉，不是云备份，普通 push 不包含它。
本例开始前没有正在进行的 merge/rebase，没有未解决冲突。

```powershell
git status
git stash push -u -m "同步前暂存"
# -u 包括未跟踪文件；不含 .gitignore 忽略的文件。
git stash list
git status
# 确认修改已经妥善收起，再拉取。
git pull --ff-only
```

pull 失败：停止，先解决问题 7 的分叉或其他错误。不要继续恢复命令。
pull 成功后，确认要恢复的 stash 编号：

```powershell
git stash show --stat 'stash@{0}'
git stash apply 'stash@{0}'
# apply 保留原记录，恢复可能冲突；不要反复 apply。
git status
```

若发生冲突，人工解决、保存、git add 对应文件，检查并 commit。
**stash apply 冲突没有 stash --continue，也不使用 rebase --continue。**
本流程在干净状态拉取成功后才 apply，冲突解决后直接形成普通提交。
确认所有文件已正确恢复、提交或另有备份，才可单独清理准确记录：

```powershell
git stash list
git stash drop 'stash@{0}'
# 可选；drop 仅在确认该记录已经不需要时执行。
```

需要带到 B 的未完成功能：用功能分支 commit + push，B 再 fetch 并切到该分支；见功能分支交接。
被忽略的原始数据、密钥和本地环境另行安排，不用 stash -a 随手打包所有秘密。
来源：[git stash](https://git-scm.com/docs/git-stash)。
''')
    write('04_常见问题/9_更新不见了与忘记推送.md', r'''# 问题 9：A 明明改了，B 却没有？

按顺序排查，每次只处理发现的那一项。

## A 没有推送

在 A：检查编辑器是否保存；git status 看未提交内容；git log -1 --oneline 看最近提交。
仅 commit 没有 push，B 无法从 GitHub 获取。
完成必要检查并 push 后，在网页相同分支确认，再到 B pull。
如果 A 离线，先本地 commit，联网再 push。A 不在手边且没有其他备份时，GitHub 无法恢复未上传工作。

## 分支不同

```powershell
git branch --show-current
git branch -vv
git fetch origin
git branch -a
```

A 在 feature 分支推送，B 的 main 不会自动拥有该功能；网页也要选 feature 才能看见。
工作区干净时切换对应本地分支；仅远程存在时：git switch --track origin/实际分支名。

## 仓库或目录错了

```powershell
git rev-parse --show-toplevel
git remote -v
git log -1 --oneline
```

确认编辑器打开的目录与终端根目录相同，A、B 的 origin 指向同一 owner/PHM。
同名 PHM 可以位于不同账号；文件夹名也可以与仓库名不同。
ZIP 解压副本没有 .git，不能作为长期同步克隆。

## 只做了 fetch / 文件没被跟踪

fetch 不把远程文件放进当前工作区；干净时再 pull --ff-only。
检查文件是否被忽略：git check-ignore -v -- '实际文件路径'。
检查是否被跟踪：git ls-files -- '实际文件路径'。
Git 不记录空目录，缓存、.venv 和被忽略数据也不会自动上传。

## 网页看不到 / 本地 clean

网页刷新，核对账号、仓库和分支；点击最新提交记录比对短编号。
`nothing to commit` 和 `working tree clean` 不表示没有待 push 的提交。
按问题 7 fetch 后检查左右提交数；删除 .git 或强制上传不能修正这些定位问题。
''')
    write('03_另一台电脑拉取与上传/冲突逐行练习.md', r'''# 合并冲突：不要只点“保留当前”

PHM 示例：双方修改同一配置行。以下仅为练习数值，不能直接用于实际设备控制。

```python
<<<<<<< HEAD
sample_rate = 200
=======
sample_rate = 100
>>>>>>> origin/main
```

普通 merge 中，HEAD 一侧通常是当前分支，另一侧是正在合入的分支。
rebase 时标签与直觉可能不同，不要凭 Current/Incoming 名称判断 A/B；核对真实内容和提交。

1. 先问这两处修改分别为什么发生。频率应由数据采集要求决定，Git 不知道哪个参数正确。
2. 打开整段上下文，比较双方实现；可以选一个值，也可以综合成新的实现。
3. 删除冲突标记，保留完整且可运行的代码。不要把两段代码无脑重复粘在一起。
4. 保存，搜索残留标记，检查语法、测试和业务含义。自动合并成功也可能存在逻辑冲突。

```powershell
git status
git diff --check
# 可发现一部分残留冲突标记及空白问题，不代替项目测试。
git add -- '实际冲突文件路径'
git diff --cached
```

然后按**当前操作**完成：

| 冲突来自哪里 | 解决并暂存后的动作 | 放弃当前操作 |
| --- | --- | --- |
| git merge | git commit，再检查与 push | git merge --abort |
| git rebase | git rebase --continue，可能多轮，再检查与 push | git rebase --abort |
| git stash apply | 普通 git commit，原 stash 先保留 | 无 stash --abort；保留 stash，先检查状态 |

上表不是三组连续命令。先 git status 判断自己正在做哪一种操作。
图片、PDF、Word、模型权重等二进制文件一般不能逐行合并；先将两份内容另存，再人工选择或重新生成。
不要在未理解时点 Accept Both，更不要用强推当作解决文件冲突。
''')
    write('03_另一台电脑拉取与上传/功能分支跨电脑交接.md', r'''# 未完成的功能怎样从 A 带到 B

同一个人轮流在两台电脑做同一功能，使用同名功能分支即可。不同并行任务可以建不同分支。
电脑名不决定分支；功能分支也不会自动隔离未提交修改，切分支前先保存。

## A：从最新 main 开始（工作区干净）

```powershell
git switch main
git pull --ff-only
git switch -c feature/phm-reader
# 编辑、保存，再暂存实际文件。
git add -- '实际源码路径'
git diff --cached
git commit -m "WIP: 数据读取功能第一阶段"
git push -u origin feature/phm-reader
```

WIP 表示未完成；可以在功能分支保存阶段进度，但仍需检查不含秘密或不应上传的数据。
这不会把功能自动合并到 main。

## B：第一次接手该功能（工作区干净）

```powershell
git fetch origin
git branch -a
git switch --track origin/feature/phm-reader
# 仅在 B 尚无同名本地分支时使用。
git log -1 --oneline
```

B 已有该分支时：git switch feature/phm-reader，再 git pull --ff-only。
修改后照常 add、检查、commit、push。回 A 时切回该功能分支并 pull --ff-only。

## 完成后用 PR 合并

GitHub → Pull requests → New pull request。
base 选 main，compare 选 feature/phm-reader；查看 Files changed、检查结果，填写说明。
个人仓库也能给自己开 PR，用来记录修改目的与检查过程；不等于必须有其他人审批。
根据仓库规则完成合并后，两台电脑各自 git switch main，再 git pull --ff-only。
旧功能分支可能与 squash/rebase 合并后的 main 历史不同；不要在旧分支上随手 pull main。
新任务从更新后的 main 新建分支。删除旧分支属于可选清理，确认无独有工作再做。
来源：[GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)。
''')
    write('04_常见问题/10_认证网络和权限.md', r'''# 问题 10：认证、网络、权限要分开查

| 提示或现象 | 优先核对 | 处理办法 |
| --- | --- | --- |
| git 不是可识别命令 | Git 安装与 PATH | 安装 Git 后重开终端，用 git --version 检查 |
| Authentication failed | HTTPS 凭据、账号、令牌有效期 | 优先用 GCM 浏览器重新登录；不要用账号密码推送 |
| Permission denied (publickey) | SSH 公钥、agent、使用的账号 | 本机生成密钥并添加公钥；ssh -T git@github.com 核对返回用户名 |
| Repository not found / 403 | 地址、账号、私有仓库授权 | 核对 owner/PHM、当前认证账号和写权限；姓名邮箱不是权限 |
| protected branch / GH013 | 分支规则、PR 或检查要求 | 推到功能分支并创建 PR，按提示完成检查 |
| 连接超时 / Could not resolve host | 本地网络、DNS、代理、服务状态 | 检查浏览器能否访问 GitHub 与 githubstatus.com；保留本地提交稍后重试 |
| large file / secret detected | 文件大小、提交历史中的秘密 | 看问题 11；同步命令不能消除这些拒绝原因 |

只读检查：git remote -v、git branch -vv、git config --show-origin --get-all credential.helper。
截图、日志或向别人求助前隐藏令牌、私人路径与敏感地址。
SSH 首次连接核对 GitHub 官方主机指纹后再接受；不要上传没有 .pub 后缀的私钥。
不要通过关闭 SSL 校验、乱改全局代理、给 PAT 全权限或硬编码令牌解决问题。
需要手工 PAT 时限制目标仓库和有效期，代码写入通常需要 Contents 写权限；组织可能另有限制。

来源：[认证方式](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)、[GCM](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)。
''')
    write('04_常见问题/11_科研数据环境与OneDrive.md', r'''# 问题 11：代码同步了，为何另一台电脑跑不起来？

Git 同步受跟踪的文件与提交，不复制整台电脑。推荐两个独立克隆，通过 GitHub 交接。
当前材料位于 OneDrive 路径；这是路径事实，不代表已经发生同步故障。
为减少 Git 元数据与云盘同步并发写入的风险，建议后续将工作克隆放在 C:Projects 或 D:Projects 等普通本地目录。
本次不移动或删除现有仓库。

## PHM 文件分类建议

| 内容 | 推荐处理 |
| --- | --- |
| .py、配置示例、README、测试 | 纳入 Git；提交有意义的小改动 |
| requirements.txt / pyproject.toml / 项目锁文件 | 按项目实际工具纳入 Git；另一台重建环境 |
| .venv、__pycache__、临时日志 | .gitignore 忽略，不复制虚拟环境 |
| .env、令牌、SSH 私钥 | 本机安全保存；仓库只放无秘密的 .env.example |
| 原始传感器数据、视频、权重 | 按大小与授权单独保存；Git 中记录来源、版本、校验值和获取方法 |
| 小型脱敏测试数据 | 确认可公开/可共享后按需纳入 Git |
| 论文或轨道设施敏感资料 | 先按项目规定处理；私有仓库也不是任意上传授权 |

## Python 环境重建示例

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 仅在项目实际提供 requirements.txt 时用；此命令是说明，不在本次执行。
```

依赖可能要联网下载；按项目实际 Python 版本、锁文件和 README 操作。
相对路径优先，避免把 A 的 D: 数据绝对路径写死到所有人共用的代码。
代码、数据、随机种子与依赖版本都要匹配，才能谈复现实验。

## 大文件与忽略规则

GitHub 浏览器上传单文件上限 25 MiB；常规 Git 仓库阻止超过 100 MiB 的文件，并对超过 50 MiB 的文件警告。
限制与套餐可能变动，以官方链接为准。不要把 LFS 当成无限免费容量；本教程不启用收费服务。
.gitignore 不会移除已跟踪文件。若仅需停止跟踪一个已跟踪但非秘密的文件：

```powershell
git ls-files -- '实际文件路径'
# 确认后才做下一条；--cached 只从暂存索引移除，保留本机文件。
git rm --cached -- '实际文件路径'
# 添加对应 .gitignore 规则，再检查、commit、push。
```

这不删除旧历史中的文件。密钥已提交时先撤销/轮换；大文件在待推送的旧提交里时，单纯新建删除提交仍可能被拒绝。
需要历史清理时先备份并制定迁移方案，不能用强推、重置或删 .git 试错。
来源：[大文件](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。
''')
    write('04_常见问题/12_误操作恢复与撤销.md', r'''# 问题 12：误操作后先保留现场

先停止写入，记录 git status 和最近命令；保留现有目录及重要未提交文件。
不要删 .git，不要使用 reset --hard、clean -fd 或 push -f 碰运气。

## 只是 add 错了

```powershell
git restore --staged -- '实际文件路径'
# 在仓库已有提交的前提下，从暂存区撤回；工作区文件仍保留。
```

## 已 push 的普通提交要撤销

工作区干净、已同步且确认目标后，用新的反向提交保留历史：

```powershell
git log --oneline -10
git show 实际提交编号
git revert 实际提交编号
# 确认编号后逐条执行；冲突按提示解决，再继续或 --abort。
# 这适用于普通提交；合并提交的撤销还需要主线选择，不直接套用。
git push
```

revert 可能影响后续依赖该改动的代码，仍需检查。另一台电脑随后 pull。
revert 不会从旧历史抹掉秘密，泄露凭据必须先撤销或轮换。

## 正在 merge / rebase，但不想继续

git status 判断操作类型；分别用 git merge --abort 或 git rebase --abort。
只运行与当前操作对应的一条。开始操作前工作区干净更有利于安全恢复。

## 提交好像丢了

```powershell
git reflog -15
# 本机引用变动记录，不是跨电脑云日志，也不会永久保留。
git show 实际找到的提交编号
git branch rescue/recovered 实际找到的提交编号
# 确认找到正确提交后建立新分支，避免直接覆盖当前分支。
```

reflog 主要帮助找回已提交版本；从未提交/暂存且无备份的文件，不保证可恢复。
如果 A 独有提交尚未 push，B 的 reflog 一般找不到它。
来源：[revert](https://git-scm.com/docs/git-revert)、[reflog](https://git-scm.com/docs/git-reflog)。
''')
    # 清理现有教程里会让用户误以为已运行自动检查的表述。
    for folder in ('02_第一次上传与推送', '03_另一台电脑拉取与上传'):
        for p in (ROOT/folder).glob('*.md'):
            text = p.read_text(encoding='utf-8')
            text = re.sub(r'下文 (https://github.com/YOUR-USER/PHM.git|git@github.com:YOUR-USER/PHM.git) 替换为 \1。', '下文 YOUR-USER 替换为自己的 GitHub 用户名；仓库不叫 PHM 时也一并替换。', text)
            text = re.sub(r'首次上传命令中 (https://github.com/YOUR-USER/PHM.git|git@github.com:YOUR-USER/PHM.git) 替换成 \1。', '首次上传前，把 YOUR-USER、PHM 和本地目录换成实际值。', text)
            text = text.replace('会检查远程为空、身份、项目根目录和当前分支；失败会停止。', '以上是手动命令示例，不是会自动停止的脚本；请自行核对远程为空、身份、项目根目录和当前分支，报错后停止。')
            p.write_text(text, encoding='utf-8')
    write('05_仓库界面与提交原理/界面与术语速查.md', '''# PHM 仓库页面与提交原理速查

PDF 使用 YOUR-USER/PHM 示意图，不是用户真实页面截图。没有提供仓库 URL，未核实真实分支、权限或设置。
核对日期：2026-10-19；可见项目取决于权限、仓库设置、窗口宽度及 GitHub 更新。

| 页面区域 | 用途 | PHM 中何时使用 |
| --- | --- | --- |
| owner / PHM 与 Public / Private | 账号归属、名称、可见性 | 确认没进错同名仓库；Private 不等于只有自己能访问 |
| Code 标签页 | 文件、分支、README、提交入口 | 日常找源码、看当前分支文件 |
| Issues | 缺陷、任务、讨论条目 | 记录“传感器 CSV 解析报错” |
| Pull requests | 比较分支、讨论、检查和合并请求 | 合并 feature 到 main；与 git pull 是两回事 |
| Actions | 工作流运行和日志 | 查看已经配置的测试/构建；红叉不等于 push 失败 |
| Projects | 任务看板或表格 | 按“待做/进行中/完成”组织研究任务 |
| Wiki / Discussions（可选） | 长文知识库 / 主题讨论 | 开启后才出现，未开启无需寻找 |
| Security | 安全策略、漏洞和秘密相关功能 | 可用功能因权限、可见性及套餐而异 |
| Insights | 贡献、提交、活动等统计 | 看项目活动；统计不代表实验质量 |
| Settings | 仓库配置、访问、分支规则等 | 管理者才可见部分或全部；删除等操作另行审慎处理 |
| Watch / Star / Fork | 通知 / 收藏 / 自己名下的派生仓库 | 双机同步不需要 fork |
| 分支下拉、branches / tags | 当前分支及版本标记 | A 推到 feature，网页需选同一分支查看 |
| Go to file / 搜索、文件列表 | 找文件、浏览目录 | 点文件看内容、History 或 Blame |
| Add file | 网页新建或上传 | 网页 commit 也会产生远程新提交，本机随后要 pull |
| 绿色 Code 按钮 | HTTPS/SSH 地址、工具入口、ZIP 等 | clone 用复制的地址；ZIP 不是完整 Git 克隆 |
| 最新提交、提交短编号、历史入口 | 当前目录最近提交与分支历史 | 列表行里的提交是影响该路径的最近记录，不一定每行都相同 |
| README / About | 使用说明 / 描述、主题、链接 | 先看环境、运行方式和数据说明 |
| Releases / Tags / Packages | 发布说明与资产 / 提交标记 / 软件包 | tag 不等于 Release；源码 ZIP 不一定含外部数据与 LFS 实体 |
| Contributors / Languages / Deployments（若有） | 贡献者、语言估计和部署状态 | 依内容与设置显示；语言占比不代表贡献工作量 |

## 提交是怎样形成的

保存文件 → 工作区；git add → 把所选内容放进暂存区；git commit → 用暂存区形成本地快照与提交；
git push → 向远程发送需要的 Git 对象并请求更新分支引用。
push 不自动提交文件，不保证运行测试或部署；网页编辑提交则直接在 GitHub 形成提交。
在 add 之后再次编辑文件，commit 默认只收录已经暂存的那版；需要再次 add 才包含后续修改。

提交对象记录根 tree、父提交（首次提交无父，普通提交通常一个父，合并可有多个）、作者/提交者与说明；
tree 关联目录与文件对象。Git 逻辑上以快照表示版本，并复用相同内容；底层还可能压缩存储。
commit ID 由对象内容决定，不是文件名、日期或顺序号。分支是可移动的提交引用；HEAD 通常指当前分支。

origin 是本地远程别名；origin/main 是最近 fetch 掌握的远程 main 状态，不是实时云端；
本地 main、origin/main、GitHub main 是三处需区分的引用。
fetch 更新信息但通常不动当前工作区；pull = fetch + 整合到当前分支；--ff-only 分叉时停止。

术语表：[打印速查 HTML](../reference/github-cheatsheet.html)；完整讲解：[PDF](../output/pdf/GitHub_PHM_双机协作与仓库图解.pdf)。
来源索引：[官方资料](../官方资料.md)。
''')
    write('MISSION.md', '''# Mission: 用 GitHub 交接两台电脑上的 PHM 代码

## Why
用户需要在两台电脑轮流修改同一仓库，能可靠拉取、提交、推送并处理冲突，同时看懂 GitHub 仓库页面。

## Success looks like
- 能从 A 提交并推送，再在 B 拉取同一分支、核对提交编号后继续工作。
- 能区分保存、add、commit、push，以及 fetch、pull 与 Pull Request。
- 遇到分叉或未提交修改时能选择对应步骤，不覆盖另一台电脑的工作。

## Constraints
- 简体中文、面向初学者；保留现有分类，以 PowerShell 示例为主。
- 第三方预算 0 元；本次只创建本地学习资料，不替用户上传或改账户设置。
- 尚未提供真实 GitHub 仓库地址；页面使用明确标注的 PHM 示意图。
''')
    old = (ROOT/'官方资料.md').read_text(encoding='utf-8')
    extra = '\n\n## 本次专题核对与来源编号\n\n核对日期：2026-10-19。PDF 中的 S 编号对应下列官方来源。\n\n'
    extra += '\n'.join(f'- **{sid}** [{title}]({url})' for sid,title,url in SOURCES)
    write('官方资料.md', old.split('## 本次专题核对与来源编号')[0].rstrip()+extra)
    write('RESOURCES.md', '# GitHub 双机协作 Resources\n\n## Knowledge\n\n'+ '\n'.join(f'- [{title}]({url})\n  用于：{title}；PDF 来源编号 {sid}。' for sid,title,url in SOURCES) + '\n\n## Gaps\n\n尚未提供真实 PHM 页面与项目运行说明，无法核实账户权限、实际界面布局及项目测试命令。\n')
    write('assets/learning.css', '''*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#183049;font:17px/1.85 "Microsoft YaHei",sans-serif}main{max-width:980px;margin:40px auto;padding:44px;background:white;border-radius:20px}h1{font-size:36px;line-height:1.35}h2{color:#007f80}a{color:#007f80}pre{background:#132b43;color:#edf8fa;padding:22px;border-radius:12px;white-space:pre-wrap;font-size:15px}aside{border-left:5px solid #eaa758;padding:14px 22px;background:#fff5e7}button{background:#007f80;color:white;border:0;border-radius:8px;padding:10px 18px;cursor:pointer}details{padding:18px;border:1px solid #d9e3eb;margin:12px 0;border-radius:10px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd}@media print{body{background:white}main{margin:0;padding:0}button{display:none}}''')
    write('assets/quiz.js', '''document.querySelectorAll('[data-answer]').forEach(q=>q.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{q.querySelector('output').textContent=b.dataset.value===q.dataset.answer?'正确：commit 只在本地，push 后另一台电脑才能从 GitHub 拉到。':'再想一想：保存、暂存和本地提交都不会自动传到 GitHub。';})));''')
    write('lessons/0001-two-computers.html', '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>一课学会双机交接</title><link rel="stylesheet" href="../assets/learning.css"><main><p>PHM · 10 分钟短课</p><h1>把 A 的一次改动交给 B</h1><p>目标：能说清修改在哪一步离开 A，并用提交编号核对 B 是否拿到同一版本。</p><aside>以下为练习指导，不会自动操作仓库。先在练习仓库使用，所有命令报错后停止。</aside><h2>先记住四步</h2><pre>保存 → git add → git commit → git push</pre><p>前面三步都发生在 A。push 成功后，B 才能从 GitHub 拉取。网页要选择同一分支。</p><h2>用一次小改动练习</h2><ol><li>在 A 确认分支和干净工作区，pull --ff-only。</li><li>在已有练习 README 添加一行双机交接说明，保存、暂存、检查并 commit。</li><li>先停下来查看网页：此时没有新提交是正常的。</li><li>push 后刷新网页，记录最新短编号。</li><li>在 B 确认同仓库、同分支、干净工作区，pull --ff-only；核对 git log -1 --oneline。</li></ol><div data-answer="push"><h2>立即自测</h2><p>A 已 commit，B 何时能从 GitHub 获取这次改动？</p><button data-value="save">保存之后</button> <button data-value="add">暂存之后</button> <button data-value="push">推送之后</button><p><output aria-live="polite"></output></p></div><h2>过两天再回忆</h2><p>不看上文，说出“开工”和“收工”的动作，以及 clean 为什么不等于上传成功。</p><p>主参考：<a href="https://docs.github.com/en/desktop/working-with-your-remote-repository-on-github-or-github-enterprise/syncing-your-branch-in-github-desktop">GitHub 官方同步说明</a>。</p><p><a href="../reference/github-cheatsheet.html">打印速查</a> · <a href="../03_另一台电脑拉取与上传/00_双机同步先看这篇.md">完整步骤</a> · <a href="../output/pdf/GitHub_PHM_双机协作与仓库图解.pdf">图解 PDF</a></p><p>遇到不清楚的步骤可继续问我；提供脱敏后的 git status 和错误原文即可。此课未记录为“已掌握”，需要实际练习反馈。</p></main><script src="../assets/quiz.js"></script></html>''')
    write('reference/github-cheatsheet.html', '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>GitHub 双机速查</title><link rel="stylesheet" href="../assets/learning.css"><main><p>PHM · 打印参考</p><h1>开工先拉，收工先交接</h1><h2>开工 / 工作区干净且在目标分支</h2><pre>git branch --show-current\ngit status\ngit pull --ff-only</pre><h2>收工 / 保存并检查</h2><pre>git add -- '实际文件路径'\ngit diff --cached\ngit commit -m "说明本次修改"\ngit push\ngit log -1 --oneline</pre><p>网页同一分支核对提交短编号；报错就停。新分支第一次推送需 git push -u origin 分支名。</p><h2>术语表</h2><table><tr><th>术语</th><th>含义</th></tr><tr><td>Git / GitHub</td><td>本地版本工具 / 远程托管平台</td></tr><tr><td>工作区 / 暂存区</td><td>正在编辑的文件 / 准备提交的内容</td></tr><tr><td>commit / push</td><td>形成本地提交 / 上传提交并更新远程引用</td></tr><tr><td>clone / fetch / pull</td><td>首次克隆 / 获取远程信息 / 获取并整合进当前分支</td></tr><tr><td>origin / main / HEAD</td><td>远程别名 / 分支示例名 / 当前检出的引用</td></tr><tr><td>origin/main</td><td>本机最近 fetch 掌握的远程 main 位置</td></tr><tr><td>stash</td><td>仅本机的临时保存，不随 push 上传</td></tr><tr><td>Pull Request</td><td>请求合并分支，不等于 git pull</td></tr></table><p><a href="../lessons/0001-two-computers.html">返回短课</a> · <a href="../官方资料.md">官方资料</a> · <a href="https://git-scm.com/docs/git-pull">git pull 文档</a></p></main></html>''')
    oldread = (ROOT/'README.md').read_text(encoding='utf-8')
    marker = '## 文件导航' if '## 文件导航' in oldread else '### 首次上传与原有问题'
    oldnav = oldread[oldread.index(marker):].replace('## 文件导航','### 首次上传与原有问题')
    write('README.md', '''# GitHub / PHM 双机协作学习包

重点解决两台电脑轮流修改同一仓库：拉取、提交、推送、交接、分叉与冲突。
教程为人工执行的步骤，命令示例不等于本次已执行；遇到错误先停止。

## 从这里开始

1. **[双机同步完整步骤](03_另一台电脑拉取与上传/00_双机同步先看这篇.md)**：B 首次克隆，A→B→A 每日交接。
2. **[每日交接清单](03_另一台电脑拉取与上传/每日交接清单.md)**：操作时照着核对。
3. **[精美图解 PDF](output/pdf/GitHub_PHM_双机协作与仓库图解.pdf)**：仓库界面、提交原理、双机步骤与排错。
4. [10 分钟交互短课](lessons/0001-two-computers.html) 与 [可打印速查](reference/github-cheatsheet.html)。HTML 用浏览器打开。

## 分类导航

| 分类 | 内容 |
| --- | --- |
| 00_原始材料 | 两份原始 TXT 与修订说明 |
| 01_首次创建仓库 | 账号、Git、作者信息、空仓库、忽略规则 |
| 02_第一次上传与推送 | A 网页 / B Desktop / C HTTPS / D SSH；E 分支操作 |
| 03_另一台电脑拉取与上传 | 各方式、双机完整流程、每日清单、冲突练习、功能分支交接 |
| 04_常见问题 | 原有 1-6，加双边提交、stash、忘记 push、认证、科研环境、误操作恢复 |
| 05_仓库界面与提交原理 | 网页按钮与术语说明 |
| output/pdf | 最终 PDF |
| assets / lessons / reference | 短课样式、练习与速查 HTML |

### 遇到问题直接点

- [两边都提交了 / push 被拒绝](04_常见问题/7_两台电脑都提交了.md)
- [本地没 commit，怎么拉取](04_常见问题/8_未提交修改与stash.md)
- [另一台看不到更新 / 忘记 push](04_常见问题/9_更新不见了与忘记推送.md)
- [merge / rebase / stash 冲突逐行处理](03_另一台电脑拉取与上传/冲突逐行练习.md)
- [未完成功能跨电脑交接](03_另一台电脑拉取与上传/功能分支跨电脑交接.md)
- [认证、网络和权限](04_常见问题/10_认证网络和权限.md)
- [数据、环境、大文件和 OneDrive](04_常见问题/11_科研数据环境与OneDrive.md)
- [误操作恢复](04_常见问题/12_误操作恢复与撤销.md)
- [仓库页面与提交原理速查](05_仓库界面与提交原理/界面与术语速查.md)

## 使用边界与验证

日期：2026-10-19。未提供真实 PHM GitHub URL，PDF 中的 YOUR-USER/PHM 是明确标注的界面示意。
没有修改账户、仓库设置、密钥或 Git 配置，也没有执行实际推送、移动仓库或清理历史。
本机 PHM 仓库的 Git 元数据读取受当前环境限制，无法据此确认实际分支与远程地址；示例 main 必须按实际情况替换。
来源与核对范围见 [官方资料](官方资料.md)；生成源码为 build_github_guide.py。
PDF 已进行文本、分页与渲染核对；教程的双机核心流程另在隔离的本地演示仓库验证，结果见 [验证记录](验证记录.md)。

---

## 原有基础教程导航

''' + oldnav)

pdfmetrics.registerFont(TTFont('YaHei', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('YaHeiB', 'C:/Windows/Fonts/msyhbd.ttc', subfontIndex=0))
pdfmetrics.registerFontFamily('YaHei',normal='YaHei',bold='YaHeiB',italic='YaHei',boldItalic='YaHeiB')
W,H=A4
NAVY=colors.HexColor('#142D46'); TEAL=colors.HexColor('#007F83'); GOLD=colors.HexColor('#E8AC63')
INK=colors.HexColor('#233B50'); MUTED=colors.HexColor('#667D8E'); LIGHT=colors.HexColor('#EEF4F7'); LINE=colors.HexColor('#D7E3EA')
OUT=ROOT/'output/pdf/GitHub_PHM_双机协作与仓库图解.pdf'
OUT.parent.mkdir(parents=True,exist_ok=True)
C=None
Y=0
PAGE=0
AUDIT=[]
def para(text,x,y,width,size=10.5,leading=18,color=INK,bold=False):
    style=ParagraphStyle('body',fontName='YaHeiB' if bold else 'YaHei',fontSize=size,leading=leading,textColor=color,wordWrap='CJK',splitLongWords=True)
    p=Paragraph(text,style); _,height=p.wrap(width,1000)
    if y-height<55: raise ValueError(f'Page {PAGE} overflow {text[:35]} bottom {y-height}')
    p.drawOn(C,x,y-height)
    AUDIT.append({'page':PAGE,'bottom':round(y-height,2),'text':re.sub('<[^>]+>','',text)[:70]})
    return y-height
def p(text,gap=10):
    global Y
    Y=para(text,44,Y,W-88)-gap
def title(s):
    global Y
    Y=para(s,44,Y,W-88,15,24,TEAL,True)-9
def box(label,text,tone='teal'):
    global Y
    col=TEAL if tone=='teal' else GOLD
    ps=ParagraphStyle('card',fontName='YaHei',fontSize=10.4,leading=18,textColor=INK,wordWrap='CJK')
    q=Paragraph(text,ps); _,h=q.wrap(W-124,1000); h+=54
    if Y-h<60: raise ValueError(f'box overflow page {PAGE}')
    C.setFillColor(LIGHT if tone=='teal' else colors.HexColor('#FFF5E8')); C.roundRect(44,Y-h,W-88,h,8,fill=1,stroke=0)
    C.setFillColor(col); C.rect(44,Y-h,4,h,fill=1,stroke=0)
    para(label,60,Y-12,W-120,10.6,17,col,True)
    q.drawOn(C,60,Y-38-(h-54)); Y-=h+14
def code(lines):
    global Y
    if isinstance(lines,str): lines=lines.strip().splitlines()
    h=len(lines)*17+24
    if Y-h<60: raise ValueError(f'code overflow page {PAGE}')
    C.setFillColor(NAVY); C.roundRect(44,Y-h,W-88,h,8,fill=1,stroke=0)
    for i,s in enumerate(lines):
        size=9.1
        if pdfmetrics.stringWidth(s,'YaHei',size)>W-118: raise ValueError('code too wide '+s)
        C.setFont('YaHei',size); C.setFillColor(colors.HexColor('#C8F1ED') if s.lstrip().startswith('#') else colors.white)
        C.drawString(59,Y-22-i*17,s)
    Y-=h+14
def rows(data,widths=None,size=10.0):
    global Y
    widths=widths or [140,W-228]
    for i,(a,b) in enumerate(data):
        pa=ParagraphStyle('a',fontName='YaHeiB',fontSize=size,leading=16,textColor=TEAL,wordWrap='CJK')
        pb=ParagraphStyle('b',fontName='YaHei',fontSize=size,leading=16,textColor=INK,wordWrap='CJK')
        qa,qb=Paragraph(a,pa),Paragraph(b,pb)
        ha=qa.wrap(widths[0]-20,1000)[1]; hb=qb.wrap(widths[1]-20,1000)[1]; h=max(ha,hb)+18
        if Y-h<65: raise ValueError(f'row overflow {PAGE}: {a}')
        C.setFillColor(LIGHT if i%2==0 else colors.white); C.rect(44,Y-h,W-88,h,fill=1,stroke=0)
        qa.drawOn(C,54,Y-9-ha); qb.drawOn(C,54+widths[0],Y-9-hb)
        Y-=h
    Y-=14
def start(kicker,heading,sub='',sources=''):
    global Y,PAGE
    if PAGE: C.showPage()
    PAGE+=1
    C.setFillColor(colors.white); C.rect(0,0,W,H,fill=1,stroke=0)
    C.setFillColor(TEAL); C.rect(0,H-9,W,9,fill=1,stroke=0)
    C.setFont('YaHeiB',9); C.setFillColor(TEAL); C.drawString(44,H-41,kicker)
    C.setFont('YaHeiB',23); C.setFillColor(NAVY); C.drawString(44,H-82,heading)
    Y=H-104
    if sub: Y=para(sub,44,Y,W-88,10,16,MUTED)-14
    if sources: Y=para('依据：'+sources+'  |  完整链接见文末',44,Y,W-88,8,13,MUTED)-14
    C.setStrokeColor(LINE); C.line(44,43,W-44,43)
    C.setFont('YaHei',8); C.setFillColor(MUTED); C.drawString(44,28,'PHM · GitHub 学习手册   /   2026-10-19')
    C.drawRightString(W-44,28,f'{PAGE:02d}')
    C.bookmarkPage(f'p{PAGE}'); C.addOutlineEntry(heading,f'p{PAGE}',0)

def flow(nodes):
    global Y
    n=len(nodes); gap=14; bw=(W-88-(n-1)*gap)/n; top=Y
    for i,(a,b) in enumerate(nodes):
        x=44+i*(bw+gap); C.setFillColor(LIGHT); C.roundRect(x,top-95,bw,95,8,fill=1,stroke=0)
        para(a,x+10,top-12,bw-20,12,19,TEAL,True)
        para(b,x+10,top-42,bw-20,9.3,15)
        if i<n-1:
            C.setStrokeColor(TEAL); C.line(x+bw+2,top-47,x+bw+gap-2,top-47)
            C.line(x+bw+gap-5,top-44,x+bw+gap-2,top-47); C.line(x+bw+gap-5,top-50,x+bw+gap-2,top-47)
    Y=top-115

def mock():
    global Y
    top=Y; left=44; width=W-88
    C.setFillColor(LIGHT); C.roundRect(left,top-302,width,302,10,fill=1,stroke=0)
    def t(s,x,dy,size=9,col=INK,b=False):
        C.setFillColor(col);C.setFont('YaHeiB' if b else 'YaHei',size);C.drawString(x,top-dy,s)
    t('①  YOUR-USER / PHM     Private',58,27,12,NAVY,True)
    t('Watch    Star    Fork  ②',365,27,8)
    t('③ Code   Issues   Pull requests   Actions   Projects   Security   Insights   Settings',58,58,8)
    C.setStrokeColor(LINE); C.line(57,top-73,W-58,top-73)
    t('④ main ▼   branches   tags',58,96,9,TEAL,True)
    t('Go to file    Add file',278,96,8)
    C.setFillColor(TEAL);C.roundRect(432,top-106,103,24,5,fill=1,stroke=0)
    t('⑤  Code ▼',449,98,9,colors.white,True)
    t('⑥ 最新提交说明     a1b2c3d     History / commits',58,130,9)
    t('⑦ src/                  修复数据读取',58,161,9)
    t('    tests/                增加样例检查',58,185,9)
    t('    README.md        更新使用说明',58,209,9)
    t('⑧ README：安装、运行、数据说明',58,250,10,TEAL,True)
    t('⑨ About / Releases / Contributors / Languages',58,280,9)
    Y=top-321

def pdf():
    global C,Y
    C=canvas.Canvas(str(OUT),pagesize=A4,pageCompression=1)
    C.setTitle('GitHub PHM：仓库界面、提交原理与双机协作')
    C.setAuthor('PHM 学习资料'); C.setSubject('中文初学者图解；双机拉取、提交、推送和冲突恢复')
    start('FIELD GUIDE / 01','让两台电脑接上同一份工作','GitHub 仓库界面、提交原理与 PHM 双机协作')
    C.setFillColor(NAVY); C.roundRect(44,Y-215,W-88,215,13,fill=1,stroke=0)
    para('开工先拉取<br/>收工先提交，再推送',65,Y-28,W-130,25,40,colors.white,True)
    para('A 电脑 → GitHub / PHM → B 电脑<br/>每台电脑独立克隆，通过同一分支交接。',65,Y-135,W-130,12,23,colors.HexColor('#C6E8E8'))
    Y-=242
    title('按你现在的问题阅读')
    rows([('看懂页面','第 2-4 页：标签、按钮、文件和历史入口。'),('理解提交','第 5-6 页：工作区、暂存区、提交图与分支引用。'),('两台电脑接力','第 7-9 页：首次准备、日常命令、Desktop 操作。'),('出错后怎么办','第 10-16 页：分叉、冲突、stash、分支、恢复与环境。'),('随手查阅','第 17 页交接卡；第 18-19 页官方来源。')],size=10)
    p('适用：个人研究代码仓库。示例使用 main 与 YOUR-USER/PHM，实际名称请自行核对。界面为重绘示意，不是已登录账号的真实截图。',gap=0)

    start('INTERFACE / 02','先认出这九个区域','PHM 仓库首页示意；布局压缩显示，侧栏内容在此放到图底部。','S01 / S02')
    mock()
    rows([('① 仓库身份','owner、PHM、可见性：先确认账号、仓库和是否公开。'),('② 关注工具','Watch 管通知；Star 收藏；Fork 另建派生仓库。'),('③ 功能标签','Code 看文件；其他标签按任务使用，部分可能隐藏。'),('④ 当前分支','决定网页显示哪条分支；tags 是标记版本的入口。'),('⑤ 绿色 Code','复制 clone 地址、工具入口、Download ZIP 等。'),('⑥ 提交入口','查看提交说明、短编号与历史；入口随页面变化。'),('⑦ 文件列表','进入目录和文件；每行可显示影响该路径的最近提交。'),('⑧ / ⑨ 文档与侧栏','README 讲怎么用；About、Releases 等讲项目与版本。')],widths=[115,W-203],size=9.5)

    start('INTERFACE / 03','顶部标签：什么时候点哪个','先用 Code、Issues、Pull requests，其他随项目需要启用。','S01 / S09 / S12 / S13')
    rows([('Code','项目文件、分支、README、历史。日常查看 PHM 源码从这里开始。'),('Issues','记录缺陷、需求与任务。例如“CSV 读取时出现空值”。'),('Pull requests','比较分支、说明改动、看检查结果、请求合并。PR 和 git pull 是不同的操作。'),('Actions','已配置工作流的运行结果与日志。红叉可能是测试失败，不等于 push 失败。'),('Projects','看板或表格管理任务，例如待做、进行中、已完成。'),('Wiki / Discussions','可选的长文知识库与主题讨论区，未开启就可能不显示。'),('Security','安全策略、依赖或秘密相关功能；具体能力取决于权限、仓库与套餐。'),('Insights','贡献、提交和活动统计。统计量不能证明代码或实验质量。'),('Settings','配置、访问权限、规则等。只有拥有相应权限的人能看到对应选项。')],size=10)
    box('个人仓库也可以用 PR','自己提交、自己检查、自己合并，也能留下清楚的改动理由。是否需要审批、是否能直接 push，由仓库规则决定。')

    start('INTERFACE / 04','文件页与右侧栏怎么用','Code 标签页与绿色 Code 按钮同名，但作用不同。','S02 / S11 / S16')
    rows([('分支下拉','A 推到了 feature 分支，网页选 main 就看不到那份改动。先核对分支。'),('Go to file / 搜索','按文件名或代码搜索定位；进入目录后面包屑可返回上层。'),('Add file','网页创建或上传文件，并在 GitHub 形成提交；本机之后也需要 pull。'),('绿色 Code 按钮','HTTPS / SSH 地址用于 clone。ZIP 只有该版本的源码快照，没有完整 .git 历史。'),('文件内容与历史','History 看该文件的修改记录；Blame 定位代码行关联的提交。Raw 看原始内容。'),('提交短编号','点击进入改动明细；用它核对“这次修改是否已到网页与 B 电脑”。'),('README / About','README 说明安装运行；About 放项目摘要、主题和相关链接。'),('Releases / Tags','Tag 指向版本提交；Release 额外提供版本说明和可下载资产，二者不相同。'),('Packages / 其他侧栏','软件包、贡献者、语言、部署等按内容和设置显示。语言比例不代表工作量。')],size=10)
    p('Private 代表受访问控制，仍可能有协作者或获授权应用。源码归档也不保证包含外部数据和所有 LFS 实体。',gap=0)

    start('MENTAL MODEL / 05','提交不是上传','先理解一次修改在哪个位置，再记命令。','S05 / S06 / S20')
    flow([('工作区','编辑器里保存后的文件'),('暂存区','git add 选入本次提交'),('本地仓库','git commit 形成版本'),('GitHub','git push 上传并更新分支')])
    title('add 之后再改文件，会发生什么？')
    p('例如 README 原来写“采样 100”。你改成“采样 200”并执行 add，再改成“采样 300”。此时 commit 默认记录的是已暂存的“采样 200”。要把 300 纳入提交，需要再次 add。')
    code(['git diff                 # 看未暂存差异','git add -- README.md     # 暂存这个文件','git diff --cached        # 看本次实际要提交的内容','git commit -m "更新说明"  # 只在本机形成提交','git push                 # 上传已有提交'])
    box('提交对象记录什么','根目录 tree、父提交、作者与提交者信息、提交说明等。tree 关联文件与目录对象。Git 逻辑上记录项目快照，并复用相同内容；底层还会压缩存储。')
    p('提交编号来自对象内容，不是文件名或时间序号。首次提交没有父提交，普通提交通常一个父提交，合并提交可有多个父提交。push 不会自动保存编辑器文件、自动 commit、测试或部署。')

    start('MENTAL MODEL / 06','main、origin/main 与 HEAD','三个位置需要分清：本地分支、远程跟踪引用、服务器上的分支。','S04 / S05 / S06')
    flow([('本地 main','本机分支，指向一个提交'),('origin/main','最近 fetch 掌握的远程位置'),('GitHub main','服务器实际分支，可被 A 或 B 更新')])
    rows([('origin','通常是远程仓库别名；不是分支，也不是 GitHub 固定保留字。'),('HEAD','通常指向当前分支；切换分支会改变当前检出的代码。'),('fetch','获取对象与远程引用信息，通常不改变当前工作区。'),('pull','先 fetch，再整合到当前分支；不是单纯下载文件。'),('--ff-only','只允许快进更新；分叉时停止，让你先判断如何整合。'),('push','把本地提交发给远程，并请求更新相应分支引用。')],size=10.3)
    code(['C0 --- C1 --- C2','       main     GitHub main','git pull --ff-only','C0 --- C1 --- C2','                main / HEAD'])
    p('上图表示快进：本地没有独有提交，只需把 main 前移。origin/main 离线时可能过期；先 fetch 再用它判断进度。')

    start('SETUP / 07','两台电脑第一次怎么准备','同一账号、同一仓库、两份独立克隆；路径可以不同。','S10 / S17 / S19')
    title('选一条路线，保持简单')
    rows([('想少用命令','GitHub Desktop 登录账号 → Clone repository → 选本地目录。'),('愿意学命令','HTTPS + Git Credential Manager，在浏览器认证；不必先手工创建 PAT。'),('已有 SSH 习惯','每台电脑生成自己的密钥，只把公钥加到账号，不复制私钥。')],size=10.5)
    code(['git --version','git config --global user.name "你的提交显示名"','git config --global user.email "你的提交邮箱"','# 在已有父目录运行；替换 YOUR-USER','git clone https://github.com/YOUR-USER/PHM.git PHM',r'Set-Location -LiteralPath .\PHM','git remote -v','git branch -vv'])
    box('新电脑 clone，已有克隆 pull','clone 会建立本地仓库、origin 和默认检出分支的跟踪关系。已经 clone 的目录不必再 init。已有同名文件夹时，先保留它，克隆到新目录再比较复制源码，不覆盖 .git。')
    p('作者姓名与邮箱不等于登录权限。可用 GitHub 实际提供的 noreply 邮箱。HTTPS、SSH 只是认证与传输选择，不改变 add、commit、pull、push 的核心含义。')

    start('TWO COMPUTERS / 08','A → GitHub → B：每天照着做','本页前提：当前是目标分支、工作区干净、已配置上游；每段报错就停。','S04 / S20')
    title('01  A 开工：确认位置，拉取后再编辑')
    code(['git rev-parse --show-toplevel','git branch --show-current','git status','git pull --ff-only'])
    title('02  A 收工：保存、检查、提交、推送')
    code(['git status','git diff','git add -- "实际要提交的文件路径"','git diff --cached','git commit -m "修复传感器数据读取"','git push','git log -1 --oneline'])
    title('03  B 接手：同一分支拉取，核对提交编号')
    code(['git branch --show-current','git status','git pull --ff-only','git log -1 --oneline'])
    p('网页选中相同分支确认 A 的提交已出现；B 核对短编号后再编辑。B 收工同样 commit + push，返回 A 同样先 pull。新分支首次 push 需要 -u origin 分支名。')
    box('clean 不等于已上传','working tree clean 只表示没有未提交修改；本地仍可能领先远程。必须确认 push 成功，以及网页同分支出现这次提交。',tone='gold')

    start('TWO COMPUTERS / 09','不用命令：Desktop 双机操作','把 A、B 当作两个独立客户端；两边都要同步。','S03 / S20')
    rows([('首次 B 接入','File → Clone repository，选择 PHM，选保存目录，Clone。'),('开工看哪一份','Current Repository 选 PHM；Current Branch 选要接手的分支。'),('获取更新','先 Fetch origin；有远程更新时再 Pull origin。Fetch 本身不会把代码整合到工作区。'),('查看这次修改','保存代码后返回 Desktop，在 Changes 中看差异，勾选需要提交的文件。'),('形成本地版本','填写 Summary，点击 Commit to 当前分支。此时还没有上传。'),('上传交接','点击 Push origin，确认成功；必要时从网页核对分支与提交。'),('处理分叉','如果提示拉取、冲突或 rebase，读清提示，按正在进行的操作完成；不要盲点重试。'),('回另一台电脑','选择相同仓库与分支，再 Fetch 和 Pull，确认新提交出现在 History。')],size=10.5)
    box('按钮随状态改变','Fetch origin、Pull origin、Push origin 会随状态显示。受保护分支可能要求走 PR。不同版本按钮位置会变，按标签和提示识别即可。')
    p('命令行与 Desktop 操作的是同一份克隆时，看到的是同一套 Git 历史。不要在两个不同的 PHM 文件夹来回操作，却以为它们会自行同步。')

    start('DIVERGENCE / 10','两台电脑都 commit 了怎么办','push 拒绝通常是在保护远程独有提交；先判断，再合并。','S04 / S07')
    code(['git status               # 先处理未提交修改','git branch backup/b-before-sync','# 备份名要唯一；它只保护当前已提交历史','git fetch origin','git rev-list --left-right --count "HEAD...@{upstream}"'])
    rows([('0 / 0','同步；仍需另外查看是否存在未提交文件。'),('0 / 正数','本地落后，用 pull --ff-only。'),('正数 / 0','本地领先，检查后 push。'),('正数 / 正数','分叉，不能快进，下面二选一。')],widths=[110,W-198],size=10)
    title('默认：merge 保留双方提交')
    code(['git merge origin/main','# 若无冲突，检查后 git push','# 有冲突见下一页；合并成功后不再机械执行 rebase'])
    p('前提：当前确实在 main、刚完成 fetch，工作区干净且没有其他进行中的操作。已经共享的提交优先保持历史稳定；备份分支不包含未提交文件。')
    box('可选：未发布的本地提交才考虑 rebase','若只是本地尚未推送的普通提交，可另选 git rebase origin/main，让它接在远程提交之后。会产生新编号；不要随意 rebase 已共享历史。正常完成后再 push，无需强推。',tone='gold')

    start('CONFLICTS / 11','冲突不是二选一按钮题','示例数值只用于教学，真实参数要按项目需求判断。','S04 / S07 / S08')
    code(['<<<<<<< HEAD','sample_rate = 200','=======','sample_rate = 100','>>>>>>> origin/main'])
    p('Git 只能发现部分文本冲突，不知道采样率应该多少。先读上下文与双方改动目的，保留正确实现并删掉冲突标记。rebase 时 Current / Incoming 的含义容易误判，应以实际内容为准。')
    code(['git status','git diff --check','git add -- "实际冲突文件路径"','git diff --cached'])
    rows([('merge 冲突','所有冲突解决并暂存后 git commit；检查后 push。放弃本次操作：git merge --abort。'),('rebase 冲突','git rebase --continue，可能重复多轮；全部完成后检查并 push。放弃：git rebase --abort。'),('stash apply 冲突','解决、暂存后作为普通修改 commit。没有 stash --continue，也不运行 rebase --continue。')],size=10.3)
    box('自动合并成功也要检查','双方改不同代码段，仍可能产生逻辑不兼容。按项目说明检查和测试。PDF、图片、模型等二进制文件需保留两份后人工选择或重新生成。')

    start('LOCAL CHANGES / 12','没 commit，想先拉取怎么办','先保存当前工作；stash 是本地抽屉，功能分支才适合跨电脑交接。','S08 / S09')
    title('临时挪开修改：stash')
    code(['git status','git stash push -u -m "同步前暂存"','git stash list','git pull --ff-only','# pull 成功后，确认要恢复的记录','git stash show --stat "stash@{0}"','git stash apply "stash@{0}"','git status'])
    p('-u 包含未跟踪文件，不包括被忽略文件。apply 保留 stash 记录，恢复时可能冲突。pull 失败就先停止，处理分叉等问题后再恢复；不要反复 apply。')
    box('恢复完再考虑清理','解决冲突、检查并提交或完成其他备份后，才可按需 git stash drop 对应记录。stash 不随普通 push 上传，B 无法从 GitHub 拉到 A 的 stash。',tone='gold')
    title('要带到 B 的未完成工作：功能分支')
    p('在适当功能分支保存阶段进度并 commit + push，B fetch 后跟踪同名分支。WIP 可以标记未完成状态，但仍要确认不含秘密与不应上传的数据。')
    p('若 A 离线，先在本地 commit，联网再 push；若 A 无法访问且没有备份，GitHub 无法凭空恢复未上传内容。')

    start('BRANCH HANDOFF / 13','同一个功能，换电脑接着做','不必按电脑名分支；按功能分支，同一任务在 A、B 轮流推进。','S09')
    title('A：从更新后的 main 创建功能分支')
    code(['git switch main','git pull --ff-only','git switch -c feature/phm-reader','# 编辑、暂存、检查后','git commit -m "WIP: 数据读取第一阶段"','git push -u origin feature/phm-reader'])
    title('B：第一次接手这个远程分支')
    code(['git fetch origin','git branch -a','git switch --track origin/feature/phm-reader','# 仅当 B 尚无同名本地分支时使用'])
    p('若 B 已有该本地分支：先 switch 到它，再 pull --ff-only。完成修改后正常 add、commit、push。回 A 也先在这个分支 pull。切换前先处理未提交修改。')
    box('功能完成：用 PR 合并到 main','Pull requests → New pull request。base 选 main，compare 选 feature/phm-reader；看差异与检查后按规则合并。两台电脑各自切回 main 并 pull。')
    p('PR 不会自动下载到本机。若以 squash 或 rebase 方式合并，旧分支历史可能不同；下一项任务从最新 main 新建分支，不在旧功能分支继续混用。')

    start('DIAGNOSIS / 14','“更新不见了”按这个顺序查','越先确认仓库和分支，越少走弯路。','S03 / S10 / S17')
    rows([('A 只保存 / 只 commit','在 A 看 status 和 log；完成 push，网页确认后 B 再 pull。'),('B 只 fetch','fetch 只获取远程信息；工作区干净时再 pull --ff-only。'),('网页与本地分支不同','branch --show-current、branch -vv 核对；网页下拉选同一分支。'),('编辑器打开错目录','rev-parse --show-toplevel 与编辑器路径比较；同名文件夹不代表同一克隆。'),('仓库地址错了','remote -v 核对 owner/PHM；不要只看文件夹名。'),('文件被忽略 / 空目录','check-ignore -v、ls-files 检查；Git 不跟踪空目录。'),('认证或 403','作者姓名不是登录账号；检查 GCM、PAT/SSH、仓库写权限和组织策略。'),('保护规则要求 PR','改走功能分支与 PR，按规则完成检查；不使用强推绕过。'),('网络超时 / DNS 错误','检查本地网络、GitHub 服务状态；保留本地提交，恢复网络后重试。')],size=10.2)
    box('不要用危险命令猜原因','删除 .git、reset --hard、clean -fd、push -f 会改变或丢失内容；关闭 SSL 校验和明文保存令牌也不能解决同步原理问题。',tone='gold')

    start('RECOVERY / 15','撤销与找回：先保护现场','本页是按条件选择的操作，不是连续执行的修复脚本。','S14 / S15')
    title('只是暂存错了')
    code(['git restore --staged -- "实际文件路径"','# 已有提交的仓库：撤回暂存，不丢工作区内容'])
    title('已经 push 的普通提交要撤销')
    code(['git log --oneline -10','git show 实际提交编号','git revert 实际提交编号','# 先核对目标；检查反向提交的结果，再 git push'])
    p('revert 新建一个反向提交，保留共享历史。可能冲突，也可能影响后续依赖；合并提交的撤销需要另选主线，不能直接套用。秘密泄露仍需先撤销或轮换凭据。')
    title('已经提交过，后来找不到了')
    code(['git reflog -15','git show 实际找到的提交编号','git branch rescue/recovered 实际找到的提交编号'])
    box('reflog 是本机记录','先核对再建救援分支，避免直接覆盖当前分支。reflog 不永久保留，也不是跨电脑日志；从未提交、没有备份的文件不能保证找回。merge / rebase 中止使用对应的 --abort。')

    start('RESEARCH FILES / 16','代码能拉到，环境不一定能复制','PHM 的代码、数据与运行环境要分开管理。','S11 / S18')
    rows([('纳入 Git','源码、配置示例、README、测试、按项目使用的依赖文件与锁文件。'),('本机重建','虚拟环境、缓存、运行日志；不把 A 的 .venv 原样搬到 B。'),('独立保存','原始数据、视频、权重：记录版本、来源与校验值；按授权共享。'),('不写进仓库','令牌、私钥、真实 .env。只放无秘密的 .env.example。'),('可复现实验','还需对齐数据、随机种子、依赖与 Python 版本，不只对齐代码。')],size=10.3)
    title('关于当前 OneDrive 路径')
    p('当前学习材料位于 OneDrive 下，不代表已经出现故障。作为预防性安排，建议工作克隆使用普通本地目录，两台电脑各自 clone，经 GitHub 同步，减少云盘与 Git 同时写 .git 的风险。本次没有移动目录。')
    box('大文件与秘密不是普通同步错误','常规 Git 上传超过 100 MiB 的文件会被阻止；超过 50 MiB 有警告，浏览器单文件上限 25 MiB。以官方现行限制为准，不把 LFS 当作无限免费存储。',tone='gold')
    p('.gitignore 不移除已跟踪内容，也不抹掉旧历史。新提交里删除大文件或秘密，仍不能清除旧提交里的副本。先备份、撤销泄露凭据，再针对具体历史制定清理方案。')

    start('DAILY CARD / 17','每次换电脑前后，只核对这几项','把这一页打印或保存在桌面，形成固定交接习惯。','S03 / S04 / S09')
    title('开工：确认 → 拉取 → 核对')
    code(['git branch --show-current','git status','git pull --ff-only','git log -1 --oneline'])
    title('收工：保存 → 暂存检查 → 提交 → 推送')
    code(['git add -- "实际文件路径"','git diff --cached','git commit -m "描述这次修改"','git push','git status -sb'])
    box('网页最后确认','选同一分支，看到相同提交编号。交接记录：仓库、分支、最后提交短编号、push 是否成功、待做事项、检查情况、未纳入 Git 的文件。')
    title('三个问题，检验自己是否掌握')
    p('1. A 已 commit 但没 push，B 能拉到吗？<br/>2. working tree clean 能证明上传了吗？<br/>3. stash 中的文件会跟着普通 push 到 B 吗？')
    p('答案：都不能。交互练习见 lessons/0001-two-computers.html；详细命令与排错见同目录的 Markdown 分类教程。',gap=0)

    for group,items in enumerate((SOURCES[:10],SOURCES[10:]),1):
        start(f'SOURCES / {17+group:02d}','官方资料与适用范围' if group==1 else '补充来源与制作说明','核对日期：2026-10-19。S 编号对应各页依据；点击标题可打开官方原文。')
        for sid,t,url in items:
            p(f'<font color="#007F83"><b>{sid}</b></font>  <a href="{escape(url)}" color="#007F83">{escape(t)}</a><br/><font size="7.5" color="#667D8E">{escape(url).replace("/", "/<wbr/>")}</font>',gap=11)
        if group==2:
            box('本手册的核实边界','已阅读两份输入材料并参考官方文档。未提供真实仓库 URL；未核实账号权限、实际分支和仓库规则。PHM 页面为教学示意。教程不等于已在用户仓库执行；本地隔离演练与版式检查见验证记录。')
    C.save()
    (ROOT/'tmp/pdfs').mkdir(parents=True,exist_ok=True)
    (ROOT/'tmp/pdfs/layout_audit.json').write_text(json.dumps(AUDIT,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'PDF written: {OUT} ({PAGE} pages)')

if __name__=='__main__':
    # 默认只重建长版 PDF，避免覆盖已按真实问题修订的 Markdown。
    if '--regenerate-generic-docs' in sys.argv:
        docs()
    pdf()
