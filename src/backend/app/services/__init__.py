"""服务实现层：一个文件一个业务能力。

- device.py           设备解析（auto → cuda:0 / cpu）
- task_catalog.py     七任务元数据（唯一数据源）
- image_store.py      图片落盘 / 缩放 / 候选框缓存（按围栏指纹分文件）
- fence.py            电子围栏几何：归一化 / 裁剪框 / 面积 / 过滤 / 灰化
- wedetect_source.py  WeDetect 候选框生成（支持围栏裁剪推理）
- model_runtime.py    模型加载与状态机（唯一持有进程级状态）
- task_runner.py      单任务：校验 + 派发 + 警告
- suite_runner.py     全量：串行编排七个任务
- job_spool.py        排队缓冲：未处理的图落 data/image_queue/，失败件移 failed/
- job_queue.py        生产消费队列：落盘入队、单消费者串行跑、重启恢复、结果留存
"""
