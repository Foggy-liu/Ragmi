from pathlib import Path


class FileScanner:
    """文件扫描器：扫描并分类文档文件"""

    def __init__(self, input_dir):
        self.input_dir = input_dir
        self.supported_types = {'.txt', '.md', '.docx', '.doc', '.pdf'}

    def scan_documents(self):
        """扫描并分类文档文件"""
        file_categories = {}

        for filename in self.input_dir.iterdir():
            if filename.is_file():
                ext = filename.suffix.lower()
                if ext in self.supported_types:
                    if ext not in file_categories:
                        file_categories[ext] = []
                    file_categories[ext].append(filename)

        return file_categories

if __name__ == '__main__':
    test_dir = Path('D:\\PythonProject\\ragmi\\documents')
    scanner = FileScanner(test_dir)

    # 2. 执行扫描
    result = scanner.scan_documents()

    # 3. 打印结果
    print("扫描结果：")
    for ext, files in result.items():
        print(f"{ext}: {len(files)}个文件")
        for f in files:
            print(f"  - {f.name}")
