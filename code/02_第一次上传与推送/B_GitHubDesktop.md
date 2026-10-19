# 文件夹二 B：GitHub Desktop 上传

1. 从 https://desktop.github.com 安装 GitHub Desktop 并登录 GitHub。
2. 尚无任何仓库时，可 File → New repository，填写名称与父目录；注意实际创建的是“父目录/仓库名”。
3. 把项目文件复制到这个新仓库目录，检查 .gitignore 和待提交文件。
4. 左下角写 Summary，例如“首次上传代码”，点击 Commit to 当前分支。
5. 点击 Publish repository，确认名称、所属账号和 Keep this code private，再发布。
6. Repository → View on GitHub，核对上传结果。
如果已有本地 Git 仓库，用 File → Add local repository 选择现有根目录。
如果目录还不是仓库，按界面提示创建，并核对最终路径，防止在项目内又多建一个同名子目录。
如果 GitHub 上已经建了同名仓库，走 File → Clone repository 克隆它，再复制项目文件、Commit、Push origin；
不再次 Publish 同名仓库，也不要把旧 .git 一起复制。
此方法主要使用界面操作，无需执行本地命令脚本。
