# 补充：创建分支、选择分支、提交和推送分支

前提：仓库已有至少一个提交；下例从 main 创建 feature-lift-control。
每个小节是单独的操作阶段，不要整页一次执行。

阶段 1：同步基线并创建新分支（改代码之前）
```powershell
Set-Location -LiteralPath 'D:\Projects\PHM'
git status
# 有未提交修改时先提交到合适的分支，或按问题 6 用 stash 暂存。
git switch main
# 选择已存在的 main 分支。
git pull --ff-only origin main
# 只接受可快进更新；有分叉则停下检查。
git switch -c feature-lift-control
# 创建并切换到新分支；基于刚同步的 main。
git branch --show-current
# 确认当前选择的分支。
```

阶段 2：修改代码后提交、推送
```powershell
git status
git add .
# 在根目录暂存要提交的修改；也可指定具体文件。
git diff --cached
# 检查后提交。
git commit -m "新增升降控制功能"
git push -u origin feature-lift-control
# 首次推送该功能分支并建立上游；以后可 git push。
```

阶段 3：选择已有分支
```powershell
git fetch origin
# 更新远程跟踪分支列表。
git branch -a
# 列出本地及远程跟踪分支。
git switch feature-lift-control
# 选择已有的本地分支。
# 如果只在远程存在，改用下面这一条，不要两条都执行：
# git switch --track origin/feature-lift-control
```

阶段 4：合并（完成并验证功能后）
建议在 GitHub 打开 Pull Request，确认改动、检查通过后合并，再在本地切回 main 并 pull --ff-only。
个人练习仓库也可本地合并：
```powershell
git switch main
git pull --ff-only origin main
git merge feature-lift-control
# 有冲突则修改冲突文件、git add、git commit；也可 git merge --abort 放弃本次合并。
git push origin main
# 受保护分支若拒绝直推，改走 Pull Request，不要强推。
```
可选清理：确认已合并、已不需要且当前不在该分支，才 git branch -d feature-lift-control。
删除远程分支是另一项操作：git push origin --delete feature-lift-control；确认团队不再使用再执行。
删除分支属于可选清理步骤，确认后再单独执行。
