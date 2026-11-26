import json
import hashlib
import time
from pathlib import Path


def _basename(stored_path):
    """从（可能是绝对路径的）字符串里取出文件名。

    索引里存过两种形式：宿主机绝对路径（D:\\...\\txt\\x.txt）和容器绝对路径
    （/app/txt/x.txt）。改成只留文件名、解析时用 output_dir 拼回来，
    宿主机和容器才能共用同一份索引 —— 否则换个环境 Path(...).exists() 恒为
    False，去重永远不生效。
    """
    return str(stored_path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


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
                    index = json.load(f)
                # 兼容旧格式：output_path 存的是绝对路径 → 迁成只存文件名
                for info in index.values():
                    if 'output_path' in info:
                        info['output_path'] = _basename(info['output_path'])
                return index
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
            output_path = self.output_dir / _basename(output_info['output_path'])
            if output_path.exists():
                # 哈希相同即内容相同，内容相同就不必再解析一遍。
                #
                # ⚠ 旧实现这里还比了一次 mtime（要求 source_mtime <= output_mtime 才跳过），
                # 那道门反而把去重废掉了：上传接口用 'wb' 覆盖写 documents/ 里的源文件
                # （api/api_file.py），源文件 mtime 必然比产物新 → 每次上传同一份文档
                # 都被判成"需要处理"；而 output.py 的 get_output_path() 永不覆盖、
                # 只会造 _1/_2/... 副本 → txt/ 里堆出一串同内容副本，索引里全是重复 chunk。
                #
                # "源文件是否更新"由哈希本身回答：内容变了哈希就变、查不到条目 → 重新解析。
                # 措辞里不带"未更新"—— 已经没有 mtime 这一说了。
                return False, "内容相同，已处理过"
        return True, "需要处理"

    def record_processed(self, source_file, output_path):
        """记录已处理的文件"""
        source_path = Path(source_file)
        source_hash = self._get_hash(source_path)
        if source_hash:
            self.file_index[source_hash] = {
                # 只存文件名：宿主机与容器指向同一个 bind mount，
                # 存绝对路径会跨环境失效（宿主机写的 D:\... 在容器里解析不到）
                'output_path': _basename(output_path),
                'source_file': str(source_path),
                'recorded_time': time.time()
            }
            self._save_index()