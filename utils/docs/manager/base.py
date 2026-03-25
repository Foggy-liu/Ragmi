class ProcessorManager:
    """处理器管理器：调度不同格式的处理器"""
    def __init__(self, output_manager):
        self.output_manager = output_manager
        self.processors = {}
        self.file_mapping = {}  # 记录源文件->输出文件的映射

    def process_files(self, file_categories):
        """处理各类文件，返回处理结果和文件路径映射"""
        results = {
            'processed': 0,
            'skipped': 0,
            'failed': 0
        }
        self.file_mapping.clear()  # 清空历史映射
        for file_type, files in file_categories.items():
            print(f"\n处理 {file_type} 文件类型...")
            for file_path in files:
                try:
                    # 生成输出路径
                    output_path = self.output_manager.get_output_path(file_path, file_type[1:])
                    # 根据文件类型调用对应的处理函数
                    success = self._process_single_file(file_path, output_path, file_type)
                    if success:
                        print(f"✓ 已处理: {file_path.name} -> {output_path.name}")
                        results['processed'] += 1
                        self.file_mapping[str(file_path)] = str(output_path)  # 记录映射关系
                    else:
                        print(f"✗ 处理失败: {file_path.name}")
                        results['failed'] += 1
                except Exception as e:
                    print(f"✗ 处理失败 {file_path.name}: {e}")
                    results['failed'] += 1
        return results, self.file_mapping  # 返回结果和映射

    def register_processor(self, file_ext, processor):
        self.processors[file_ext] = processor

    def _process_single_file(self, source_path, output_path, file_type):
        if file_type in self.processors:
            return self.processors[file_type].process(source_path, output_path)
        return False
