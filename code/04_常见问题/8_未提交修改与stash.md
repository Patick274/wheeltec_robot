# 问题 8：我已经修改代码，还没 commit，怎么 pull？

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
