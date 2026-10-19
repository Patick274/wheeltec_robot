# 文件夹三 B：GitHub Desktop 同步

1. 在第二台电脑安装 Desktop，登录账号，并配置提交姓名与邮箱。
2. 首次：File → Clone repository，选仓库或填 URL，选保存路径，再 Clone。
3. 每次开始工作前：选择 Current branch → 目标分支，先 Fetch origin；有更新则 Pull origin。
4. 修改代码，回 Desktop 查看差异，选择需要提交的文件。
5. 填写 Summary → Commit to 当前分支 → Push origin。
6. 如果界面提示冲突，按提示在编辑器解决并完成合并，核对后再 Push。
电脑 A 做完后先 Commit 和 Push；电脑 B 开始前先 Fetch 和 Pull，返回 A 时也一样。
Fetch 仅获取远程信息；Pull 才把远程更新整合到当前分支。
