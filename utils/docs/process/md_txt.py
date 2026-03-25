import markdown
import re
from pathlib import Path
from bs4 import BeautifulSoup

MD_EXTENSIONS = ['extra', 'sane_lists', 'attr_list']


class MarkdownProcessor:
    def __init__(self):
        pass

    def parse_html_to_text(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        text_parts = []

        # 按文档顺序一次性处理所有元素
        for element in soup.find_all(['h1', 'h2', 'h3', 'p', 'table', 'img', 'ul', 'ol']):
            # 检查元素是否嵌套在表格中
            is_in_table = False
            for parent in element.parents:
                if parent.name == 'table':
                    is_in_table = True
                    break

            # 如果在表格内且不是table标签本身，跳过
            if is_in_table and element.name != 'table':
                continue

            # 检查元素是否嵌套在列表中（除了列表本身）
            if element.name in ['p', 'h1', 'h2', 'h3']:
                is_in_list = False
                for parent in element.parents:
                    if parent.name in ['ul', 'ol', 'li']:
                        is_in_list = True
                        break
                if is_in_list:
                    continue

            if element.name in ['h1', 'h2', 'h3']:
                text = element.get_text().strip()
                if text:
                    text_parts.append(f"\n\n{text}\n")

            elif element.name == 'p':
                text = element.get_text().strip()
                if text and not re.match(r'^\[\^?\d+\]', text):
                    text_parts.append(f"\n{text}")

            elif element.name == 'table':
                # 表格需要嵌套扫描
                rows = element.find_all('tr')
                if not rows:
                    continue

                table_lines = []
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    cell_texts = [cell.get_text().strip() for cell in cells]
                    if cell_texts:
                        table_lines.append(" | ".join(cell_texts))

                if len(table_lines) >= 2:
                    headers = table_lines[0].split(" | ")
                    separator = " | ".join(['-' * len(h) for h in headers])
                    table_lines.insert(1, separator)

                if table_lines:
                    text_parts.append(f"\n\n{chr(10).join(table_lines)}\n\n")

            elif element.name == 'img':
                img_alt = element.get('alt', '').strip()
                if img_alt:
                    text_parts.append(f"\n【图片：{img_alt}】\n")
                else:
                    text_parts.append(f"\n【图片】\n")

            elif element.name in ['ul', 'ol']:
                # 检查是否在另一个列表内
                is_nested_list = False
                for parent in element.parents:
                    if parent.name in ['ul', 'ol', 'li']:
                        is_nested_list = True
                        break

                if is_nested_list:
                    continue

                # 处理列表项
                items = []
                for li in element.find_all('li'):
                    # 提取列表项文本
                    li_text = li.get_text(strip=True)
                    if li_text:
                        if element.name == 'ul':
                            items.append(f"  • {li_text}")
                        else:
                            idx = list(element.find_all('li')).index(li) + 1
                            items.append(f"  {idx}. {li_text}")

                if items:
                    text_parts.append("\n" + "\n".join(items) + "\n")

        full_text = ''.join(text_parts)
        full_text = re.sub(r'\n{3,}', '\n\n', full_text.strip())
        return full_text

    def process(self, file_path, output_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        html_content = markdown.markdown(md_content, extensions=MD_EXTENSIONS)
        plain_text = self.parse_html_to_text(html_content)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(plain_text)

        print(f"处理完成：{file_path} -> {output_path}")
        return True

    def batch_process(self, input_folder, output_folder):
        input_dir = Path(input_folder)
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        success_count = 0
        for md_file in input_dir.glob("*.md"):
            try:
                output_file = output_dir / f"{md_file.stem}.txt"
                self.process(md_file, output_file)
                success_count += 1
            except Exception as e:
                print(f"处理失败 {md_file.name}: {str(e)}")

        if success_count:
            print(f"批量处理完成：成功 {success_count}个文件")
        else:
            print("未找到MD文件")


if __name__ == '__main__':
    processor = MarkdownProcessor()
    processor.process("../../../documents/01_RAG_intro.md", "txt.txt")