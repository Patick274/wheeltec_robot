# 问题 4：git push -u main 写错了什么

git push -u main 中的 main 会被当作远程名，而不是分支名；具体错误信息随仓库配置变化。
```powershell
git remote -v
git branch --show-current
# 先确认远程和分支。
git push -u origin main
# 正确结构：git push -u <远程名> <分支名>。
# 当前分支若为 master，就执行 git push -u origin master。
```
首次建立上游后通常可 git push。不要把 git push -u main 当作简写。
