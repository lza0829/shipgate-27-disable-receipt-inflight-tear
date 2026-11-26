# 发版闸（Shipgate）

骨架：发版申请入闸 → 环境晋升裁决 → 放行/回滚窗 → 发布结果对账

- 前端 http://127.0.0.1:6800
- API http://127.0.0.1:11800
- 数据库环境变量 `SHIPGATE_DB`（容器内默认 `/data/shipgate.db`）

```bash
docker compose up -d --build
```
