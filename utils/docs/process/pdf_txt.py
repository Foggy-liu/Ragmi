import os
import pymupdf
from PIL import Image
import io
import pytesseract
import cv2
import numpy as np
from pathlib import Path


class SimplePdfParser:
    """
    PDF解析器：pymupdf文本提取 + OCR兜底
    """

    # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    # 使用 tesseract OCR 技术需要安装并手动配置OCR路径，或者是将其添加到你的环境变量中（电脑配置）

    def __init__(self):
        """
        初始化PDF解析器
        """

        # 获取当前文件的路径
        current_script_path = Path(__file__).resolve()

        # 固定路径：相对于当前文件向上两级目录
        self.pdf_dir = current_script_path.parent.parent.parent.parent / "documents"
        self.output_dir = current_script_path.parent.parent.parent.parent / "txt"

        self.pdf_file_list = []

        # 创建输出目录
        # parents = True: 自动创建所有必要的父目录
        # exist_ok = True: 目录已存在时不抛出异常
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_pdf_files(self):
        """获取目录下所有PDF文件"""
        self.pdf_file_list.clear()

        if not os.path.exists(self.pdf_dir):
            print(f"目录不存在：{self.pdf_dir}")
            return []

        for filename in os.listdir(self.pdf_dir):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(self.pdf_dir, filename)
                if os.path.isfile(file_path):
                    self.pdf_file_list.append(file_path)

        if not self.pdf_file_list:
            print(f"在 {self.pdf_dir} 未找到PDF文件")
        else:
            print(f"找到 {len(self.pdf_file_list)} 个PDF文件")

        return self.pdf_file_list

    def extract_pure_text(self, page):
        """单页面文本提取"""
        valid_blocks = []
        y_threshold = 12

        # 方式1：优先提取原生大文本块
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            if "text" not in block:
                continue
            text = block["text"].strip()
            if text:
                x0, y0 = block["bbox"][0], block["bbox"][1]
                valid_blocks.append({"text": text, "x0": x0, "y0": y0})

        # 方式2：若没抓到文本，用单词级文本块兜底
        if not valid_blocks:
            words = page.get_text("words")
            for word in words:
                x0, y0, _, _, text = word[:5]
                text = text.strip()
                if text:
                    valid_blocks.append({"text": text, "x0": x0, "y0": y0})

        # 处理无文本情况
        if not valid_blocks:
            return "（无有效文本）"

        # 核心排版修复：行分组+左右排序
        valid_blocks.sort(key=lambda b: b["y0"])
        line_groups = []
        current_line = [valid_blocks[0]]

        for block in valid_blocks[1:]:
            if abs(block["y0"] - current_line[0]["y0"]) <= y_threshold:
                current_line.append(block)
            else:
                line_groups.append(current_line)
                current_line = [block]
        line_groups.append(current_line)

        # 同一行按x坐标排序（左→右）
        page_text_lines = []
        for line in line_groups:
            line.sort(key=lambda b: b["x0"])
            line_text = "".join([b["text"] for b in line])
            page_text_lines.append(line_text)

        # 合并页面文本
        page_text = "\n".join(page_text_lines)

        # 文本规范化
        return self.text_normalization(page_text)

    def text_normalization(self, text):
        """文本规范化处理"""
        if not text or text.strip() == "":
            return text

        # 1. 统一换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # 2. 移除多余空白字符
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            line = ' '.join(line.split())
            if line:
                cleaned_lines.append(line)

        # 3. 处理段落合并
        result_lines = []
        for line in cleaned_lines:
            if result_lines and len(result_lines[-1]) > 0 and len(line) < 50:
                last_char = result_lines[-1][-1]
                if last_char in '，。！？；：,.!?;:）】》」』':
                    result_lines[-1] += line
                    continue
            result_lines.append(line)

        # 4. 重新组合
        return '\n'.join(result_lines)

    def page_to_image(self, page, zoom=2):
        """将PDF页面转为PIL Image"""
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_data = pix.tobytes("ppm")
        return Image.open(io.BytesIO(img_data))

    def ocr_scan(self, img):
        """OCR扫描图片提取文字"""
        # 预处理图像
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # 增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 二值化
        _, binary = cv2.threshold(enhanced, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # OCR识别
        text = pytesseract.image_to_string(binary, lang='chi_sim+eng',
                                           config='--psm 3 --oem 3')

        return text.strip()

    def extract_page_text(self, pdf_path, page_num):
        """提取单页文本：先尝试pymupdf，失败则OCR"""
        try:
            with pymupdf.open(pdf_path) as doc:
                if page_num < 1 or page_num > len(doc):
                    return f"页码错误：共{len(doc)}页，请求第{page_num}页"

                page = doc[page_num - 1]

                # 先尝试用pymupdf提取文本
                text = self.extract_pure_text(page)

                # 如果提取到的文本太短或无文本，尝试OCR
                if len(text.strip()) < 10 or text == "（无有效文本）":
                    img = self.page_to_image(page)
                    ocr_text = self.ocr_scan(img)
                    if ocr_text:
                        return f"【OCR扫描】\n{ocr_text}"
                    else:
                        return "（无法提取文本）"
                else:
                    return text

        except Exception as e:
            return f"提取失败：{str(e)}"

    def process_single_pdf(self, pdf_path, output_path=None):
        """处理单个PDF文件"""
        pdf_name = os.path.basename(pdf_path)
        if output_path is None:
            # 如果没有指定输出路径，使用默认路径
            txt_name = os.path.splitext(pdf_name)[0] + ".txt"
            txt_path = os.path.join(self.output_dir, txt_name)
        else:
            txt_path = output_path

        print(f"\n处理文件：{pdf_name}")
        print(f"保存路径：{txt_path}")

        try:
            with pymupdf.open(pdf_path) as doc:
                total_pages = len(doc)
                all_text = [f"【PDF信息】：{pdf_name}（共{total_pages}页）", ""]

                for page_num in range(1, total_pages + 1):
                    print(f"  处理第 {page_num}/{total_pages} 页...", end='')

                    # 提取单页文本
                    page_text = self.extract_page_text(pdf_path, page_num)

                    # 添加到结果
                    all_text.append(f"===== 第{page_num}页 =====")
                    all_text.append(page_text)
                    all_text.append("")

                    print("完成")

                # 保存到文件
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(all_text))

                print(f" {pdf_name} 处理完成")
                return True

        except Exception as e:
            print(f" {pdf_name} 处理失败：{str(e)}")
            return False

        except Exception as e:
            print(f" {pdf_name} 处理失败：{str(e)}")
            return False

    def main(self):
        """主函数：批量处理文件，批量导出"""
        print("=" * 50)
        print("开始批量处理PDF文件")
        print("=" * 50)

        # 获取PDF文件列表
        pdf_files = self.get_pdf_files()

        if not pdf_files:
            print("没有需要处理的PDF文件，程序退出")
            return

        success_count = 0
        fail_count = 0

        # 逐个处理PDF文件
        for i, pdf_path in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}] ", end="")
            if self.process_single_pdf(pdf_path):
                success_count += 1
            else:
                fail_count += 1

        # 输出统计信息
        print("\n" + "=" * 50)
        print(f"处理完成！")
        print(f"成功：{success_count} 个文件")
        print(f"失败：{fail_count} 个文件")
        print(f"结果保存在：{self.output_dir}")
        print("=" * 50)

    def process(self, file_path, output_path):
        """处理单个PDF文件，参数由框架传入"""
        return self.process_single_pdf(file_path, output_path)


# 使用示例
if __name__ == '__main__':
    # 创建解析器
    parser = SimplePdfParser()

    # 执行主函数
    parser.main()