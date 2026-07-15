# 维护手册（给维护者，用户不用看）

## 一、三个地方，各管各的

| 位置 | 角色 | 里面有什么 |
|---|---|---|
| GitHub 仓库 `yuwen-cool/yuwen-publish-precheck` | **发布版**，用户从这里安装和升级 | 干净的产品文件 + 空模板 |
| 本地 `~/Desktop/coding/yuwen-publish-precheck/` | **发布仓**，连着 GitHub 的本地副本 | 和 GitHub 一模一样 |
| 本地 `creator/.cursor/skills/yuwen-publish-precheck/` | **日用副本**，自己平时用 + 改进都在这里 | 产品文件 + 自己的真实沉淀（data/） |

改进永远先发生在日用副本（自己先用顺了），再同步到发布仓推上去。个人沉淀只存在于日用副本的 data/，同步命令会排除它，物理上到不了 GitHub。

## 二、什么能随便改，什么不能动

**能随便改（用户升级不受影响）**：规则文档（references/）、脚本（scripts/）、SKILL.md 指令、README/ROADMAP/CHANGELOG、模板（templates/）、测试（evals/）。用户的数据在 data/ 下且不被 Git 跟踪，`git pull` 物理上碰不到。

**三条不能破坏的契约（破坏 = 毁掉老用户）**：

1. `.gitignore` 里 data/ 不入库的规则**不能删改**；任何时候不得把 data/ 下除 README 外的文件加入 Git（有测试守着：`test_user_data_never_tracked_by_git`）；
2. **数据文件格式向后兼容**：my-rules.md 的表格列、expressions.md 的分区、词库的行格式——只能加列/加区，不能改名或删列；scan.py 解析必须继续兼容旧格式（参考现有的四列/五列兼容写法）；
3. **data/ 的路径约定不挪**：用户的文件就在那些位置，换目录名 = 老用户的沉淀全部失联。

## 三、发布一次更新的标准流程（5 步）

在日用副本改完后：

```bash
# 1. 日用副本跑测试（15 个全过才继续）
cd ~/Desktop/coding/creator/.cursor/skills/yuwen-publish-precheck && python3 evals/test_scan.py

# 2. 同步到发布仓（--exclude data/ 保证个人沉淀不外流）
rsync -a --delete --exclude 'data/' --exclude '.git' --exclude '__pycache__' --exclude '.DS_Store' \
  ~/Desktop/coding/creator/.cursor/skills/yuwen-publish-precheck/ ~/Desktop/coding/yuwen-publish-precheck/

# 3. 发布仓再跑一次测试（数据安全测试只在这里真正生效）
cd ~/Desktop/coding/yuwen-publish-precheck && python3 evals/test_scan.py

# 4. 检查即将公开的内容（看一眼有没有不该出现的文件/改动）
git status && git diff --stat

# 5. 更新 CHANGELOG.md 版本号和变更说明，然后提交推送
git add -A && git commit -m "版本说明" && git push
```

不会敲命令就把这份文件发给 AI，说"按维护手册发布这次更新"。

## 四、发布前自查清单

- [ ] 两处测试都全过
- [ ] `git status` 里没有 data/ 下的文件（除 README）
- [ ] `git diff` 里没有个人信息、绝对路径、密钥
- [ ] CHANGELOG 写了这次改了什么
- [ ] 改了规则内容的：规则要点能追溯到官方来源（重大规则变更建议先走上游 video-rules 规则库的回归再生成）

## 五、常见问题

- **改了模板会影响老用户吗？** 不会。用户的实际数据是从模板复制出去的独立文件，升级只更新模板本身，下次新建才用新模板。
- **用户报告升级后出问题？** 先让对方发 `git status` 和报错原文；`git pull` 被拒绝通常是对方改了跟踪文件，指导其 `git stash && git pull && git stash pop`。
- **失手把不该发的推上去了？** 立即联系维护 AI 做历史重写 + 强推，越早越好。
