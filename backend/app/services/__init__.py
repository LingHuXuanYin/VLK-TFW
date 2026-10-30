"""服务实现层：一个文件一个业务能力。

- device.py           设备解析（auto → cuda:0 / cpu）
- task_catalog.py     七任务元数据（唯一数据源）
- image_store.py      图片落盘 / 缩放 / 候选框缓存
- wedetect_source.py  WeDetect 候选框生成
- model_runtime.py    模型加载与状态机（唯一持有进程级状态）
- task_runner.py      单任务：校验 + 派发 + 警告
- suite_runner.py     全量：串行编排七个任务
"""
