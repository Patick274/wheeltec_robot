"""在临时目录里验证教材场景，不访问 GitHub 或改动用户仓库。"""
from pathlib import Path
import tempfile, subprocess, os, json, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
GIT = Path('C:/Users/thunderobot/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe')
ENV = os.environ.copy()
for k in list(ENV):
    if k.startswith('GIT_'): ENV.pop(k)
ENV.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_EDITOR='true', GIT_MERGE_AUTOEDIT='no')
RESULT=[]
def git(path,*args,ok=True):
    r=subprocess.run([str(GIT),'-C',str(path),*args],env=ENV,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if ok and r.returncode: raise RuntimeError(str(args)+'\n'+r.stdout+r.stderr)
    return r
def note(s): RESULT.append(s); print('PASS: '+s)
def commit(repo,message):
    git(repo,'add','.')
    git(repo,'commit','-m',message)
def put(repo,name,text): (repo/name).write_text(text,encoding='utf-8')
def counts(repo): return git(repo,'rev-list','--left-right','--count','HEAD...@{upstream}').stdout.split()
DEMO_ROOT = Path('C:/Users/thunderobot/.codex/visualizations/2026/10/19/01a152aa-4ceb-73b3-b1ff-ea70418122c4')
DEMO_ROOT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='phm-git-learning-', dir=DEMO_ROOT, ignore_cleanup_errors=True) as td:
    base=Path(td); remote=base/'remote.git'; a=base/'A'; b=base/'B'
    assert base.resolve().is_relative_to(DEMO_ROOT.resolve())
    git(base,'init','--bare','--initial-branch=main',str(remote))
    git(base,'clone',str(remote),str(a))
    for repo in [a]:
        git(repo,'config','user.name','Learning Demo');git(repo,'config','user.email','demo@example.invalid')
    put(a,'README.md','initial\n'); put(a,'config.py','sample_rate = 100\n');commit(a,'initial');git(a,'push','-u','origin','main')
    git(base,'clone',str(remote),str(b))
    git(b,'config','user.name','Learning Demo');git(b,'config','user.email','demo@example.invalid')
    assert counts(b)==['0','0'];note('两份独立克隆、origin 与上游建立成功')
    put(a,'README.md','A change\n');commit(a,'A edit')
    assert git(a,'status','--porcelain').stdout==''
    git(a,'fetch','origin');assert counts(a)==['1','0'];note('工作区 clean 时仍可有一个未推送提交')
    assert git(a,'rev-parse','HEAD').stdout!=git(b,'rev-parse','HEAD').stdout
    git(a,'push');git(b,'pull','--ff-only')
    assert git(a,'rev-parse','HEAD').stdout==git(b,'rev-parse','HEAD').stdout;note('A push 后 B 快进拉取，提交编号一致')
    put(b,'README.md','staged\n');git(b,'add','README.md');put(b,'README.md','later edit\n');git(b,'commit','-m','staged snapshot')
    assert git(b,'show','HEAD:README.md').stdout=='staged\n';assert (b/'README.md').read_text()=='later edit\n'
    git(b,'add','README.md');git(b,'commit','-m','later snapshot');git(b,'push');git(a,'pull','--ff-only');note('add 后再编辑，commit 默认只包含已暂存版本')
    put(a,'a.txt','A independent\n');commit(a,'A new');git(a,'push')
    put(b,'b.txt','B independent\n');commit(b,'B new');git(b,'branch','backup/b-before-sync')
    assert git(b,'push',ok=False).returncode!=0
    git(b,'fetch','origin');assert counts(b)==['1','1']
    assert git(b,'pull','--ff-only',ok=False).returncode!=0
    git(b,'merge','origin/main','--no-edit');assert (b/'a.txt').exists() and (b/'b.txt').exists()
    git(b,'push');git(a,'pull','--ff-only');note('分叉被检测；快进停止；merge 保留双方提交并可普通推送')
    put(a,'config.py','sample_rate = 200\n');commit(a,'A config');git(a,'push')
    put(b,'config.py','sample_rate = 300\n');commit(b,'B config');git(b,'fetch','origin')
    before=git(b,'rev-parse','HEAD').stdout
    assert git(b,'merge','origin/main','--no-edit',ok=False).returncode!=0
    assert '<<<<<<<' in (b/'config.py').read_text()
    git(b,'merge','--abort');assert git(b,'rev-parse','HEAD').stdout==before
    assert git(b,'rebase','origin/main',ok=False).returncode!=0
    put(b,'config.py','sample_rate = 250\n');git(b,'add','config.py');git(b,'rebase','--continue')
    git(b,'push');git(a,'pull','--ff-only');assert (a/'config.py').read_text()=='sample_rate = 250\n'
    note('同一行冲突、merge --abort、rebase 解决后 continue 和普通 push')
    put(b,'.gitignore','ignored.txt\n');commit(b,'ignore data');git(b,'push');git(a,'pull','--ff-only')
    put(b,'README.md','local uncommitted\n');put(b,'new.txt','untracked\n');put(b,'ignored.txt','ignored\n')
    git(b,'stash','push','-u','-m','before sync')
    assert not (b/'new.txt').exists() and (b/'ignored.txt').exists()
    put(a,'other.txt','remote update\n');commit(a,'A remote update');git(a,'push');git(b,'pull','--ff-only')
    git(b,'stash','apply','stash@{0}');assert (b/'new.txt').exists();assert git(b,'stash','list').stdout
    commit(b,'restored work');git(b,'push');git(b,'stash','drop','stash@{0}');git(a,'pull','--ff-only')
    assert not (a/'ignored.txt').exists();note('stash -u 收起未跟踪文件但不含忽略文件；apply 后记录保留')
    git(a,'switch','-c','feature/phm-reader');put(a,'feature.txt','WIP\n');commit(a,'WIP');git(a,'push','-u','origin','feature/phm-reader')
    git(b,'fetch','origin');git(b,'switch','--track','origin/feature/phm-reader')
    assert (b/'feature.txt').read_text()=='WIP\n';note('功能分支在 A 推送后，可在 B 跟踪接手')
    git(b,'switch','main');git(b,'pull','--ff-only')
    put(b,'revert-demo.txt','revert me\n');commit(b,'to revert');git(b,'push');target=git(b,'rev-parse','HEAD').stdout.strip()
    git(b,'revert','--no-edit',target);git(b,'push');assert not (b/'revert-demo.txt').exists()
    git(b,'branch','rescue/recovered',target);assert git(b,'show',target+':revert-demo.txt').stdout=='revert me\n'
    note('已推送普通提交可 revert；历史仍可查看并建立救援分支')
report='''# 验证记录

日期：2026-10-19。

## 核心流程演练

使用临时目录中的一个本地裸仓库模拟远程，A、B 两个独立克隆模拟两台电脑。
未连接 GitHub、未触碰真实 PHM 的 Git 元数据，未改动全局配置；临时演练目录结束后清理。

通过项目：

'''+ '\n'.join('- '+s for s in RESULT)+'''

## 文件与 PDF 检查

最终 PDF 共 19 页；嵌入中文字体、可搜索文字、目录书签、官方资料链接。
逐页渲染并目视核对版式，检查文本与代码框边界；检查 Markdown/HTML 本地链接和原始 TXT 副本。
PDF 页面使用示意图，不是用户实际 GitHub 页面截图。

## 未验证范围

未验证真实 GitHub 登录、网络、仓库权限、分支规则、Desktop 实际安装界面或 PHM 项目测试。
真实仓库元数据当前读取受环境限制，示例分支 main 和仓库地址必须按实际核对。
Windows Desktop 步骤依据官方文档；核心 Git 命令演练不能替代在线账户验证。
'''
(ROOT/'验证记录.md').write_text(report,encoding='utf-8')
print(json.dumps({'passed':len(RESULT)},ensure_ascii=False))
