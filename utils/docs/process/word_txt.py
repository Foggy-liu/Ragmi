import os
import re
from docx import Document
from pathlib import Path

class SimpleWordProcessor:
    """简化的Word处理器（只支持.docx）"""

    def get_docx_files(self, input_folder: Path):
        """获取目录下所有.docx文件"""
        docx_files = []

        if not input_folder.exists():
            print(f"目录不存在：{input_folder}")
            return []

        # 使用 glob 方法获取所有 .docx 文件
        for file_path in input_folder.glob("*.docx"):
            if file_path.is_file():
                docx_files.append(file_path)

        if not docx_files:
            print(f"在 {input_folder} 未找到.docx文件")
        else:
            print(f"找到 {len(docx_files)} 个.docx文件")

        return docx_files

    def main(self):
        """主函数：批量处理Word文档"""
        # 获取当前文件的路径
        current_script_path = Path(__file__).resolve()

        # 固定路径：相对于当前文件向上两级目录
        input_folder = current_script_path.parent.parent.parent / "documents"
        output_folder = current_script_path.parent.parent.parent / "txt"

        # 检查输入文件夹
        if not input_folder.exists():
            print(f"错误：文件夹 '{input_folder}' 不存在")
            return

        # 获取所有.docx文件
        docx_files = self.get_docx_files(input_folder)

        if not docx_files:
            print(f"'{input_folder}' 文件夹中没有找到.docx文件")
            return

        print(f"找到 {len(docx_files)} 个Word文档")

        # 确保输出文件夹存在
        output_folder.mkdir(parents=True, exist_ok=True)

        # 批量处理
        success_count = 0
        for docx_file_path in docx_files:
            try:
                # 读取Word文档
                doc = Document(docx_file_path)
                full_text = []

                # 提取所有段落
                for paragraph in doc.paragraphs:
                    full_text.append(paragraph.text)

                # 提取表格内容
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            full_text.append(cell.text)

                # 合并文本
                plain_text = '\n'.join(full_text)

                # 生成输出路径
                file_name = docx_file_path.name
                file_name_without_ext = docx_file_path.stem
                output_file_path = output_folder / f"{file_name_without_ext}.txt"

                # 写入文件
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(plain_text)

                print(f"[OK] 已处理: {file_name} -> {output_file_path}")
                success_count += 1

            except Exception as e:
                print(f"[FAIL] 处理失败 {docx_file_path.name}: {e}")

        print(f"\n处理完成！成功处理 {success_count}/{len(docx_files)} 个文件")

    def process_single_docx(self, docx_path, output_path=None):
        """处理单个Word文档"""
        try:
            # 读取Word文档
            doc = Document(docx_path)
            full_text = []

            # 提取所有段落
            for paragraph in doc.paragraphs:
                full_text.append(paragraph.text)

            # 提取表格内容
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        full_text.append(cell.text)

            # 合并文本
            plain_text = '\n'.join(full_text)

            # 确定输出路径
            if output_path is None:
                file_name_without_ext = Path(docx_path).stem
                output_path = self.output_folder / f"{file_name_without_ext}.txt"

            # 写入文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)

            return True
        except Exception as e:
            print(f"处理失败 {docx_path}: {e}")
            return False


    def process(self, file_path, output_path):
        """统一接口：处理单个Word文档"""
        return self.process_single_docx(file_path, output_path)


# 使用
if __name__ == "__main__":
    processor = SimpleWordProcessor()
    processor.main()
