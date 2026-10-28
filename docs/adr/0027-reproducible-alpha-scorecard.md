# ADR 0027：以可转交 kit 和真实边界 probe 区分技术 alpha 与外部复验

- 状态：Proposed；S08-03a 已[远端技术验收](../planning/sprint-08-status.md#s08-03a-远端验收记录)，[PR #94](https://github.com/Darrenus/tickwitness/pull/94) 待owner接受，真实外部门PENDING。
- 日期：2026-10-28。
- 基线：owner 已合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93)，merge `97822d7a74931a829bd3355fb40d85d4504de59d`。
- 合同：[Alpha Scorecard v1](../contracts/alpha-scorecard-v1.md)；[外部复验手册](../alpha-reproduction.md)。

## 问题

既有 portable search evidence 已能脱离原工作目录重建报告，但外部参与者仍需组合 wheel、证据、pin 与操作命令。单独汇总已有 PASS flags 无法证明此次确实重审或观察到同步失败边界；在独立 CI 环境重跑也不等于外部用户真正尝试过。

S08-03 要求反例、完整 clean、无效扰动和同步／原子制品边界，同时保留真实外部尝试。用户已选择自行联系外部参与者，目前尚无外部执行记录，不能以软件完成替代此门槛。

## 决策

新增 strict AlphaSuite／AlphaScorecard 与独立32MiB可转交 kit，固定携带实际 core wheel、操作手册、stdlib 提交 runner 和两个完整 search evidence 包。语料逐字节复用 owner 已接受 S08-01 native 反例与 all-true clean，记录旧 producer 与当前 assembler 的不同来源；不新增 native 研究执行、槽位或预算。

每次 qualify 重新验证两份原包及精确 bundle/report pins，要求 clean 完整非空；从实际 CE 冻结上界导出 upper+1 无效扰动并重新调用 validator。两案例的谓词不同，只承担技术对照，不扩展 baseline 翻转、因果或市场结论。

发布 probe 在新 scratch 内调用实际新 kit publisher，使用仅限本调用的同步 hooks：正常不覆盖发布、提交前失败清理、rename 后父同步不确定并保留完整内容。应用从 postcommit 目录重新取得 kit，再独立审计两例；失败发布不产生成功回执。受控注入与物理断电分别表述，不引入全局 monkeypatch 或恢复原数据库。

保存 scorecard 的验证必须重新执行整个流水线并 exact-match，不能信任外来 flags。确定性 scorecard 不存路径、时间或平台异常正文，保留固定技术 scope；实际 submission 则保留真实环境、命令、退出码和错误，失败尝试不删除。

外部 runner 只在参与者本地新目录采集提交，不自动联系或上传。Role 自报为 external_user／maintainer／automation，全部标 SELF_REPORTED_UNREVIEWED；身份不因填写 external 获认证，也不自动改软件 scorecard 门槛。CI、AI、owner 或模板不计外部用户。

## 结果与范围

技术 checks 全通过仍固定 external_attempts=0、external_successes=0、PENDING，release_decision 为 TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING。用户取得真实外部尝试后再保留原始记录并由 owner 接受；本批只交 S08-03a，#24 不整体 Done，不发行、不补造采用或人类领域复核。

严格 no-follow／bounded exact-tree 与 atomic no-replace IO 限定可信 parent、POSIX Linux/macOS 及支持的文件系统。Kit pins 是完整性引用，不是作者签名；当前证据不认证来源、全局历史、外部身份、物理 crash durability 或 S10 通用恢复。全部运行及安装验收远端执行，实际结果回填 [Sprint 8](../planning/sprint-08-status.md)，原8h专项估算不改记为实际工时。
