import os
import hashlib
import time
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
# import argparse
from pathlib import Path
import oss2
from oss2 import Auth, Bucket
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# import argparse
# parser = argparse.ArgumentParser(description='OSS Sync Tool')
# parser.add_argument('--config', help='Config file path')
# parser.add_argument('--direction', choices=['local2oss', 'oss2local', 'both'], 
#                    default='both', help='Sync direction')
# args = parser.parse_args()


logger = logging.getLogger("aliyun_oss_sync")

def setup_logging():
    # 设置日志文件名
    log_file = "aliyun_oss_sync.log"
    
    # 创建一个logger
    logger.setLevel(logging.INFO)  # 设置日志级别

    # 创建一个RotatingFileHandler
    # maxBytes=10*1024*1024 表示每个日志文件的最大大小为10MB
    # backupCount=5 表示保留5个备份文件
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    
    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    # 将handler添加到logger中
    logger.addHandler(handler)
    return logger

class OSSSync:
    def __init__(self, config):
        # 初始化配置
        self.config = {
            'local_path': Path(config['local_path']).resolve(),
            'oss_path': config['oss_path'].strip('/'),
            'exclude': set(config.get('exclude', [])),
            'sync_direction': config.get('direction', 'local2oss')
        }

        # OSS 客户端初始化
        self.auth = Auth(config['access_key_id'], config['access_key_secret'])
        self.bucket = Bucket(self.auth, config['endpoint'], config['bucket_name'])
        
        # 设置跨平台路径处理
        self.os_adapt_sep = '\\' if os.name == 'nt' else '/'

    def _convert_path(self, path):
        """统一路径格式为OSS风格"""
        return str(path).replace(self.os_adapt_sep, '/')

    def _get_relative_path(self, full_path):
        """获取相对于本地根目录的相对路径"""
        try:
            return Path(full_path).relative_to(self.config['local_path'])
        except ValueError:
            return None

    def _should_ignore(self, path):
        """检查是否在排除列表中"""
        path_str = self._convert_path(path)
        return any(path_str.startswith(p) for p in self.config['exclude'])

    def _calculate_file_hash(self, file_path):
        """计算文件哈希值(MD5)"""
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        return md5.hexdigest()

    def initial_sync(self):
        """初始同步：对比并同步差异"""
        logger.info("Starting initial synchronization...")
        
        # 扫描本地文件
        local_files = {}
        for root, _, files in os.walk(self.config['local_path']):
            for file in files:
                full_path = Path(root) / file
                rel_path = self._get_relative_path(full_path)
                if not rel_path or self._should_ignore(rel_path):
                    continue
                
                local_files[self._convert_path(rel_path)] = {
                    'mtime': full_path.stat().st_mtime,
                    'hash': self._calculate_file_hash(full_path)
                }

        # 扫描OSS文件
        oss_files = {}
        # oss_file_iterator = self.bucket.list_objects_v2(prefix=self.config['oss_path'])
        oss_file_iterator = oss2.ObjectIterator(self.bucket, prefix=self.config['oss_path'])
        for obj in oss_file_iterator:
            rel_path = obj.key[len(self.config['oss_path'])+1:]
            if not rel_path or self._should_ignore(rel_path):
                continue
            
            oss_files[rel_path] = {
                'mtime': obj.last_modified,
                'hash': obj.etag.strip('"')
            }

        # 同步策略
        if self.config['sync_direction'] in ['local2oss', 'both']:
            # 上传本地新增/修改文件
            for rel_path in set(local_files) - set(oss_files):
                self._upload_file(rel_path)
            
            # 对比相同文件
            for rel_path in set(local_files) & set(oss_files):
                if (local_files[rel_path]['hash'].lower() != oss_files[rel_path]['hash'].lower() or
                    local_files[rel_path]['mtime'] > oss_files[rel_path]['mtime']):
                    self._upload_file(rel_path)

        if self.config['sync_direction'] in ['oss2local', 'both']:
            # 下载OSS新增/修改文件
            for rel_path in set(oss_files) - set(local_files):
                self._download_file(rel_path)
            
            # 对比相同文件
            for rel_path in set(local_files) & set(oss_files):
                if (local_files[rel_path]['hash'] != oss_files[rel_path]['hash'] or
                    local_files[rel_path]['mtime'] < oss_files[rel_path]['mtime']):
                    self._download_file(rel_path)

        logger.info("Initial synchronization completed")

    def _upload_file(self, rel_path):
        """上传文件到OSS"""
        local_full = self.config['local_path'] / rel_path
        oss_key = f"{self.config['oss_path']}/{rel_path}"
        
        try:
            self.bucket.put_object_from_file(oss_key, str(local_full))
            logger.info(f"Uploaded: {rel_path}")
        except Exception as e:
            logger.error(f"Upload failed: {rel_path} - {str(e)}")

    def _download_file(self, rel_path):
        """从OSS下载文件"""
        oss_key = f"{self.config['oss_path']}/{rel_path}"
        local_full = self.config['local_path'] / rel_path
        
        try:
            local_full.parent.mkdir(parents=True, exist_ok=True)
            self.bucket.get_object_to_file(oss_key, str(local_full))
            logger.info(f"Downloaded: {rel_path}")
        except Exception as e:
            logger.error(f"Download failed: {rel_path} - {str(e)}")

