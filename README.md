# XmiLogger

基于 Loguru 的增强日志记录器，支持多语言、异步操作、远程错误上报、统计与日志管理等能力。

## 特性

- 多语言输出（zh/en）
- 自定义格式、级别过滤、按大小或按时间轮转、保留策略、压缩
- request_id 上下文注入（ContextVar）
- 装饰器记录函数调用与耗时（同步/异步）
- 远程日志上报（默认仅 ERROR 及以上，异步发送避免阻塞）
- 基础统计（按级别/分类/小时）、缓存性能信息
- 日志管理（压缩、归档、清理）、简单分析与导出

## 安装

```bash
 pip install -U xmi_logger
```

## 快速开始

### 基本使用

```python
from xmi_logger import XmiLogger

# 创建日志记录器实例
logger = XmiLogger(
    file_name="app",
    log_dir="logs",
    language="zh"  # 使用中文输出
)

# 设置 request_id（每条日志会带 ReqID:xxx）
token = logger.request_id_var.set("req-001")
try:
    logger.info("这是一条信息日志")
    logger.warning("这是一条警告日志")
    logger.error("这是一条错误日志")
finally:
    logger.request_id_var.reset(token)

# 程序退出前清理（关闭远程发送、恢复 excepthook、移除 handler）
logger.cleanup()
```

#### request_id 用法与并发说明

`request_id_var` 是一个 `ContextVar`，用来给“同一条业务链路”的日志自动带上 `ReqID:...`：

- `set(value)`：把当前上下文的 request_id 设为 `value`，并返回一个 token（表示 set 之前的旧值）
- `reset(token)`：把当前上下文恢复到 set 之前的值，避免 request_id 泄漏到下一次请求/任务

推荐写法用 `try/finally` 确保一定 reset（如上例）。

多并发下的行为：

- 多线程：不同线程之间的 `request_id` 互不影响；但新线程不会自动继承父线程的 request_id，需要显式传递。
- asyncio：不同 Task 之间的 `request_id` 互不影响；创建 Task 时会复制一份当前上下文，所以要在 `create_task()` 之前 set。

线程/线程池中传递 request_id 的示例：

```python
import contextvars
import threading

token = logger.request_id_var.set("req-001")
try:
    ctx = contextvars.copy_context()
    t = threading.Thread(target=lambda: ctx.run(logger.info, "子线程日志也带 ReqID"))
    t.start()
    t.join()
finally:
    logger.request_id_var.reset(token)
```

asyncio 并发示例（每个请求独立 request_id）：

```python
import asyncio

async def handle(req_id: str):
    token = logger.request_id_var.set(req_id)
    try:
        logger.info("开始处理")
        await asyncio.sleep(0.1)
        logger.info("处理完成")
    finally:
        logger.request_id_var.reset(token)

async def main():
    await asyncio.gather(handle("req-1"), handle("req-2"))

asyncio.run(main())
```

### 异步函数支持

```python
import asyncio

@logger.log_decorator()
async def async_function():
    await asyncio.sleep(1)
    return "异步操作完成"

# 使用异步函数
async def main():
    result = await async_function()
    logger.info(f"异步函数结果: {result}")

asyncio.run(main())
```

### 增强错误信息

```python
# 错误日志现在会显示详细的位置信息
@logger.log_decorator("除零错误", level="ERROR")
def divide_numbers(a, b):
    return a / b

try:
    result = divide_numbers(1, 0)
except ZeroDivisionError:
    logger.exception("捕获到除零错误")
    # 输出示例：
    # 2025-01-03 10:30:15.123 | ERROR    | ReqID:REQ-123 | app.py:25:divide_numbers | 12345 | 除零错误 [ZeroDivisionError]: division by zero | 位置: app.py:25:divide_numbers | 代码: return a / b
    # 调用链: app.py:25:divide_numbers -> main.py:10:main
```

### 带位置信息的日志

```python
# 使用 log_with_location 方法记录带位置信息的日志
logger.log_with_location("INFO", "这是带位置信息的日志")
# 输出示例：
# 2025-01-03 10:30:15.123 | INFO     | ReqID:REQ-123 | app.py:30:main | 12345 | [app.py:30:main] 这是带位置信息的日志
```

### 性能监控

```python
import json

# 获取性能统计信息
perf_stats = logger.get_performance_stats()
print(json.dumps(perf_stats, indent=2))

# 清除缓存
logger.clear_caches()

# 性能优化配置
logger = XmiLogger(
    file_name="app",
    cache_size=512,        # 增加缓存大小
    enable_stats=True      # 启用统计功能
)
```

### 批量日志处理

