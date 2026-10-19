# 文件夹三 C：命令行 HTTPS 同步

新电脑安装 Git、配置 user.name/user.email，并用 GCM 在浏览器登录；若手工使用 PAT，见文件夹二 C。
下文 YOUR-USER 替换为自己的 GitHub 用户名；仓库不叫 PHM 时也一并替换。

首次克隆（只做一次）：
```powershell
Set-Location -LiteralPath 'D:\Projects'
# 先进入现有的父文件夹；PHM 由 clone 创建。
git clone https://github.com/YOUR-USER/PHM.git PHM
# clone 自动设置 origin；新电脑还要配置提交身份和认证。
Set-Location -LiteralPath 'D:\Projects\PHM'
git branch --show-current
# clone 通常检出远程默认分支；默认分支不一定叫 main。
git remote -v
```
日常步骤 1：开始改代码之前同步
```powershell
git status
# 确认在正确分支且工作区干净；有修改先提交或参考问题 6 暂存。
git pull --ff-only
# 使用当前分支的上游；若分支已分叉，会停止，不自动重写历史。
```
日常步骤 2：编辑、保存文件，然后提交与上传
```powershell
git status
git add .
git diff --cached
# 检查提交内容。
git commit -m "描述这次修改"
# 没有更改时无需新提交；已有提交仍然可能需要 push。
git push
# 使用当前分支的上游；新分支先 git push -u origin 分支名。
```
如果 push 被拒绝，按问题 6 处理；不要用强推覆盖另一台电脑的提交。
首次克隆、编辑前拉取、编辑后提交与推送是三个独立阶段。
不要把这三个阶段当成一个连续的一键动作。
