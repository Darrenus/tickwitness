# ADR0047：冻结专用 EC2 的真实来源与显式具名参考资格

状态：S13-02参考环境选择，2026-11-25 Asia/Singapore。本 ADR 和[EC2 合同](../contracts/restricted-reference-ec2-v1.md)须经独立审阅、实际 commit/push 并核对远端 ref 后，才可实现 provider/loader 或执行探针；实际冻结提交另记于状态入口，本文不声称资格通过，M1 产品仍关闭。

## 背景

PR115 仍为 Draft，source `00a134eb0144383cf80bcd1ed74305bb25036539`，owner main/base `6c350b9fe32dfed96392edd2b856e937f767e342`。原 GHA Ubuntu24.04 参考因100个 opaque attachment 无法建立旧合同要求的闭包而真实拒绝，未完成加载／transition／完整探针。旧失败、UNKNOWN 和封存证据保持原义，普通 CI 绿色不补足隔离资格。

现有专用用途 CPU VM 为 EC2 新加坡 `i-0d79530ca78320939`／`m7i.2xlarge`／AMI `ami-09289bc217ad5e9e7`，Ubuntu24.04/x86_64；先前只读观察 kernel `7.0.0-1018-aws`。VM 是持久宿主，Stop/Start 不是全新 GHA 环境；自动停机的基础实测也不能替代执行隔离资格。应先补齐停机异常分支，再推进该精确宿主的内部 reference。

## 决定

新增独立 `aws_ec2_dedicated_v1` 来源及 `restricted_reference_ec2_host_v1` 版本记录，不伪造 GITHUB_ACTIONS／github-hosted／ImageOS／ImageVersion／workflow 身份来通过旧入口。受信 root 仅以有界 IMDSv2 token＋IID 请求观察 instance／region／AMI／type／architecture，与 owner 固定期望匹配；source40hex、run32hex、kernel boot UUID 分别绑定，metadata token 不持久化或进入子进程。此记录不是独立硬件远程认证，也不防恶意宿主重写全部锚点。

新的精确政策为 ABI4.0、非绝对具名 `tickwitness-reference-ec2`、`flags=(unconfined)`、仅 `userns,`，**没有 exec attachment**；LF 终止字节 SHA256 `62c319e3655d13e4c4f856e3591efb48dda36ce3ba175681688ff49b05592314`。这是显式许可例外，不是 MAC 隔离。原 GHA v1／旧 attachment 门不改，不把 foreign opaque 规则当无冲突；仅在此新范围依据无 attachment 的具名政策，主张实际显式 transition 与独立观察到的执行身份。foreign 原始 unknown 记录保留且观测状态不得意外改变。

政策及 run 登记放在 root-owned `/var/lib/tickwitness-reference-ec2/runs/<run_id>` 不可复用子目录，stage 不进入自动加载的 `/etc/apparmor.d`。共同根及 `runs` 等 ancestors 可已存在，但必须逐项核对 root ownership／真实 directory identity／non-symlink／无 group/world write；本次 driver 首次排他创建 run 目录、record、claim，stage／证据也只可首次排他创建，旧 run/source/boot 记录永久保留。先前 invocation 的同名 profile 或选定 claim/run/stage/证据拒绝复用，不覆盖、不删除造 fresh；本次 driver 已合法创建的自身 claim 不应被 loader 误判为旧 run。

同一 accepted invocation 以精确 source/run/boot/owner-invocation 及真实 claim ownership，在 driver→loader→backend 间按 `CLAIMED→POLICY_READY→QUALIFYING→TERMINAL` 有序交接。loader 首次加入 driver 自身 CLAIMED，backend 首次加入其 POLICY_READY，均共用原持久 counters／monotonic anchor，不重新 admission；path／root UID／调用者提供的 runId 本身不能证明 ownership。重复 setup／第二次 runner initialization 拒绝，构造或重试不重建 claim、不清零计数／重置期限；失败／未知保留并结束或毒化本次 invocation。受信 loader 原30s／最多3固定外部命令／各64KiB／one add+skip-cache 限额保持；缺失依赖及 controllers 只能由可信准备阶段预置并读回，实际 parser/config/ABI/library/feature／政策字节及宿主 tuple 在探针前冻结，执行期不得修改全局配置补门。load 前冻结 pre-load manifest，load 后再冻结最终 manifest。

root bootstrap 仍先进入并读回原 owned cgroup，然后于 UIDdrop/NNP 前调用绑定 libapparmor 的 `aa_change_profile("tickwitness-reference-ec2")`。host 独立核对 bootstrap 与最终 guest 都为精确 `tickwitness-reference-ec2 (unconfined)`，再放行 GO。global AppArmor 与 userns restriction=1 不变，UID/GID61184、groups[]、NNP1、host caps0、required namespaces、RO mounts、FD closure、final seccomp 和全部 host canary 证据不让步；缺失或意外切换拒绝／UNKNOWN，不静默回退 M0。

保留同一固定24-case catalog、单 run 原600s monotonic 入场期限和24次最多提交。root 持久排他登记绑定 source/run/boot，失败和未知计费不退款；换目录、重建 runner、SSH 断线、取消或重启不产生新窗口，跨 boot 的旧 run 结束／不确定并拒续，不后台自动开新 run。原10s probe／另2s stop、各流64KiB、cpu.max25000/100000 fair-class rate、256MiB/swap0/oom.group1、pids32、唯一16MiB/512inode、FSIZE8MiB/FD64/core0/RTPRIO0 均不随8核32GiB宿主扩大。

资格与生命周期检查不打开研究 Job/Catalog/ledger、不调用回放、不预留研究槽或产生 finding；原协议/Job/family、5/8/11、attempts/events/native wall limits、golden、PR94、committed-result verify/ACK 及 unknown-slot 语义保持。真实研究重跑仍需同一原协议新槽。

## 后果与验收

所有项目／攻击／native／构建／类型检查继续在授权远端 CPU；不得本机执行。结束保存有界结果并请求 Stop，最后用 AWS 控制面确认 Stopped；四小时宿主保护不替代 probe 或600s窗口，也不是绝对计费硬上限。未确认整个任务 cgroup 已空不得卸载 scratch；未知停止／owned mount 状态保留诊断并停止后续 admission。新证据使用新 sibling scope，不写入旧 PR114／PR115 封存树。

完整固定探针实际通过也仅能产生此精确 tuple 的 `QUALIFIED_REFERENCE_ONLY`。M1 产品仍 DISABLED，原产品接入／原槽前 admission／fencing／独立安全复核等门另行满足；M2、任意源码、HTTP/MCP、release、GPU、额外服务器、自动合并及外发联系不由本 ADR 授权。外部真人复验0/0/PENDING、独立安全复核NOT_PERFORMED 分别保留，S13-02原16h／S13总34h及质量容量不变，不补造实际工时。

具体新来源 schema、IMDS 界限、政策字节、剩余不确定性与主源均见[EC2 合同](../contracts/restricted-reference-ec2-v1.md)。实际 freeze push、当前源码、宿主 manifest、原预算计数与负例／Stop／cleanup 必须在发生后另记，不预填通过或启用状态。