```python
import asyncio

# 批量记录日志
batch_logs = [
    {'level': 'INFO', 'message': '消息1', 'tag': 'BATCH'},
    {'level': 'WARNING', 'message': '消息2', 'category': 'SYSTEM'},
    {'level': 'ERROR', 'message': '消息3'}
]

logger.batch_log(batch_logs)  # 同步批量记录
asyncio.run(logger.async_batch_log(batch_logs))  # 异步批量记录
```

### 上下文日志

```python
# 带上下文的日志记录
context = {
    'user_id': 12345,
    'session_id': 'sess_abc123',
    'request_id': 'req_xyz789'
}

logger.log_with_context("INFO", "用户登录", context)
logger.log_with_timing("INFO", "API请求完成", {'db_query': 0.125, 'total': 0.467})
```

### 自适应日志级别

```python
# 启用自适应级别
logger = XmiLogger(
    file_name="app",
    adaptive_level=True,    # 启用自适应级别
    enable_stats=True       # 自适应依赖统计
)

# 根据错误率/日志速率自动调整级别（需持续产生日志以更新统计）
logger.set_adaptive_level(error_rate_threshold=0.1)
```

### 日志管理

```python
# 压缩旧日志
logger.compress_logs(days_old=7)

# 归档日志
logger.archive_logs()

# 清理旧日志
logger.cleanup_old_logs(max_days=30)
```

### 日志分析

```python
# 分析日志
analysis = logger.analyze_logs(hours=24)
print(f"错误率: {analysis['error_rate']:.2%}")

# 生成报告
report = logger.generate_log_report(hours=24)
print(report)

# 导出日志
logger.export_logs_to_json("logs.json", hours=24)
```

### advanced_features（可选）

加密功能依赖 cryptography，性能监控的系统指标依赖 psutil：

```bash
pip install xmi_logger[advanced]
```

```python
import hashlib
import time
from datetime import datetime

from xmi_logger.advanced_features import (
    DistributedLogger,
    LogAggregator,
    LogAnalyzer,
    LogArchiver,
    LogBackupManager,
    LogDatabase,
    LogHealthChecker,
    LogSecurity,
    LogStreamProcessor,
    PerformanceMonitor,
)

# 智能日志分析（规则匹配）
analyzer = LogAnalyzer()
analysis = analyzer.analyze_log({
    'message': '数据库连接失败: Connection refused',
    'level': 'ERROR'
})
print(f"严重程度: {analysis['severity']}")
print(f"类别: {analysis['categories']}")
print(f"建议: {analysis['suggestions']}")

# 分布式日志 ID（跨进程重启也能递增）
dist_logger = DistributedLogger("node-001", persist_every=100)
log_id = dist_logger.get_log_id()
logger.info(f"分布式日志消息 (ID: {log_id})")

# 日志安全：脱敏（支持 password/token/api_key/密码/口令 等）
security = LogSecurity()
original = "用户密码: 123456, token=abcd"
sanitized = security.sanitize_message(original)
print(sanitized)

payload = {"user": "alice", "password": "123456", "nested": {"api_key": "k-xxx"}}
print(security.sanitize_mapping(payload))

# 性能监控
monitor = PerformanceMonitor()
monitor.record_log("INFO", 0.05)
metrics = monitor.get_metrics()
print(f"总日志数: {metrics['log_count']}")
print(f"平均处理时间: {metrics['avg_processing_time_ms']:.2f}ms")
monitor.stop()

# 日志聚合（去重合并重复日志）
aggregator = LogAggregator(window_size=100, flush_interval=5.0)
for i in range(20):
    aggregator.add_log({
        'level': 'INFO',
        'message': '重复的日志消息',
        'timestamp': time.time()
    })
aggregated = aggregator.flush()
print(aggregated[0]["message"])
aggregator.stop()

# 流处理（管道式加工日志 entry）
processor = LogStreamProcessor(max_queue_size=1000)

def add_timestamp(log_entry):
    log_entry['processed_timestamp'] = time.time()
    return log_entry

def add_checksum(log_entry):
    message = log_entry.get('message', '')
    log_entry['checksum'] = hashlib.md5(message.encode()).hexdigest()[:8]
    return log_entry

processor.add_processor(add_timestamp)
processor.add_processor(add_checksum)

# 处理日志
processor.process_log({'level': 'INFO', 'message': '测试消息'})
processed_log = processor.get_processed_log(timeout=1.0)
processor.stop()

# SQLite 数据库存储（结构化落库 + 条件查询）
db = LogDatabase("logs.db")
db.insert_log({
    'timestamp': datetime.now().isoformat(),
    'level': 'ERROR',
    'message': '数据库连接失败',
    'file': 'app.py',
    'line': 100,
    'function': 'connect_db'
})

# 查询错误日志
logs = db.query_logs({'level': 'ERROR'}, limit=10)
db.close()

# 健康检查
checker = LogHealthChecker()
health = checker.check_health("logs")
print(f"状态: {health['status']}")
print(f"磁盘使用率: {health['disk_usage_percent']:.1f}%")

# 安全备份/恢复（防止 tar 路径穿越）
backup_mgr = LogBackupManager("backups")
backup_path = backup_mgr.create_backup("logs", "daily_backup")

# 列出备份
backups = backup_mgr.list_backups()
for backup in backups:
    print(f"{backup['name']} - {backup['size_mb']:.2f}MB")

# 日志归档（压缩并移到 archives 目录）
archiver = LogArchiver("archives")
archived_files = archiver.archive_logs("logs", days_old=7, compression_type="gzip")
print(f"归档了 {len(archived_files)} 个文件")
```

