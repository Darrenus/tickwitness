# TickWitness 技术 alpha 外部复验手册

这份 kit 用于检查：已有合成证据能否在你的独立环境重建相同的受限结论、无效扰动是否被拒绝，以及原子发布在受控同步故障下是否正确报告。它不运行交易策略、不连接交易所、不使用 GPU，也不需要原作者的数据库、行情采集目录或 native 引擎。

当前软件交付与真实外部复验分开追踪。尚未收到外部实际记录时，计数保持 **0 / PENDING**；你运行后产生的提交也先标记为 **SELF_REPORTED_UNREVIEWED**，由维护者核对。失败和安装问题同样是有价值的复验记录，请保留。

## 1. 开始前应收到什么

请从联系人取得完整 kit 目录，以及通过可信单独渠道提供的 **64位 kit ID**。目录内应有 `manifest.json`、本手册 `README.md`、`reproduce.py`、`distribution` 下唯一的 `tickwitness-…-py3-none-any.whl`，以及 `cases/counterexample`、`cases/clean-control` 两个完整证据包。

如果收到的是 `alpha-reproduction-kit.tar.gz`，请同时保留包外的 `handoff.json`／`HANDOFF.txt`。它们列出实际 kit ID、archive／wheel SHA-256、组装 revision 和三步命令。**先通过 owner 的单独可信渠道确认 archive SHA-256，再用系统命令校验，随后才解压或安装 wheel。不要只信任与压缩包同送的 sidecar。**

把下面 `OWNER_CONFIRMED_ARCHIVE_SHA256` 换成通过单独渠道确认的64位值，在压缩包所在目录执行；只有显示 `OK` 且期望值与 owner 确认值一致才继续：

```sh
printf '%s  %s\n' 'OWNER_CONFIRMED_ARCHIVE_SHA256' 'alpha-reproduction-kit.tar.gz' | shasum -a 256 -c -
```

校验失败或暂时无法向 owner 确认时，不安装或执行包内内容，保留实际输出并联系 owner。校验后在新目录解压，得到唯一顶层 `tickwitness-alpha-kit`；不要把包外 sidecar 塞回 kit，或修改 README。Archive 只携带 kit，不混入作者的 probe／自动化提交；sidecar 中的外部计数仍是0/PENDING。若最初只收到解压目录，请先向 owner 索取归档与单独确认的 checksum，完成这个安装前步骤。

不要自行修改文件、补缺件、重新计算一个 ID 当成原 pin，或把只有报告 JSON 的目录当成完整 kit。Hash pin 检查内容身份，不等于作者签名。原始合成见证来自早先受验收的 S08-01，当前组装 revision 另记在 manifest；不是新跑出来的盈利记录。

所需环境：独立的 **Linux 或 macOS**、Python **3.12／3.13／3.14**、可创建新目录且支持 atomic no-replace 和目录 fsync 的本地文件系统。不承诺 Windows、特殊网络盘或真实断电恢复资格。包下载完成、Python 已可用后，安装与复验可以离线进行。无需额外 Python 依赖、数据库、API key 或 GPU。

## 2. 在新的虚拟环境安装

下列绝对路径仅为示例，请替换成你的实际路径。虚拟环境与提交目录放在 kit 外；不要从 TickWitness 源码 checkout 内运行。

```sh
python3.12 -m venv /absolute/path/tickwitness-alpha-env
/absolute/path/tickwitness-alpha-env/bin/python -m pip install \
  --no-index --no-deps /absolute/path/alpha-kit/distribution/*.whl
/absolute/path/tickwitness-alpha-env/bin/python -I -m tickwitness --version
```

可使用受支持的其他 Python 版本。请安装随包 wheel，不安装 `[nautilus]`、不另装最新版，也不以源码 editable 安装替代。若创建环境或安装失败，保留终端中的实际命令与完整错误，连同 OS／Python 版本发回联系人；此时不要填造一次成功结果。

## 3. 执行并保存真实尝试

联系人会给你实际 kit ID；下面 `REPLACE_WITH_64_HEX_KIT_ID` 必须替换，不能留作占位符。participant ID 取一个不含私人联系方式的简短代号。只有实际参与的外部用户选择 `external_user`；维护者自测选择 `maintainer`，自动任务选择 `automation`。Role 是自报，不认证独立身份。

