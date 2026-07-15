# SQLite 备份 Runbook

备份前执行：

```powershell
python scripts/local_health.py
python scripts/verify_database.py --database data/worldpulse.db
```

创建备份：

```powershell
python scripts/backup_database.py --source data/worldpulse.db --output data/backups/worldpulse.backup.db
```

备份应包含 WAL 已提交内容，并在恢复演练中再次运行 `verify_database.py`。不要把 `data/*.db`、WAL、日志或备份文件提交到 Git。恢复后先启动 API，再使用 worker `--once` 处理一个非生产演练 job，检查 lifecycle health、artifact integrity 和 Replay Pack。