### 远程日志收集

```python
logger = XmiLogger(
    file_name="app",
    remote_log_url="https://your-log-server.com/logs",
    max_workers=3
)
```

### 日志统计功能

```python
# 启用统计功能
logger = XmiLogger(
    file_name="app",
    enable_stats=True
)

# 获取统计信息
stats = logger.get_stats()
print(logger.get_stats_summary())

# 获取错误趋势
error_trend = logger.get_error_trend()

# 获取分类分布
category_dist = logger.get_category_distribution()
```

## 高级配置

### 完整配置示例

```python
logger = XmiLogger(
    file_name="app",                    # 日志文件名
    log_dir="logs",                     # 日志目录
    max_size=14,                        # 单个日志文件最大大小（MB）
    retention="7 days",                 # 日志保留时间
    remote_log_url=None,                # 远程日志服务器URL
    max_workers=3,                      # 远程日志发送线程数
    work_type=False,                    # 工作模式（False为测试环境）
    language="zh",                      # 日志语言（zh/en）
    rotation_time="1 day",              # 日志轮转时间
    custom_format=None,                 # 自定义日志格式
    filter_level="DEBUG",               # 日志过滤级别
    compression="zip",                  # 日志压缩格式
    enable_stats=False,                 # 是否启用统计
    categories=None,                    # 日志分类列表
    cache_size=128,                     # 缓存大小
    adaptive_level=False,               # 自适应日志级别
    performance_mode=False,             # 性能模式（配合 enable_performance_mode/disable_performance_mode）
    enable_exception_hook=False         # 是否接管 sys.excepthook
)
```

### 自定义日志格式

```python
custom_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "ReqID:{extra[request_id]} | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

logger = XmiLogger(
    file_name="app",
    custom_format=custom_format
)
```

## 主要功能

### 1. 日志记录
- 支持所有标准日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
- 支持自定义日志级别
- 支持带标签和分类的日志记录

### 2. 日志管理
- 自动日志轮转
- 日志压缩
- 日志保留策略
- 多文件输出（按级别分文件）

### 3. 统计功能
- 日志总数统计
- 错误率统计
- 按类别统计
- 按时间统计
- 错误趋势分析

### 4. 远程日志
- 异步远程日志发送
- 自动重试机制
- 线程池管理
- 错误处理

### 5. 装饰器支持
- 函数执行时间记录
- 异常捕获和记录
- 支持同步和异步函数

### 6. 增强错误信息
- 显示错误发生的具体文件、行号和函数名
- 显示错误发生时的代码行内容
- 显示调用链信息（最后3层调用）
- 支持全局异常处理器
- 提供带位置信息的日志记录方法

### 7. 性能优化
- 智能缓存机制减少重复计算
- 连接池优化网络请求性能
- 内存优化减少对象创建
- 统计缓存提高查询效率
- 线程本地缓存提升并发性能

### 8. 高级功能
- 批量日志处理提高大量日志记录性能
- 上下文日志自动添加相关上下文信息
- 自适应级别根据系统状态自动调整日志级别
- 日志管理压缩、归档、清理功能
- 日志分析智能分析日志内容和趋势
- 性能监控实时监控缓存和性能指标

### 9. 智能分析功能
- 智能日志分析自动识别错误、警告、安全事件
- 分布式日志支持多节点环境，提供唯一日志ID
- 日志安全功能敏感信息清理和加密
- 性能监控实时监控系统资源使用
- 日志聚合自动聚合重复日志
- 流处理可扩展的日志处理管道
- 数据库支持结构化日志存储和查询
- 健康检查系统状态监控
- 备份管理自动备份和恢复
- 内存优化智能垃圾回收
- 智能路由基于条件的日志分发
- 日志归档自动压缩和归档

## 错误处理

```python
try:
    logger = XmiLogger("app", log_dir="/path/to/logs")
except RuntimeError as e:
    print(f"日志配置失败: {e}")
```

## 注意事项

1. 确保日志目录具有写入权限
2. 远程日志URL必须是有效的HTTP(S)地址
3. 建议在生产环境中启用统计功能
4. 异步操作时注意正确处理异常

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
