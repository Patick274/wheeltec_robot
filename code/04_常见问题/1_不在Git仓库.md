# 问题 1：fatal: not a git repository

原因：当前目录及父目录没有有效 Git 仓库，常见于进入了错误目录或下载的 ZIP。
```powershell
Get-Location
# 看当前在哪个目录。
Set-Location -LiteralPath 'D:\Projects\PHM'
git rev-parse --show-toplevel
git status
# 先找已有仓库根目录，不要见到错误就到处 git init。
```
确实是从未初始化的新本地项目，才 git init -b main，接着按首次上传流程操作。
目标在 GitHub 已有历史时，用 clone 到新目录，而不是在 ZIP 内重新初始化。
