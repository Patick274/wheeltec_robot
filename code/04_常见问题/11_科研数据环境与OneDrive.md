# 问题 11：代码同步了，为何另一台电脑跑不起来？

Git 同步受跟踪的文件与提交，不复制整台电脑。推荐两个独立克隆，通过 GitHub 交接。
当前材料位于 OneDrive 路径；这是路径事实，不代表已经发生同步故障。
为减少 Git 元数据与云盘同步并发写入的风险，建议后续将工作克隆放在 C:Projects 或 D:Projects 等普通本地目录。
本次不移动或删除现有仓库。

## PHM 文件分类建议

| 内容 | 推荐处理 |
| --- | --- |
| .py、配置示例、README、测试 | 纳入 Git；提交有意义的小改动 |
| requirements.txt / pyproject.toml / 项目锁文件 | 按项目实际工具纳入 Git；另一台重建环境 |
| .venv、__pycache__、临时日志 | .gitignore 忽略，不复制虚拟环境 |
| .env、令牌、SSH 私钥 | 本机安全保存；仓库只放无秘密的 .env.example |
| 原始传感器数据、视频、权重 | 按大小与授权单独保存；Git 中记录来源、版本、校验值和获取方法 |
| 小型脱敏测试数据 | 确认可公开/可共享后按需纳入 Git |
| 论文或轨道设施敏感资料 | 先按项目规定处理；私有仓库也不是任意上传授权 |

## Python 环境重建示例

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 仅在项目实际提供 requirements.txt 时用；此命令是说明，不在本次执行。
```

依赖可能要联网下载；按项目实际 Python 版本、锁文件和 README 操作。
相对路径优先，避免把 A 的 D: 数据绝对路径写死到所有人共用的代码。
代码、数据、随机种子与依赖版本都要匹配，才能谈复现实验。

## 大文件与忽略规则

GitHub 浏览器上传单文件上限 25 MiB；常规 Git 仓库阻止超过 100 MiB 的文件，并对超过 50 MiB 的文件警告。
限制与套餐可能变动，以官方链接为准。不要把 LFS 当成无限免费容量；本教程不启用收费服务。
.gitignore 不会移除已跟踪文件。若仅需停止跟踪一个已跟踪但非秘密的文件：

```powershell
git ls-files -- '实际文件路径'
# 确认后才做下一条；--cached 只从暂存索引移除，保留本机文件。
git rm --cached -- '实际文件路径'
# 添加对应 .gitignore 规则，再检查、commit、push。
```

这不删除旧历史中的文件。密钥已提交时先撤销/轮换；大文件在待推送的旧提交里时，单纯新建删除提交仍可能被拒绝。
需要历史清理时先备份并制定迁移方案，不能用强推、重置或删 .git 试错。
来源：[大文件](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。
