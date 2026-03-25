import json
import hashlib
import time
from pathlib import Path

class FileFilter:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.index_file = self.output_dir / ".file_filter.json"
        self.file_index = self._load_index()
        self._save_index()  # 初始化时主动创建/更新索引文件

    def _load_index(self):
        """加载哈希索引文件"""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # 文件损坏或无法读取，重新创建
                return {}
        return {}

    def _save_index(self):
        """保存哈希索引到文件"""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(self.file_index, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"⚠ 警告：无法保存哈希索引: {e}")

    def _get_hash(self, file_path):
        """计算文件的MD5哈希值"""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                # 分块读取，避免大文件占用过多内存
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError) as e:
            print(f"⚠ 警告：无法计算文件哈希 {file_path}: {e}")
            return None

    def should_process(self, source_file, file_type):
        """判断文件是否需要处理"""
        source_path = Path(source_file)
        source_hash = self._get_hash(source_path)
        if source_hash is None:
            return True, "无法计算哈希"
        # 检查是否已处理过相同内容的文件
        if source_hash in self.file_index:
            output_info = self.file_index[source_hash]
            output_path = Path(output_info['output_path'])
            if output_path.exists():
                # 检查源文件是否更新
                source_mtime = source_path.stat().st_mtime
                output_mtime = output_path.stat().st_mtime
                if source_mtime <= output_mtime:
                    return False, "内容相同且未更新"
        return True, "需要处理"

    def record_processed(self, source_file, output_path):
        """记录已处理的文件"""
        source_path = Path(source_file)
        source_hash = self._get_hash(source_path)
        if source_hash:
            self.file_index[source_hash] = {
                'output_path': str(output_path),
                'source_file': str(source_path),
                'recorded_time': time.time()
            }
            self._save_index()