# 文件夹二 D：命令行 SSH 上传

SSH 适合长期使用；密钥保护权限，remote 地址决定推送到哪个仓库。
每台电脑各自生成密钥，将各自公钥加入同一 GitHub 账号即可，不必复制私钥。

```powershell
Get-ChildItem -LiteralPath "$env:USERPROFILE\.ssh" -ErrorAction SilentlyContinue
# 先检查现有密钥。已有密钥就评估复用，不要覆盖。
ssh-keygen -t ed25519 -C "你的邮箱"
# 按提示选保存位置；默认通常是用户目录/.ssh/id_ed25519。
# 看到覆盖提示不要盲目回车；建议设置密钥口令（passphrase）。
Get-Content -LiteralPath "$env:USERPROFILE\.ssh\id_ed25519.pub"
# 只复制 .pub 公钥整行。无 .pub 后缀的是私钥，不能上传或分享。
```
GitHub → Settings → SSH and GPG keys → New SSH key，类型选择 Authentication Key，粘贴公钥。
```powershell
ssh -T git@github.com
# 第一次连接先核对官方主机指纹，再回答 yes。
# Hi 用户名! You've successfully authenticated ... 表示认证成功。
# GitHub 不提供 shell，成功测试也可能返回退出码 1，应以消息和用户名判断。
```
官方指纹：https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
有口令的密钥可能每次询问口令，不等于配置失败；需要免重复输入时再配置 ssh-agent。
Windows 内置 OpenSSH 与 Git 自带 SSH 可能使用不同 agent，按官方 Windows 文档选择一致的工具链。
Git Bash 可在同一会话执行 eval "$(ssh-agent -s)" 和 ssh-add ~/.ssh/id_ed25519；这两条不是 PowerShell 语法。

首次上传前，把 YOUR-USER、PHM 和本地目录换成实际值。

```powershell
Set-Location -LiteralPath 'D:\Projects\PHM'
# 先确认该路径就是项目根目录，并准备好 .gitignore。
git init -b main
# 仅用于尚未初始化的新项目；已有仓库跳过，并确认当前分支。
git status --short
# 检查将要上传的文件，特别是凭据、虚拟环境和大文件。
git add .
# 暂存本目录内的新增、修改和删除；确认人在根目录。
git diff --cached --stat
git diff --cached
# 检查已暂存的内容；确认后再提交。
git commit -m "首次上传代码"
# 生成本地版本，不等于上传。
git remote add origin git@github.com:YOUR-USER/PHM.git
# YOUR-USER 和 PHM 替换成自己的用户名、仓库名；已有 origin 时先检查，不重复 add。
git remote -v
# 核对仓库地址。
git push -u origin main
# origin 是远程名，main 是分支名；-u 为首次推送建立上游关联。
```
若已有 origin 且地址写错，确认后执行 git remote set-url origin 正确地址。
这里假设远程仓库为空；远程已有提交时先按文件夹三 clone，或看问题 6。
以上是手动命令示例，不是会自动停止的脚本；请自行核对远程为空、身份、项目根目录和当前分支，报错后停止。
