from pathlib import Path
from utils.docs.manager.base import ProcessorManager
from utils.docs.manager.output import OutputManager
from utils.docs.manager.scanner import FileScanner
from utils.docs.manager.filter import FileFilter
from utils.docs.process.md_txt import MarkdownProcessor
from utils.docs.process.word_txt import SimpleWordProcessor
from utils.docs.process.pdf_txt import SimplePdfParser
from utils.docs.manager.clean import TextCleanerProcessor

def main():
    print("开始处理文档格式转换+文本清洗...")
    current_script_path = Path(__file__).resolve()
    input_dir = current_script_path.parent.parent.parent / "documents"
    output_dir = current_script_path.parent.parent.parent / "txt"
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")

    # 1. 扫描文件
    print("\n1. 扫描文件夹，文本归类处理...")
    scanner = FileScanner(input_dir)
    all_files = scanner.scan_documents()
    if not all_files:
        print("未找到支持的文档文件")
        return
    total_files = sum(len(files) for files in all_files.values())
    print(f"找到 {total_files} 个文档文件:")
    for file_type, files in all_files.items():
        print(f"  {file_type}: {len(files)} 个")

    # 2. 初始化管理器
    output_manager = OutputManager(output_dir)
    file_filter = FileFilter(output_dir)

    # 3. 过滤文件
    print("\n2. 过滤文件...")
    filtered_files = {}
    skip_count = 0
    for file_type, files in all_files.items():
        filtered_list = []
        for file_path in files:
            need_process, reason = file_filter.should_process(file_path, file_type)
            if need_process:
                filtered_list.append(file_path)
            else:
                print(f"  跳过: {Path(file_path).name} - {reason}")
                skip_count += 1
        if filtered_list:
            filtered_files[file_type] = filtered_list
    print(f"需要处理: {total_files - skip_count} 个文件")
    print(f"直接跳过: {skip_count} 个文件")
    if not filtered_files:
        print("没有需要处理的文件")
        return

    # 4. 注册【格式转换处理器】（仅处理非TXT文件）
    processor_manager = ProcessorManager(output_manager)
    processor_manager.register_processor('.md', MarkdownProcessor())
    processor_manager.register_processor('.docx', SimpleWordProcessor())
    processor_manager.register_processor('.doc', SimpleWordProcessor())
    processor_manager.register_processor('.pdf', SimplePdfParser())

    # 5. 第一步：执行格式转换（非TXT → 临时TXT）
    print("\n3. 执行格式转换（非TXT转TXT）...")
    convert_results, convert_mapping = processor_manager.process_files(
        {k: v for k, v in filtered_files.items() if k != '.txt'}  # 只转换非TXT文件
    )

    # 6. 第二步：收集所有需要清洗的TXT文件
    # （包含：格式转换后的临时TXT + 原生TXT）
    txt_to_clean = []
    # 6.1 加入格式转换后的TXT
    for _, temp_txt_path in convert_mapping.items():
        txt_to_clean.append(Path(temp_txt_path))
    # 6.2 加入原生TXT
    if '.txt' in filtered_files:
        txt_to_clean.extend(filtered_files['.txt'])

    # 7. 第三步：统一清洗所有TXT文件
    print("\n4. 统一清洗所有TXT文件...")
    cleaner = TextCleanerProcessor()
    clean_failed = 0
    final_mapping = {}  # 原文件 → 最终清洗后的TXT
    # 7.1 处理格式转换后的TXT
    for source_path_str, temp_txt_path in convert_mapping.items():
        source_path = Path(source_path_str)
        cleaned_path = output_dir / Path(temp_txt_path).name
        if cleaner.process(temp_txt_path, cleaned_path):
            final_mapping[str(source_path)] = str(cleaned_path)
        else:
            clean_failed += 1
    # 7.2 处理原生TXT
    if '.txt' in filtered_files:
        for native_txt_path in filtered_files['.txt']:
            cleaned_path = output_dir / native_txt_path.name
            if cleaner.process(native_txt_path, cleaned_path):
                final_mapping[str(native_txt_path)] = str(cleaned_path)
            else:
                clean_failed += 1

    # 8. 记录结果
    print("\n5. 记录处理结果...")
    for source_path_str, cleaned_path_str in final_mapping.items():
        source_path = Path(source_path_str)
        cleaned_path = Path(cleaned_path_str)
        if cleaned_path.exists():
            file_filter.record_processed(source_path, cleaned_path)
            print(f"  记录: {source_path.name} -> {cleaned_path.name}")

    # 9. 输出最终统计
    print("\n" + "=" * 50)
    total_processed = len(txt_to_clean) - clean_failed
    print("处理完成！")
    print(f"格式转换成功: {convert_results['processed']} 个")
    print(f"TXT清洗成功: {total_processed} 个")
    print(f"已跳过: {skip_count} 个")
    print(f"失败: {convert_results['failed'] + clean_failed} 个")
    print(f"最终文件保存在: {output_dir}")
    print("=" * 50)

if __name__ == "__main__":
    main()