class SyncEventHandler(FileSystemEventHandler):
    """文件系统事件处理器"""
    def __init__(self, sync_client):
        self.sync_client = sync_client
        self.last_trigger = 0
        
    def _process_event(self, event):
        """处理事件（不加防抖处理）"""
        # if time.time() - self.last_trigger < 1:  # 1秒防抖
        #     return
        
        if event.is_directory:
            return
            
        src_path = Path(event.src_path)
        rel_path = self.sync_client._get_relative_path(src_path)
        
        if not rel_path or self.sync_client._should_ignore(rel_path):
            return
        
        # 处理不同事件类型
        if event.event_type in ['created', 'modified']:
            if self.sync_client.config['sync_direction'] in ['local2oss', 'both']:
                self.sync_client._upload_file(rel_path)
        
        elif event.event_type == 'deleted':
            if self.sync_client.config['sync_direction'] in ['local2oss', 'both']:
                oss_key = f"{self.sync_client.config['oss_path']}/{rel_path}"
                try:
                    self.sync_client.bucket.delete_object(oss_key)
                    logger.info(f"Deleted on OSS: {rel_path}")
                except Exception as e:
                    logger.error(f"Delete failed: {rel_path} - {str(e)}")
        
        elif event.event_type == 'moved':
            try:
                dst_path = Path(event.dest_path)
                dst_rel_path = self.sync_client._get_relative_path(dst_path)
                if not dst_rel_path or self.sync_client._should_ignore(dst_rel_path):
                    return
                if self.sync_client.config['sync_direction'] in ['local2oss', 'both']:
                    src_oss_key = f"{self.sync_client.config['oss_path']}/{rel_path}"
                    dst_oss_key = f"{self.sync_client.config['oss_path']}/{dst_rel_path}"
                    # 复制文件
                    self.sync_client.bucket.copy_object(self.sync_client.bucket.bucket_name, src_oss_key, dst_oss_key)
                    # 删除原文件
                    self.sync_client.bucket.delete_object(src_oss_key)
                    logger.info(f"Moved on OSS: {rel_path} -> {dst_rel_path}")
            except Exception as e:
                logger.error(f"Delete failed: {rel_path} - {str(e)}")
        else:
            logger.info(f"Unknown event type: {event.event_type}")

        self.last_trigger = time.time()

    def on_any_event(self, event):
        self._process_event(event)

def main():
    setup_logging()
    try:
        if getattr(sys, 'frozen', False):
            # 打包后的程序
            base_path = sys.executable
        else:
            # 未打包的脚本
            base_path = os.path.abspath(__file__)
        
        config_file = os.path.join(os.path.dirname(base_path), 'config.json')
        config = json.load(open(config_file,'r',encoding='utf8'))
    
        observer_list = []
        for config_unit in config:
            sync_client = OSSSync(config_unit)
            # 执行初始同步
            sync_client.initial_sync()
            
            # 启动文件监控
            event_handler = SyncEventHandler(sync_client)
            observer = Observer()
            observer_list.append(observer)
            observer.schedule(
                event_handler,
                path=str(sync_client.config['local_path']),
                recursive=True
            )
            observer.start()
    except Exception as ee:
        logger.exception("Error:")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for observer in observer_list:
            observer.stop()
    for observer in observer_list:
        observer.join()

if __name__ == '__main__':
    main()