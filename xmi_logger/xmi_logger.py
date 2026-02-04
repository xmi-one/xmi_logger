#!/usr/bin/env python
# -*- coding:utf-8 -*-

# Author: zhibo.wang
# E-mail: gm.zhibo.wang@gmail.com
# Date  : 2025-01-03
# Desc  : Enhanced Logger with Loguru (with async support) + Language Option

import os
import sys
import time
import inspect
import requests
import asyncio
import aiohttp

from typing import Optional, Dict, Any, List, Tuple

from functools import wraps
from time import perf_counter
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timedelta
import threading

from loguru import logger


class XmiLogger:
    """
    基于 Loguru 的增强日志记录器，具有以下功能：
    - 自定义日志格式
    - 日志轮转和保留策略
    - 上下文信息管理(如 request_id)
    - 远程日志收集(使用线程池防止阻塞)
    - 装饰器用于记录函数调用和执行时间，支持同步/异步函数
    - 自定义日志级别(避免与 Loguru 预定义的冲突)
    - 统一异常处理

    新增：
    - 可指定语言(中文/英文)，默认中文
    - 支持按时间轮转日志
    - 支持自定义日志格式
    - 支持日志级别过滤
    - 支持自定义压缩格式
    - 支持自定义文件命名模式
    """

    # 在 _LANG_MAP 中添加新的语言项
    _LANG_MAP = {
        'zh': {
            'LOG_STATS': "日志统计: 总计 {total} 条, 错误 {error} 条, 警告 {warning} 条, 信息 {info} 条",
            'LOG_TAGGED': "[{tag}] {message}",
            'LOG_CATEGORY': "分类: {category} - {message}",
            'UNHANDLED_EXCEPTION': "未处理的异常",
            'FAILED_REMOTE': "远程日志发送失败: {error}",
            'START_FUNCTION_CALL': "开始函数调用",
            'END_FUNCTION_CALL': "结束函数调用",
            'START_ASYNC_FUNCTION_CALL': "开始异步函数调用",
            'END_ASYNC_FUNCTION_CALL': "结束异步函数调用",
            'CALLING_FUNCTION': "调用函数: {func}，参数: {args}，关键字参数: {kwargs}",
            'CALLING_ASYNC_FUNCTION': "调用异步函数: {func}，参数: {args}，关键字参数: {kwargs}",
            'FUNCTION_RETURNED': "函数 {func} 返回结果: {result}，耗时: {duration}秒",
            'ASYNC_FUNCTION_RETURNED': "异步函数 {func} 返回结果: {result}，耗时: {duration}秒",
        },
        'en': {
            'LOG_STATS': "Log statistics: Total {total}, Errors {error}, Warnings {warning}, Info {info}",
            'LOG_TAGGED': "[{tag}] {message}",
            'LOG_CATEGORY': "Category: {category} - {message}",
            'UNHANDLED_EXCEPTION': "Unhandled exception",
            'FAILED_REMOTE': "Remote logging failed: {error}",
            'START_FUNCTION_CALL': "Starting function call",
            'END_FUNCTION_CALL': "Ending function call",
            'START_ASYNC_FUNCTION_CALL': "Starting async function call",
            'END_ASYNC_FUNCTION_CALL': "Ending async function call",
            'CALLING_FUNCTION': "Calling function: {func}, args: {args}, kwargs: {kwargs}",
            'CALLING_ASYNC_FUNCTION': "Calling async function: {func}, args: {args}, kwargs: {kwargs}",
            'FUNCTION_RETURNED': "Function {func} returned: {result}, duration: {duration}s",
            'ASYNC_FUNCTION_RETURNED': "Async function {func} returned: {result}, duration: {duration}s",
        }
    }

    def __init__(
        self,
        file_name: str,
        log_dir: str = 'logs',
        max_size: int = 14,                    # 单位：MB
        retention: str = '7 days',
        remote_log_url: Optional[str] = None,
        max_workers: int = 3,
        work_type: bool = False,
        language: str = 'zh',                  # 语言选项，默认为中文
        rotation_time: Optional[str] = None,   # 新增：按时间轮转，如 "1 day", "1 week"
        custom_format: Optional[str] = None,   # 新增：自定义日志格式
        filter_level: str = "DEBUG",           # 新增：日志过滤级别
        compression: str = "zip",              # 新增：压缩格式，支持 zip, gz, tar
        enable_stats: bool = False,            # 新增：是否启用日志统计
        categories: Optional[list] = None,     # 新增：日志分类列表
        cache_size: int = 128,                 # 新增：缓存大小配置
        adaptive_level: bool = False,          # 新增：自适应日志级别
        performance_mode: bool = False,        # 新增：性能模式
        enable_exception_hook: bool = False,
    ) -> None:
        """
        初始化日志记录器。

        Args:
            file_name (str): 日志文件名称(主日志文件前缀)。
            log_dir (str): 日志文件目录。
            max_size (int): 日志文件大小(MB)超过时进行轮转。
            retention (str): 日志保留策略。
            remote_log_url (str, optional): 远程日志收集的URL。如果提供，将启用远程日志收集。
            max_workers (int): 线程池的最大工作线程数。
            work_type (bool): False 测试环境
            language (str): 'zh' 或 'en'，表示日志输出语言，默认为中文。
        """
        self.file_name = file_name
        self.log_dir = log_dir
        self.max_size = max_size
        self.retention = retention
        self.remote_log_url = remote_log_url
        
        # 保存新增的参数为实例属性
        self.rotation_time = rotation_time
        self.custom_format = custom_format
        self.filter_level = filter_level
        self.compression = compression
        self.enable_stats = enable_stats
        self.categories = categories or []
        self._cache_size = cache_size
        self._format_cache: Dict[Any, str] = {}
        self._message_cache: Dict[Any, str] = {}
        self._location_cache: Dict[Any, str] = {}
        self._stats_cache: Dict[str, Any] = {}
        self._stats_cache_time = 0.0
        self._stats_cache_ttl = 5
        self.adaptive_level = adaptive_level
        self.performance_mode = performance_mode
        self._handler_ids: List[int] = []
        self._removed_default_handler = False
        self._exception_hook_enabled = bool(enable_exception_hook)
        self._exception_hook = None
        self._prev_excepthook = None
        self._remote_loop = None
        self._remote_thread = None
        self._remote_queue = None
        self._remote_ready = threading.Event()

        # 语言选项
        self.language = language if language in ('zh', 'en') else 'zh'

        # 定义上下文变量，用于存储 request_id
        self.request_id_var = ContextVar("request_id", default="no-request-id")

        # 使用 patch 确保每条日志记录都包含 'request_id'
        self.logger = logger.patch(
            lambda record: record["extra"].update(
                request_id=self.request_id_var.get() or "no-request-id"
            )
        )
        if work_type:
            self.enqueue = False
            self.diagnose = False
            self.backtrace = False
        else:
            self.enqueue = True
            self.diagnose = True
            self.backtrace = True

        # 用于远程日志发送的线程池
        self._max_workers = max_workers
        self._executor = None
        if self.remote_log_url:
            self._executor = ThreadPoolExecutor(max_workers=max_workers)
            self._start_remote_sender()

        # 初始化 Logger 配置
        self.configure_logger()

        self._stats_lock = threading.Lock()
        self._stats = {
            'total': 0,
            'error': 0,
            'warning': 0,
            'info': 0,
            'debug': 0,
            'by_category': defaultdict(int),
            'by_hour': defaultdict(int),
            'errors': [],
            'last_error_time': None,
            'error_rate': 0.0
        }
        self._stats_start_time = datetime.now()

    def _msg(self, key: str, **kwargs) -> str:
        """消息格式化处理，优化性能"""
        try:
            # 获取消息模板
            text = self._LANG_MAP.get(self.language, {}).get(key, key)
            
            # 如果没有参数，直接返回模板
            if not kwargs:
                cache_key = (self.language, key, None)
                if cache_key in self._message_cache:
                    return self._message_cache[cache_key]
                self._message_cache[cache_key] = text
                return text
            
            # 优化参数转换
            str_kwargs = {}
            for k, v in kwargs.items():
                try:
                    if isinstance(v, (list, tuple)):
                        str_kwargs[k] = tuple(str(item) for item in v)
                    elif isinstance(v, dict):
                        str_kwargs[k] = {str(kk): str(vv) for kk, vv in v.items()}
                    else:
                        str_kwargs[k] = str(v)
                except Exception:
                    str_kwargs[k] = f"<{type(v).__name__}>"

            frozen_kwargs = tuple(
                sorted(
                    (k, tuple(sorted(v.items())) if isinstance(v, dict) else v)
                    for k, v in str_kwargs.items()
                )
            )
            cache_key = (self.language, key, frozen_kwargs)
            if cache_key in self._message_cache:
                return self._message_cache[cache_key]
            
            # 格式化消息
            result = text.format(**str_kwargs)
            
            # 缓存结果
            self._message_cache[cache_key] = result
            
            # 限制缓存大小
            if len(self._message_cache) > self._cache_size:
                # 清除最旧的缓存项
                oldest_key = next(iter(self._message_cache))
                del self._message_cache[oldest_key]
            
            return result
            
        except KeyError as e:
            text = self._LANG_MAP.get(self.language, {}).get(key, key)
            return f"{text} (格式化错误: 缺少参数 {e})"
        except Exception as e:
            text = self._LANG_MAP.get(self.language, {}).get(key, key)
            return f"{text} (格式化错误: {str(e)})"

    def _remove_handlers(self) -> None:
        handler_ids = list(self._handler_ids)
        self._handler_ids.clear()
        for handler_id in handler_ids:
            try:
                self.logger.remove(handler_id)
            except Exception:
                continue

    def configure_logger(self) -> None:
        """配置日志记录器，添加错误处理和安全性检查"""
        try:
            self._remove_handlers()
            if not self._removed_default_handler:
                try:
                    self.logger.remove(0)
                except Exception:
                    pass
                self._removed_default_handler = True
            
            # 验证配置参数
            self._validate_config()
            
            # 确保日志目录存在且可写
            self._ensure_log_directory()
            
            # 配置日志格式
            log_format = self._get_log_format()
            
            # 添加控制台处理器
            self._add_console_handler(log_format)
            
            # 添加文件处理器
            self._add_file_handlers(log_format)
            
            # 配置远程日志(如果启用)
            if self.remote_log_url:
                self._configure_remote_logging()
            
            # 设置异常处理器
            if self._exception_hook_enabled:
                self.setup_exception_handler()
            
        except Exception as e:
            # 如果配置失败，使用基本配置
            self._fallback_configuration()
            raise RuntimeError(f"日志配置失败: {str(e)}")
    
    def _validate_config(self) -> None:
        """验证配置参数"""
        if not isinstance(self.max_size, int) or self.max_size <= 0:
            raise ValueError("max_size 必须是正整数")
        
        if not isinstance(self.retention, str):
            raise ValueError("retention 必须是字符串")
        
        if self.remote_log_url and not self.remote_log_url.startswith(('http://', 'https://')):
            raise ValueError("remote_log_url 必须是有效的 HTTP(S) URL")
        
        if self.language not in ('zh', 'en'):
            raise ValueError("language 必须是 'zh' 或 'en'")
        
        if self.compression not in ('zip', 'gz', 'tar'):
            raise ValueError("compression 必须是 'zip', 'gz' 或 'tar'")
    
    def _ensure_log_directory(self) -> None:
        """确保日志目录存在且可写"""
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            # 测试目录是否可写
            test_file = os.path.join(self.log_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except (OSError, IOError) as e:
            raise RuntimeError(f"无法创建或写入日志目录: {str(e)}")
    
    def _get_log_format(self) -> str:
        """获取日志格式"""
        if self.custom_format:
            return self.custom_format
        
        return (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "ReqID:{extra[request_id]} | "
            "<cyan>{file}</cyan>:<cyan>{line}</cyan> | "
            "<magenta>{process}</magenta> | "
            "<level>{message}</level>"
        )
    
    def _add_console_handler(self, log_format: str) -> None:
        """添加控制台处理器"""
        handler_id = self.logger.add(
            sys.stdout,
            format=log_format,
            level=self.filter_level,
            enqueue=self.enqueue,
            diagnose=self.diagnose,
            backtrace=self.backtrace,
        )
        self._handler_ids.append(handler_id)
    
    def _add_file_handlers(self, log_format: str) -> None:
        """添加文件处理器"""
        # 主日志文件
        handler_id = self.logger.add(
            os.path.join(self.log_dir, f"{self.file_name}.log"),
            format=log_format,
            level=self.filter_level,
            rotation=self.rotation_time or f"{self.max_size} MB",
            retention=self.retention,
            compression=self.compression,
            encoding='utf-8',
            enqueue=self.enqueue,
            diagnose=self.diagnose,
            backtrace=self.backtrace,
        )
        self._handler_ids.append(handler_id)
        
        # 错误日志文件
        handler_id = self.logger.add(
            self._get_level_log_path("error"),
            format=log_format,
            level="ERROR",
            rotation=f"{self.max_size} MB",
            retention=self.retention,
            compression=self.compression,
            encoding='utf-8',
            enqueue=self.enqueue,
            diagnose=self.diagnose,
            backtrace=self.backtrace,
        )
        self._handler_ids.append(handler_id)
    
    def _fallback_configuration(self) -> None:
        """配置失败时的后备方案"""
        self._remove_handlers()
        handler_id = self.logger.add(
            sys.stderr,
            format="<red>{time:YYYY-MM-DD HH:mm:ss}</red> | <level>{level: <8}</level> | <level>{message}</level>",
            level="ERROR"
        )
        self._handler_ids.append(handler_id)

    def _configure_remote_logging(self):
        """
        配置远程日志收集。
        """
        # 当远程日志收集启用时，只发送 ERROR 及以上级别的日志
        handler_id = self.logger.add(
            self.remote_sink,
            level="ERROR",
            enqueue=self.enqueue,
        )
        self._handler_ids.append(handler_id)

    def log_with_tag(self, level: str, message: str, tag: str):
        """
        使用标签记录日志消息。
        
        Args:
            level: 日志级别 (info, debug, warning, error, critical)
            message: 日志消息
            tag: 标签名称
        """
        self._update_stats(level)
        logger_opt = self.logger.opt(depth=1)
        log_method = getattr(logger_opt, level.lower(), logger_opt.info)
        tagged_message = self._msg('LOG_TAGGED', tag=tag, message=message)
        log_method(tagged_message)
    
    def log_with_category(self, level: str, message: str, category: str):
        """
        使用分类记录日志消息。
        
        Args:
            level: 日志级别 (info, debug, warning, error, critical)
            message: 日志消息
            category: 分类名称
        """
        self._update_stats(level, category=category)
        logger_opt = self.logger.opt(depth=1)
        log_method = getattr(logger_opt, level.lower(), logger_opt.info)
        categorized_message = self._msg('LOG_CATEGORY', category=category, message=message)
        log_method(categorized_message)
    
    def setup_exception_handler(self):
        """
        设置统一的异常处理函数，将未处理的异常记录到日志。
        """
        def exception_handler(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                # 允许程序被 Ctrl+C 中断
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            try:
                # 获取调用栈信息
                import traceback
                tb = traceback.extract_tb(exc_traceback)
                
                # 安全地格式化异常信息
                error_msg = self._msg('UNHANDLED_EXCEPTION') if 'UNHANDLED_EXCEPTION' in self._LANG_MAP[self.language] else "未处理的异常"
                
                # 安全地格式化异常值
                exc_value_str = str(exc_value) if exc_value is not None else "None"
                
                # 获取错误发生的具体位置
                if tb:
                    # 获取最后一个调用帧(通常是错误发生的地方)
                    last_frame = tb[-1]
                    error_location = f"{last_frame.filename}:{last_frame.lineno}:{last_frame.name}"
                    line_content = last_frame.line.strip() if last_frame.line else "未知代码行"
                else:
                    error_location = "未知位置"
                    line_content = "未知代码行"
                
                # 组合详细的错误消息
                full_error_msg = (
                    f"{error_msg}: {exc_type.__name__}: {exc_value_str} | "
                    f"位置: {error_location} | "
                    f"代码: {line_content}"
                )
                
                # 记录详细错误信息
                self.logger.opt(exception=True).error(full_error_msg)
                
                # 记录调用链信息
                if len(tb) > 1:
                    call_chain = []
                    for frame in tb[-3:]:  # 只显示最后3层调用
                        call_chain.append(f"{frame.filename}:{frame.lineno}:{frame.name}")
                    self.logger.error(f"调用链: {' -> '.join(call_chain)}")
                    
            except Exception as e:
                # 如果格式化失败，使用最基本的错误记录
                self.logger.opt(exception=True).error(f"未处理的异常: {exc_type.__name__}")

        if self._prev_excepthook is None:
            self._prev_excepthook = sys.excepthook
        self._exception_hook = exception_handler
        sys.excepthook = exception_handler

    def _get_level_log_path(self, level_name):
        """
        获取不同级别日志文件的路径。
        """
        return os.path.join(self.log_dir, f"{self.file_name}_{level_name}.log")

    def get_log_path(self, message):
        """
        如果需要将所有日志按照级别分文件时，可使用此方法。
        """
        log_level = message.record["level"].name.lower()
        log_file = f"{log_level}.log"
        return os.path.join(self.log_dir, log_file)

    def _start_remote_sender(self) -> None:
        if self._remote_thread and self._remote_thread.is_alive():
            return

        def remote_thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            queue = asyncio.Queue()

            async def remote_worker():
                connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
                timeout = aiohttp.ClientTimeout(total=5)
                session = aiohttp.ClientSession(connector=connector, timeout=timeout)
                try:
                    while True:
                        payload = await queue.get()
                        if payload is None:
                            queue.task_done()
                            break
                        try:
                            await self._post_remote_payload(session, payload)
                        finally:
                            queue.task_done()
                finally:
                    try:
                        await session.close()
                    except Exception:
                        pass
                    loop.stop()

            self._remote_loop = loop
            self._remote_queue = queue
            self._remote_ready.set()
            loop.create_task(remote_worker())
            loop.run_forever()
            try:
                loop.close()
            except Exception:
                pass

        self._remote_ready.clear()
        self._remote_thread = threading.Thread(target=remote_thread_target, daemon=True)
        self._remote_thread.start()
        self._remote_ready.wait(timeout=2)

    async def _post_remote_payload(self, session: aiohttp.ClientSession, payload: Dict[str, Any]) -> None:
        for attempt in range(3):
            try:
                async with session.post(
                    self.remote_log_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
                    return
            except Exception as e:
                if attempt == 2:
                    self.logger.warning(self._msg('FAILED_REMOTE', error=f"最终尝试失败: {e}"))
                    return
                await asyncio.sleep(1 * (attempt + 1))

    def _build_remote_payload(self, message: Any) -> Dict[str, Any]:
        log_entry = message.record
        try:
            time_str = log_entry["time"].strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            time_str = str(log_entry.get("time"))

        file_path = ""
        file_obj = log_entry.get("file")
        if file_obj:
            try:
                file_path = os.path.basename(file_obj.path)
            except Exception:
                file_path = str(file_obj)

        return {
            "time": time_str,
            "level": getattr(log_entry.get("level"), "name", str(log_entry.get("level"))),
            "message": log_entry.get("message", ""),
            "file": file_path,
            "line": log_entry.get("line"),
            "function": log_entry.get("function"),
            "request_id": log_entry.get("extra", {}).get("request_id", "no-request-id"),
        }

    def remote_sink(self, message):
        payload = self._build_remote_payload(message)
        if self._remote_loop and self._remote_queue and self._remote_ready.is_set():
            try:
                self._remote_loop.call_soon_threadsafe(self._remote_queue.put_nowait, payload)
                return
            except Exception:
                pass
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._executor.submit(self._send_payload_sync, payload)

    def _stop_remote_sender(self) -> None:
        loop = self._remote_loop
        queue = self._remote_queue
        thread = self._remote_thread
        if loop and queue and thread and thread.is_alive():
            try:
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception:
                pass
            thread.join(timeout=2)
        self._remote_loop = None
        self._remote_queue = None
        self._remote_thread = None
        self._remote_ready.clear()

    def _send_payload_sync(self, payload: Dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json"}
        max_retries = 3
        retry_delay = 1
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.remote_log_url,
                    headers=headers,
                    json=payload,
                    timeout=5,
                )
                response.raise_for_status()
                return
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.warning(self._msg('FAILED_REMOTE', error=f"Final attempt failed: {e}"))
                else:
                    time.sleep(retry_delay * (attempt + 1))

    def add_custom_level(self, level_name, no, color, icon):
        """
        增加自定义日志级别。

        Args:
            level_name (str): 日志级别名称。
            no (int): 日志级别编号。
            color (str): 日志级别颜色。
            icon (str): 日志级别图标。
        """
        try:
            self.logger.level(level_name, no=no, color=color, icon=icon)
            self.logger.debug(f"Custom log level '{level_name}' added.")
        except TypeError:
            # 如果日志级别已存在，记录调试信息
            self.logger.debug(f"Log level '{level_name}' already exists, skipping.")

    def __getattr__(self, level: str):
        """
        使 MyLogger 支持直接调用 Loguru 的日志级别方法。

        Args:
            level (str): 日志级别方法名称。
        """
        logger_method = getattr(self.logger.opt(depth=1), level)
        return logger_method

    def log(self, level: str, message: str, *args, **kwargs):
        self._update_stats(level)
        return self.logger.opt(depth=1).log(level, message, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs):
        self._update_stats("DEBUG")
        return self.logger.opt(depth=1).debug(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        self._update_stats("INFO")
        return self.logger.opt(depth=1).info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self._update_stats("WARNING")
        return self.logger.opt(depth=1).warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self._update_stats("ERROR")
        return self.logger.opt(depth=1).error(message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        self._update_stats("CRITICAL")
        return self.logger.opt(depth=1).critical(message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs):
        self._update_stats("ERROR")
        return self.logger.opt(depth=1).exception(message, *args, **kwargs)

    def log_decorator(self, msg: Optional[str] = None, level: str = "ERROR", trace: bool = True):
        """
        增强版日志装饰器，支持自定义日志级别和跟踪配置

        Args:
            msg (str): 支持多语言的异常提示信息key(使用_LANG_MAP中的键)
            level (str): 记录异常的日志级别(默认ERROR)
            trace (bool): 是否记录完整堆栈跟踪(默认True)
        """
        def decorator(func):
            _msg_key = msg or 'UNHANDLED_EXCEPTION'
            log_level = level.upper()

            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    self._log_start(func.__name__, args, kwargs, is_async=True)
                    start_time = perf_counter()
                    try:
                        result = await func(*args, **kwargs)
                        duration = perf_counter() - start_time
                        self._log_end(func.__name__, result, duration, is_async=True)
                        return result
                    except Exception as e:
                        self._log_exception(func.__name__, e, _msg_key, log_level, trace, is_async=True)
                        if trace:
                            raise
                        return None
                return async_wrapper
            else:
                @wraps(func)
                def sync_wrapper(*args, **kwargs):
                    self._log_start(func.__name__, args, kwargs, is_async=False)
                    start_time = perf_counter()
                    try:
                        result = func(*args, **kwargs)
                        duration = perf_counter() - start_time
                        self._log_end(func.__name__, result, duration, is_async=False)
                        return result
                    except Exception as e:
                        self._log_exception(func.__name__, e, _msg_key, log_level, trace, is_async=False)
                        if trace:
                            raise
                        return None
                return sync_wrapper
        return decorator

    def _log_exception(self, func_name: str, error: Exception, msg_key: str,
                     level: str, trace: bool, is_async: bool):
        """统一的异常记录处理，增强错误信息显示"""
        try:
            log_method = getattr(self.logger, level.lower(), self.logger.error)
            
            # 获取调用栈信息
            import traceback
            tb = traceback.extract_tb(error.__traceback__)
            
            # 安全地获取消息
            error_msg = self._msg(msg_key) if msg_key in self._LANG_MAP[self.language] else f"发生异常: {msg_key}"
            
            # 安全地格式化错误信息
            error_type = type(error).__name__
            error_value = str(error) if error is not None else "None"
            
            # 获取错误发生的具体位置
            if tb:
                # 获取最后一个调用帧(通常是错误发生的地方)
                last_frame = tb[-1]
                error_location = f"{last_frame.filename}:{last_frame.lineno}:{last_frame.name}"
                line_content = last_frame.line.strip() if last_frame.line else "未知代码行"
            else:
                error_location = "未知位置"
                line_content = "未知代码行"
            
            # 组合详细的错误消息
            full_error_msg = (
                f"{error_msg} [{error_type}]: {error_value} | "
                f"位置: {error_location} | "
                f"代码: {line_content}"
            )

            if trace:
                # 记录详细错误消息
                log_method(full_error_msg)
                # 记录完整的异常堆栈
                self.logger.opt(exception=True).error("完整异常堆栈:")
                
                # 记录调用链信息
                if len(tb) > 1:
                    call_chain = []
                    for frame in tb[-3:]:  # 只显示最后3层调用
                        call_chain.append(f"{frame.filename}:{frame.lineno}:{frame.name}")
                    self.logger.error(f"调用链: {' -> '.join(call_chain)}")
            else:
                log_method(full_error_msg)

            # 记录函数调用结束
            end_msg = self._msg('END_ASYNC_FUNCTION_CALL' if is_async else 'END_FUNCTION_CALL')
            self.logger.info(end_msg)
            
        except Exception as e:
            # 如果格式化失败，使用最基本的错误记录
            self.logger.error(f"记录异常时发生错误: {str(e)}")
            if trace:
                self.logger.opt(exception=True).error("原始异常堆栈:")

    def _log_start(self, func_name, args, kwargs, is_async=False):
        """
        记录函数调用开始的公共逻辑。
        """
        def format_arg(arg):
            """优化的参数格式化函数"""
            try:
                if isinstance(arg, (str, int, float, bool)):
                    return str(arg)
                elif isinstance(arg, (list, tuple)):
                    return f"[{len(arg)} items]"
                elif isinstance(arg, dict):
                    return f"{{{len(arg)} items}}"
                else:
                    return str(arg)
            except Exception:
                return f"<{type(arg).__name__}>"

        # 安全地格式化参数
        args_str = [format_arg(arg) for arg in args]
        kwargs_str = {k: format_arg(v) for k, v in kwargs.items()}
        
        if is_async:
            self.logger.info(self._msg('START_ASYNC_FUNCTION_CALL'))
            self.logger.info(
                self._msg('CALLING_ASYNC_FUNCTION', 
                         func=func_name, 
                         args=args_str, 
                         kwargs=kwargs_str)
            )
        else:
            self.logger.info(self._msg('START_FUNCTION_CALL'))
            self.logger.info(
                self._msg('CALLING_FUNCTION', 
                         func=func_name, 
                         args=args_str, 
                         kwargs=kwargs_str)
            )

    def _log_end(self, func_name, result, duration, is_async=False):
        """
        记录函数调用结束的公共逻辑。
        """
        def format_result(res):
            """优化的结果格式化函数"""
            try:
                if isinstance(res, (str, int, float, bool)):
                    return str(res)
                elif isinstance(res, (list, tuple)):
                    return f"[{len(res)} items]"
                elif isinstance(res, dict):
                    return f"{{{len(res)} items}}"
                else:
                    return str(res)
            except Exception:
                return f"<{type(res).__name__}>"

        # 安全地格式化结果和持续时间
        result_str = format_result(result)
        duration_str = f"{duration:.6f}"  # 格式化持续时间为6位小数
        
        if is_async:
            self.logger.info(
                self._msg('ASYNC_FUNCTION_RETURNED', 
                         func=func_name, 
                         result=result_str, 
                         duration=duration_str)
            )
            self.logger.info(self._msg('END_ASYNC_FUNCTION_CALL'))
        else:
            self.logger.info(
                self._msg('FUNCTION_RETURNED', 
                         func=func_name, 
                         result=result_str, 
                         duration=duration_str)
            )
            self.logger.info(self._msg('END_FUNCTION_CALL'))
            
    def _update_stats(self, level: str, category: Optional[str] = None) -> None:
        """更新日志统计信息"""
        if not self.enable_stats:
            return
            
        with self._stats_lock:
            self._stats['total'] += 1
            self._stats[level.lower()] += 1
            
            if category:
                self._stats['by_category'][category] += 1
            
            current_hour = datetime.now().strftime('%Y-%m-%d %H:00')
            self._stats['by_hour'][current_hour] += 1
            
            if level.upper() == 'ERROR':
                self._stats['errors'].append({
                    'time': datetime.now(),
                    'message': f"Error occurred at {current_hour}"
                })
                self._stats['last_error_time'] = datetime.now()
                
                # 计算错误率
                if self._stats['total'] > 0:
                    self._stats['error_rate'] = self._stats['error'] / self._stats['total']
    
    def get_stats(self) -> Dict[str, Any]:
        """获取详细的日志统计信息，优化性能"""
        current_time = datetime.now()
        
        # 检查缓存是否有效
        if (current_time.timestamp() - self._stats_cache_time) < self._stats_cache_ttl:
            return self._stats_cache.copy()
        
        with self._stats_lock:
            stats = {
                'total': self._stats['total'],
                'error': self._stats['error'],
                'warning': self._stats['warning'],
                'info': self._stats['info'],
                'debug': self._stats['debug'],
                'duration': str(current_time - self._stats_start_time),
                'by_category': dict(self._stats['by_category']),
                'by_hour': dict(self._stats['by_hour']),
                'error_rate': float(self._stats['error_rate']),
                'time_since_last_error': str(current_time - self._stats['last_error_time']) if self._stats['last_error_time'] else None
            }
            
            # 计算每小时的平均日志数
            if stats['by_hour']:
                stats['avg_logs_per_hour'] = sum(stats['by_hour'].values()) / len(stats['by_hour'])
            
            # 获取最近的错误
            if self._stats['errors']:
                stats['recent_errors'] = [
                    {
                        'time': str(error['time']),
                        'message': str(error['message'])
                    }
                    for error in self._stats['errors'][-10:]
                ]
            
            # 更新缓存
            self._stats_cache = stats.copy()
            self._stats_cache_time = current_time.timestamp()
            
            return stats
    
    def get_stats_summary(self) -> str:
        """获取统计信息的摘要"""
        stats = self.get_stats()
        return self._msg('LOG_STATS',
            total=stats['total'],
            error=stats['error'],
            warning=stats['warning'],
            info=stats['info']
        )
    
    def get_error_trend(self) -> List[Tuple[str, int]]:
        """获取错误趋势数据"""
        with self._stats_lock:
            return sorted(
                [(hour, count) for hour, count in self._stats['by_hour'].items()],
                key=lambda x: x[0]
            )
    
    def get_category_distribution(self) -> Dict[str, int]:
        """获取日志分类分布"""
        with self._stats_lock:
            return dict(self._stats['by_category'])
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        with self._stats_lock:
            self._stats = {
                'total': 0,
                'error': 0,
                'warning': 0,
                'info': 0,
                'debug': 0,
                'by_category': defaultdict(int),
                'by_hour': defaultdict(int),
                'errors': [],
                'last_error_time': None,
                'error_rate': 0.0
            }
            self._stats_start_time = datetime.now()

    def get_current_location(self) -> str:
        """获取当前调用位置信息，优化性能"""
        try:
            frame = inspect.currentframe()
            if not frame:
                return "未知位置"
            caller = frame.f_back
            if caller and caller.f_code.co_name == "log_with_location":
                caller = caller.f_back
            if not caller:
                return "未知位置"
            filename = caller.f_code.co_filename
            lineno = caller.f_lineno
            function = caller.f_code.co_name
            return f"{filename}:{lineno}:{function}"
        except Exception:
            return "未知位置"
        finally:
            try:
                del frame
            except Exception:
                pass

    def log_with_location(self, level: str, message: str, include_location: bool = True):
        """带位置信息的日志记录"""
        self._update_stats(level)
        if include_location:
            location = self.get_current_location()
            full_message = f"[{location}] {message}"
        else:
            full_message = message
        
        logger_opt = self.logger.opt(depth=1)
        log_method = getattr(logger_opt, level.lower(), logger_opt.info)
        log_method(full_message)

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        return {
            'cache_sizes': {
                'message_cache': len(self._message_cache),
                'format_cache': len(self._format_cache),
                'location_cache': len(self._location_cache),
                'stats_cache': len(self._stats_cache)
            },
            'cache_hit_rates': {
                'message_cache_hits': getattr(self, '_message_cache_hits', 0),
                'location_cache_hits': getattr(self, '_location_cache_hits', 0),
                'stats_cache_hits': getattr(self, '_stats_cache_hits', 0)
            },
            'memory_usage': {
                'total_cache_size': (
                    len(self._message_cache) + 
                    len(self._format_cache) + 
                    len(self._location_cache) + 
                    len(self._stats_cache)
                )
            },
            'config': {
                'cache_size': self._cache_size,
                'stats_cache_ttl': self._stats_cache_ttl
            }
        }

    def clear_caches(self) -> None:
        """清除所有缓存"""
        self._message_cache.clear()
        self._format_cache.clear()
        self._location_cache.clear()
        self._stats_cache.clear()
        self._stats_cache_time = 0

    def batch_log(self, logs: List[Dict[str, Any]]) -> None:
        """批量记录日志，提高性能"""
        for log_entry in logs:
            level = log_entry.get('level', 'INFO')
            message = log_entry.get('message', '')
            tag = log_entry.get('tag')
            category = log_entry.get('category')
            
            if tag:
                self.log_with_tag(level, message, tag)
            elif category:
                self.log_with_category(level, message, category)
            else:
                self.log(level, message)

    async def async_batch_log(self, logs: List[Dict[str, Any]]) -> None:
        """异步批量记录日志"""
        for log_entry in logs:
            level = log_entry.get('level', 'INFO')
            message = log_entry.get('message', '')
            tag = log_entry.get('tag')
            category = log_entry.get('category')
            
            if tag:
                self.log_with_tag(level, message, tag)
            elif category:
                self.log_with_category(level, message, category)
            else:
                self.log(level, message)
            
            # 小延迟避免阻塞
            await asyncio.sleep(0.001)

    def log_with_context(self, level: str, message: str, context: Dict[str, Any] = None):
        """带上下文的日志记录"""
        self._update_stats(level)
        if context:
            context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
            full_message = f"{message} | {context_str}"
        else:
            full_message = message
        
        logger_opt = self.logger.opt(depth=1)
        log_method = getattr(logger_opt, level.lower(), logger_opt.info)
        log_method(full_message)

    def log_with_timing(self, level: str, message: str, timing_data: Dict[str, float]):
        """带计时信息的日志记录"""
        self._update_stats(level)
        timing_str = " | ".join([f"{k}={v:.3f}s" for k, v in timing_data.items()])
        full_message = f"{message} | {timing_str}"
        
        logger_opt = self.logger.opt(depth=1)
        log_method = getattr(logger_opt, level.lower(), logger_opt.info)
        log_method(full_message)

    def set_adaptive_level(self, error_rate_threshold: float = 0.1, 
                          log_rate_threshold: int = 1000) -> None:
        """设置自适应日志级别"""
        if not self.adaptive_level:
            return
        
        # 获取当前统计信息
        stats = self.get_stats()
        current_error_rate = stats.get('error_rate', 0.0)
        current_log_rate = stats.get('total', 0) / max(1, (datetime.now() - self._stats_start_time).total_seconds())
        
        # 根据错误率和日志频率调整级别
        if current_error_rate > error_rate_threshold or current_log_rate > log_rate_threshold:
            # 提高日志级别，减少日志输出
            if self.filter_level == "DEBUG":
                self.filter_level = "INFO"
                self._update_logger_level()
            elif self.filter_level == "INFO":
                self.filter_level = "WARNING"
                self._update_logger_level()
        else:
            # 降低日志级别，增加日志输出
            if self.filter_level == "WARNING":
                self.filter_level = "INFO"
                self._update_logger_level()
            elif self.filter_level == "INFO":
                self.filter_level = "DEBUG"
                self._update_logger_level()

    def _update_logger_level(self) -> None:
        """更新日志记录器级别"""
        try:
            self._remove_handlers()
            # 重新配置日志记录器
            self.configure_logger()
        except Exception as e:
            self.logger.warning(f"更新日志级别失败: {e}")

    def enable_performance_mode(self) -> None:
        """启用性能模式"""
        if self.performance_mode:
            # 减少日志输出
            self.filter_level = "WARNING"
            self._update_logger_level()
            # 增加缓存大小
            self._cache_size = min(self._cache_size * 2, 2048)
            # 禁用详细统计
            self.enable_stats = False

    def disable_performance_mode(self) -> None:
        """禁用性能模式"""
        if self.performance_mode:
            # 恢复日志级别
            self.filter_level = "INFO"
            self._update_logger_level()
            # 恢复缓存大小
            self._cache_size = max(self._cache_size // 2, 128)
            # 恢复统计功能
            self.enable_stats = True

    def compress_logs(self, days_old: int = 7) -> None:
        """压缩指定天数之前的日志文件"""
        import gzip
        import shutil
        from pathlib import Path
        
        log_path = Path(self.log_dir)
        current_time = datetime.now()
        
        for log_file in log_path.glob(f"{self.file_name}*.log"):
            try:
                # 检查文件修改时间
                file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                days_diff = (current_time - file_time).days
                
                if days_diff >= days_old and not log_file.name.endswith('.gz'):
                    # 压缩文件
                    with open(log_file, 'rb') as f_in:
                        gz_file = log_file.with_suffix('.log.gz')
                        with gzip.open(gz_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    
                    # 删除原文件
                    log_file.unlink()
                    self.logger.info(f"已压缩日志文件: {log_file.name}")
                    
            except Exception as e:
                self.logger.error(f"压缩日志文件失败 {log_file.name}: {e}")

    def archive_logs(self, archive_dir: str = None) -> None:
        """归档日志文件"""
        import shutil
        from pathlib import Path
        
        if archive_dir is None:
            archive_dir = os.path.join(self.log_dir, "archive")
        
        os.makedirs(archive_dir, exist_ok=True)
        log_path = Path(self.log_dir)
        
        for log_file in log_path.glob(f"{self.file_name}*.log"):
            try:
                # 移动文件到归档目录
                archive_file = Path(archive_dir) / log_file.name
                shutil.move(str(log_file), str(archive_file))
                self.logger.info(f"已归档日志文件: {log_file.name}")
                
            except Exception as e:
                self.logger.error(f"归档日志文件失败 {log_file.name}: {e}")

    def cleanup_old_logs(self, max_days: int = 30) -> None:
        """清理旧日志文件"""
        from pathlib import Path
        
        log_path = Path(self.log_dir)
        current_time = datetime.now()
        
        for log_file in log_path.glob(f"{self.file_name}*.log*"):
            try:
                # 检查文件修改时间
                file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                days_diff = (current_time - file_time).days
                
                if days_diff > max_days:
                    log_file.unlink()
                    self.logger.info(f"已删除旧日志文件: {log_file.name}")
                    
            except Exception as e:
                self.logger.error(f"删除旧日志文件失败 {log_file.name}: {e}")

    def analyze_logs(self, hours: int = 24) -> Dict[str, Any]:
        """分析指定时间范围内的日志"""
        from pathlib import Path
        import re
        
        log_path = Path(self.log_dir)
        current_time = datetime.now()
        start_time = current_time - timedelta(hours=hours)
        
        analysis = {
            'total_logs': 0,
            'error_count': 0,
            'warning_count': 0,
            'info_count': 0,
            'debug_count': 0,
            'error_rate': 0.0,
            'top_errors': [],
            'top_warnings': [],
            'hourly_distribution': defaultdict(int),
            'file_distribution': defaultdict(int),
            'function_distribution': defaultdict(int)
        }
        
        error_pattern = re.compile(r'ERROR.*?(\w+Error|Exception)', re.IGNORECASE)
        warning_pattern = re.compile(r'WARNING.*?(\w+Warning)', re.IGNORECASE)
        
        for log_file in log_path.glob(f"{self.file_name}*.log"):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        # 解析日志行
                        if 'ERROR' in line:
                            analysis['error_count'] += 1
                            # 提取错误类型
                            error_match = error_pattern.search(line)
                            if error_match:
                                error_type = error_match.group(1)
                                analysis['top_errors'].append(error_type)
                        elif 'WARNING' in line:
                            analysis['warning_count'] += 1
                            # 提取警告类型
                            warning_match = warning_pattern.search(line)
                            if warning_match:
                                warning_type = warning_match.group(1)
                                analysis['top_warnings'].append(warning_type)
                        elif 'INFO' in line:
                            analysis['info_count'] += 1
                        elif 'DEBUG' in line:
                            analysis['debug_count'] += 1
                        
                        analysis['total_logs'] += 1
                        
            except Exception as e:
                self.logger.error(f"分析日志文件失败 {log_file.name}: {e}")
        
        # 计算错误率
        if analysis['total_logs'] > 0:
            analysis['error_rate'] = analysis['error_count'] / analysis['total_logs']
        
        # 统计最常见的错误和警告
        from collections import Counter
        analysis['top_errors'] = Counter(analysis['top_errors']).most_common(10)
        analysis['top_warnings'] = Counter(analysis['top_warnings']).most_common(10)
        
        return analysis

    def generate_log_report(self, hours: int = 24) -> str:
        """生成日志报告"""
        analysis = self.analyze_logs(hours)
        
        report = f"""
=== 日志分析报告 ({hours}小时) ===
总日志数: {analysis['total_logs']}
错误数: {analysis['error_count']}
警告数: {analysis['warning_count']}
信息数: {analysis['info_count']}
调试数: {analysis['debug_count']}
错误率: {analysis['error_rate']:.2%}

最常见的错误类型:
"""
        
        for error_type, count in analysis['top_errors']:
            report += f"  {error_type}: {count}次\n"
        
        report += "\n最常见的警告类型:\n"
        for warning_type, count in analysis['top_warnings']:
            report += f"  {warning_type}: {count}次\n"
        
        return report

    def export_logs_to_json(self, output_file: str, hours: int = 24) -> None:
        """导出日志到JSON文件"""
        import json
        from pathlib import Path
        
        log_path = Path(self.log_dir)
        current_time = datetime.now()
        start_time = current_time - timedelta(hours=hours)
        
        logs_data = []
        
        for log_file in log_path.glob(f"{self.file_name}*.log"):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        log_entry = {
                            'file': log_file.name,
                            'line_number': line_num,
                            'content': line.strip(),
                            'timestamp': current_time.isoformat()
                        }
                        logs_data.append(log_entry)
                        
            except Exception as e:
                self.logger.error(f"导出日志文件失败 {log_file.name}: {e}")
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(logs_data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"日志已导出到: {output_file}")
        except Exception as e:
            self.logger.error(f"导出JSON文件失败: {e}")

    def cleanup(self) -> None:
        """清理资源"""
        if hasattr(self, 'aggregator'):
            self.aggregator.stop()
        try:
            self._stop_remote_sender()
        except Exception:
            pass
        if self._exception_hook and self._prev_excepthook and sys.excepthook is self._exception_hook:
            try:
                sys.excepthook = self._prev_excepthook
            except Exception:
                pass
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                try:
                    self._executor.shutdown(wait=False)
                except Exception:
                    pass
            self._executor = None
        self._remove_handlers()
        self.clear_caches()
        import gc
        gc.collect()
        print("XmiLogger 资源清理完成")
