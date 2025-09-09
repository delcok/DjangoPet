# -*- coding: utf-8 -*-
# @Time    : 2024/12/11 16:59
# @Author  : Delock

from logging.handlers import RotatingFileHandler
import gzip
import shutil
import os


class GzipRotatingFileHandler(RotatingFileHandler):
    """
    Rotates log files based on size and compresses old logs with gzip.
    Ensures the log directory exists.
    """

    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, encoding=None, delay=False):
        # 确保日志目录存在
        log_dir = os.path.dirname(filename)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)

    def doRollover(self):
        """
        Overridden method to perform log rotation and compress the rotated log.
        """
        super().doRollover()

        # 压缩已轮转的日志文件
        if self.backupCount > 0:
            for i in range(self.backupCount, 0, -1):
                log_filename = f"{self.baseFilename}.{i}"
                compressed_log_filename = f"{log_filename}.gz"
                if os.path.exists(log_filename) and not os.path.exists(compressed_log_filename):
                    with open(log_filename, 'rb') as f_in:
                        with gzip.open(compressed_log_filename, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(log_filename)