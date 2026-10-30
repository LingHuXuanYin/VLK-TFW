"""Taozi VLX 调测台后端。

分层（依赖单向，禁止反向 import）：
    config / schemas / errors
        ↓
    protocols（纯接口定义）
        ↓
    services（业务实现）
        ↓
    deps（组装根：单例）
        ↓
    routers（HTTP 绑定）
        ↓
    main（应用组装）
"""