```sh
/absolute/path/tickwitness-alpha-env/bin/python -I \
  /absolute/path/alpha-kit/reproduce.py \
  --kit /absolute/path/alpha-kit \
  --expected-kit-id REPLACE_WITH_64_HEX_KIT_ID \
  --participant-id external-reviewer-01 \
  --participant-role external_user \
  --output /absolute/path/tickwitness-submission-01
```

`--output` 必须是尚不存在的新目录。Runner 用同一已安装 Python 启动实际 CLI，保存 `submission.json` 和实际产生的 scorecard／错误输出；它不联网、不自动上传或替你联系任何人。请保留整个输出目录。非零退出、超时、错误 pin 或 IO 问题也要保留，不用删掉失败后只交成功截图。

Runner 成功退出0；已经保存实际失败时退出10，已保存超时则退出11。实际 CLI 原退出码另存在 submission 内；例如错 pin 的 CLI 退出3，不应手工改成10。提交文件本身 IO 失败退出3，此时可能没有完整 submission，请保留终端原始错误并说明发生在哪一步。

重试请换一个新输出目录，保留上次失败目录。Kit 和原证据保持原样，不要重用旧 probe 目录、不覆盖已有制品、不删除同步不确定目录以伪装成首次成功。提交前可检查记录是否含你不愿分享的环境信息；如需脱敏，应另提供说明并保留原件，不能静默改写 hash 绑定的证据。

## 4. 预期结果怎么读

| 检查 | 预期技术结果 |
| --- | --- |
| 既有反例 | `COUNTEREXAMPLE_FOUND`；冻结有限候选 `[1,3]` 被完整审计并含 false 见证 |
| 完整 clean control | `NO_COUNTEREXAMPLE_FOUND`；相应冻结谓词在完整非空候选集合全 true，无未知或未评估后缀 |
| 无效扰动 | 从实际假设上界导出 `upper+1 ns`，实际 validator 以范围错误拒绝；不是新研究 finding |
| 正常发布与重名 | 新 kit 发布后能读回；同目标重复发布拒绝且原字节不变 |
| 提交前同步失败 | 无成功回执、无最终目标，stage 清理 |
| 提交后父目录同步失败 | 无成功回执，保留完整目标；内容可以重新核验，但 durability 仍未确认 |

最后两项是显式注入的受控错误，不是要求你的磁盘真的出故障，也不是物理断电试验。技术 PASS 表示实际观察到规定的失败边界；那些失败发布本身没有成功回执。若运行中出现其他错误，按真实失败保留，不手动把它改成预期结果。

反例与 clean control 分别冻结 `net_marked_pnl > 0 USD` 和 `> -3 USD`，是两份不同问题的技术对照。结果不证明同一声明发生翻转、延迟因果、真实市场概率、策略未来盈利或确认样本有效性。复验不消耗原研究槽位，不重新运行 native，不开启 confirmation。

Scorecard 的 `technical_checks` 可以为 `PASS`，同时仍固定显示：

```text
external_attempts = 0
external_successes = 0
external_attempt_gate = PENDING
release_decision = TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING
```

这是软件主动保留的外部接受门，不是要求你改 JSON。填写 `external_user` 不会自动把它改成1；联系人收到你的真实提交后再核对并登记。CI、AI、作者或 owner 的自测不会计为外部用户，也不因此发布版本。

## 5. 发回哪些材料

请自行把**整个新提交目录**及你收到的 kit ID 发回联系人，包括失败记录。补充你实际操作的环境、是否独立于原作者工作目录、看不懂或不能完成的步骤，以及任何需要手动绕过的地方。不要只发 PASS 截图或手工整理的布尔结论。

如果失败早于 runner 启动，请发回安装／启动命令、原始退出码和错误、OS／Python 版本及 kit ID，并明确说明还没有生成 submission。不要补写一个未执行的 submission。参与者身份与独立性由后续真实沟通核对，本 kit 不作认证。

项目仓库与问题追踪：[Darrenus/tickwitness](https://github.com/Darrenus/tickwitness)。本手册可以作为 kit 内独立 README 使用；没有依赖原源码 checkout 的相对文档链接。
