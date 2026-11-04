# 接线与联调指南

最新同步复查见[本轮交接](REVIEW_20261104_SYNC.md),下一阶段见[P2-5说明](P2_5_BASE_INTEGRATION/explain.yaml)。

2026-11-04进度与上限位正式释放流程见[最新交接](PROGRESS_20261104.md)。

Kvaser兼容USB-CAN的最新接入流程见同目录KVASER_SOCKETCAN.md；
旧PDF按先前candleLight方案编写，驱动步骤以新指南及实际USB/接口诊断为准。

本目录的PDF对应本包0.1.0版本，按2026-10-18已知实物信息生成。

必须先核对滤波器直流适用性、支路保护、上下限位、反馈精度和传动换算。
X5为必接动力电源；手册注明X3外部24V逻辑电源可不接。
首次使用保持config/lift.yaml默认只读，先做模拟与只读通信验证。
