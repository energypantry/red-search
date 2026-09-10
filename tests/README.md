# 测试（默认全部离线，不发起网络请求）

```bash
pip install -e ".[dev]"
pytest -q
```

需要真实网络的自检（会发起少量只读请求）：

```bash
xhs doctor
xhs search "咖啡" 20          # 需要先跑过 xhs cookies / xhs fp
```
