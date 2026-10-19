# 文件夹二 C：命令行 HTTPS 上传

推荐先用 Git Credential Manager（GCM）在浏览器登录，不必手工创建 PAT。
执行 git config --show-origin --get-all credential.helper 可以检查现有凭据助手；
没有 GCM 时按官方说明安装配置，不要随意替换为 credential.helper store。
GitHub Git 的 HTTPS 账号密码认证已停用；GCM 登录、PAT 与 SSH 都是可选认证方式。

如果确实需要手工 PAT：
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token。
选择有效期、正确的 Resource owner 和目标仓库，普通代码推送给予 Contents: Read and write。
涉及 .github/workflows 文件时还需对应 Workflows 权限；组织可能要求审批或有额外策略。
命令行实际提示用户名/密码时，用户名填 GitHub 用户名，密码位置填 PAT；不是账号密码。
不要把 PAT 写入 URL、教程、脚本或仓库；fine-grained token 也不一定以 ghp_ 开头。
不使用 credential.helper store 保存令牌，因为它是明文存储。

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
git remote add origin https://github.com/YOUR-USER/PHM.git
# YOUR-USER 和 PHM 替换成自己的用户名、仓库名；已有 origin 时先检查，不重复 add。
git remote -v
# 核对仓库地址。
git push -u origin main
# origin 是远程名，main 是分支名；-u 为首次推送建立上游关联。
```
若已有 origin 且地址写错，确认后执行 git remote set-url origin 正确地址。
这里假设远程仓库为空；远程已有提交时先按文件夹三 clone，或看问题 6。
以上是手动命令示例，不是会自动停止的脚本；请自行核对远程为空、身份、项目根目录和当前分支，报错后停止。
