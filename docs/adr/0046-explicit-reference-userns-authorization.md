# ADR0046：显式冻结参考环境的userns兼容授权

状态：S13-02补充冻结，2026-11-19 Asia/Singapore。须先独立commit/push政策与合同，再实现loader/bootstrap；尚无加载／transition／完整资格通过，M1产品关闭。

## 背景

首轮run44536018240/head `e575a914` 在bwrap loopback RTM_NEWADDR处EPERM，0payload starts；原VM没有audit，不能回填原因。

另一次run44538107915/head `56a4377` 的同boot/case窗口有三条有效audit：bwrap/unconfined userns_create AUDIT，继而unprivileged_userns下setpcap与net_admin DENIED。collector溢出且尾行损坏，整体completeness仍UNKNOWN；三条实证与缺失同时保留，不计攻击通过。

## 决定

只在一个全新专用GHA Ubuntu24.04/x86_64 CPU VM使用[精确政策](../../research/security/reference-bwrap.apparmor)及[兼容合同](../contracts/restricted-reference-apparmor-v1.md)：ABI4.0、exact `/usr/bin/bwrap` attachment、named `tickwitness-reference-bwrap`、unconfined flag、仅userns许可，无额外include或通配attachment。

这是显式许可例外，不是MAC隔离；不天然限定UID或仅setup，后代可继承label。loader仅add/skip-cache，不replace、复用冲突政策、全局reload或关闭AppArmor/sysctl；global restriction仍1。load前绑定policy/parser/config/ABI/kernel features/libapparmor等真实字节与状态，未知不得填pin。

trusted root bootstrap须先进入原owned leaf并读回控制，再于UIDdrop和NNP前经受信libapparmor执行aa_change_profile进入named profile，记录真实前后label及结果；不指望NNP后的exec放宽LSM。之后原UID/GID61184、groups[]、NNP1、zero host caps、required namespaces、cap-drop ALL、final seccomp及FD规则保持。controller不进入task profile；不执行任意源码。

观察基线为Ubuntu24.04.5/kernel7.0.0-1017-azure/ImageVersion20261111.370.1/bwrap0.9.0 pkg0.9.0-1ubuntu0.3，不是未来exact pin。新VM实际parser/ABI/library及完整tuple须先冻结再probe，loaded名／mode、bootstrap／guest label和实际控制不符即拒绝／UNKNOWN／NOT_QUALIFIED。

## 后果与门槛

原24/600技术资格预算及全部CPU／内存／PID／scratch／FD／file／10s／2s／输出数字完全不变；失败未知不退款／隐藏重试，旧VM失败不抹去。0research reservations／0replay calls，原5/8/11、golden、PR94、Job/SDK/domain与已提交ACK语义不改，S13-02仍16h／S13总34h。

完整实际固定探针、宿主独立观察和停止／精确owned回收才决定新tuple资格；loader成功或AI自审不认证隔离。NNP/LSM仍可能不兼容，失败时不放宽现有保护。M1产品关闭，M2不支持，独立安全复核NOT_PERFORMED，真人0/0/PENDING；无release/GPU/新服务器/外发/自动合并，项目执行仅远端CPU。
