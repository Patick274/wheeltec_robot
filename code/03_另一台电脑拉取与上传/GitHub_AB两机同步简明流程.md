# GitHub A/B 两机同步简明流程

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
