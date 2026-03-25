import re
from pathlib import Path


def minimal_text_cleaner(raw_text):
    text = raw_text

    text = text.replace('\r\n', '\n').replace('\r', '\n')

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        if '|' in line:
            cleaned_lines.append(line)
            continue

        line = re.sub(r'([\u4e00-\u9fa5])\n?\s*([\u4e00-\u9fa5])', r'\1\2', line)

        html_escape_map = {
            '&lt;': '<', '&gt;': '>', '&quot;': '"',
            '&amp;': '&', '&#39;': "'", '&nbsp;': ' '
        }
        for escape_char, original_char in html_escape_map.items():
            line = line.replace(escape_char, original_char)

        line = re.sub(r'[\U0001F300-\U0001F9FF]', '', line)

        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


class TextCleanerProcessor:
    def __init__(self, cleaner_func=None):
        self.cleaner = cleaner_func or minimal_text_cleaner

    def process(self, source_path, output_path):
        try:
            source_path = Path(source_path)
            output_path = Path(output_path)
            output_path.parent.mkdir(exist_ok=True)

            with open(source_path, 'r', encoding='utf-8') as f_in:
                raw_text = f_in.read()

            cleaned_text = self.cleaner(raw_text)

            with open(output_path, 'w', encoding='utf-8') as f_out:
                f_out.write(cleaned_text)

            print(f" 清洗完成：{source_path.name}")
            return True
        except Exception as e:
            print(f" 清洗失败（{source_path.name}）: {str(e)}")
            return False


if __name__ == "__main__":
    cleaner = TextCleanerProcessor()
    cleaner.process("txt.txt", "清洗后的文档.txt")