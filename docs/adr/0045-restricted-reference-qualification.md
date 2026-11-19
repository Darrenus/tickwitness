# ADR0045：先限定远端隔离参考资格，再讨论产品接入

状态：S13-02首轮冻结，2026-11-19 Asia/Singapore。方案已选定；实现／实际资格未通过，M1产品入口仍关闭，独立安全复核未完成。

## 背景

owner已接受PR114的[执行信任模型](../contracts/execution-trust-v1.md)，该模型区分现有M0、未资格的M1与不支持的M2。现有Job进程组、CPU／单文件／FD控制及资源观测不能直接当作隔离后端；仅替换Popen命令会混淆执行主体、停止、lifetime和wait4口径。需要一个有界、真实可运行并可复核的参考切片，而不是开放任意策略执行。

## 决定

先提交推送[Restricted reference v1](../contracts/restricted-reference-v1.md)，再实现同一个内部launcher及固定合成负例。选择远端GitHub Actions CPU的Ubuntu24.04/x86_64参考家族；rolling label不构成exact pin，每个实际VM的OS／kernel／ImageVersion／二进制摘要／机制与限额须在探针前冻结manifest及SHA。未知字段不补造；tuple改变须重新资格。

受信root控制器在任务cgroup外：先创建并读回root-owned cgroupv2与唯一16MiB/512inode scratch，再让gated child进入leaf、降host UID/GID61184、清空groups、设置NNP并exec非setuid bwrap。必须成功建立所列user/pid/ipc/net/uts/cgroup与mount隔离；不用含try语义的unshare-all，不因NNP/AppArmor/userns失败全局修改宿主政策或降级运行。

固定cpu.max25000/100000为fair-class速率，memory.max256MiB/swap0/oom.group1/pids32；单文件8MiB、FD64、core0、RTPRIO0。seccomp拒绝socket/绕行、危险namespace/跨进程操作和RT调度修改；root/proc/usr/input逐mount只读，仅同一scratch通过tmp/shm别名可写。最终只留stdio；无设备节点、秘密、原ledger/Catalog或宿主socket。

每probe原monotonic10s入场窗口、另2s确认停止、stdout/stderr各64KiB；最多24个固定合成probe共用原600s资格入场期限。host日志在guest16MiB外单独限界。实际T01–T08负例、宿主canary、控制器readback、任务成员／停止与清理事实决定资格，未观察、拒绝、跳过或未知不当作通过。

本轮不接Job/Catalog/SDK/domain、不更改原调用默认、不创建研究预算或finding。资格执行0research reservations／0replay-engine calls；原5/8/11、golden、PR94、已提交结果和未知reservation语义不变。未来产品集成需另冻结原槽前preflight、ACK短路、真实执行身份／资源、停止与发布fencing的完整映射，不能靠Popen替换冒充完成。

## 后果与验收

S13-02仍原16h，S13总10+16+8=34h及持续质量容量不变，不补造实际工时。先做真实参考资格，不能以配置文件存在、guest自报、普通CI绿色或AI自审认证隔离。缺能力时保留M0支持范围和明确缺口，不静默扩大故事或放宽门槛。

root仅在确认任务cgroup空后卸载自己scratch并移除空leaf；停止／清理不确定保留资源及诊断，不用lazy/force卸载、全局prune或删除调用者路径。当前同kernel／受信host的限定不等于一般kernel漏洞、恶意owner或多租户隔离保障。

M1产品入口在实际资格和足够独立安全复核前保持关闭；M2托管服务不支持。外部真人研究复验仍0/0/PENDING（#24 OPEN），独立安全复核另计。无新release、HTTP/MCP、GPU、自动合并或外发联系；全部项目／攻击执行仅在授权远端CPU。机制主源与具体证据门见合同，不把主源文档当作实际主机资格。
