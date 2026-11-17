from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import List
from langchain_core.documents import Document
from pathlib import Path
import yaml

# 切分参数的**唯一事实来源**：configs/model_config.yaml 的 EMBEDDING_CONFIG.text_splitter。
# 以前代码写死 chunk_size=300、YAML 写 280，而 YAML 从没被读过 → 改配置不生效、两边漂移（P1-7）。
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "model_config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _SPLITTER_CONFIG = yaml.safe_load(_f)["EMBEDDING_CONFIG"]["text_splitter"]

class Splitter:
    """
    两步切分：LangChain切分 → 智能拼接
    """

    def __init__(self, max_chars=None, overlap=None, small_threshold=80):
        # 默认值从 YAML 读；显式传参时以传参为准
        self.max_chars = int(_SPLITTER_CONFIG["chunk_size"]) if max_chars is None else max_chars
        self.overlap = int(_SPLITTER_CONFIG["chunk_overlap"]) if overlap is None else overlap
        self.small_threshold = small_threshold

        # 1. LangChain 切分器
        #    chunk_size 必须用 self.max_chars —— 写死的话 max_chars 这个参数形同虚设，
        #    智能拼接那一步再按 max_chars 裁，两边标准不一致。
        self.langchain_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.max_chars,
            chunk_overlap=self.overlap,
            separators=list(_SPLITTER_CONFIG["separators"])
        )

    def split(self, text: str) -> List[str]:
        """
        两步切分：
        1. LangChain 机械切分
        2. 智能拼接小片段
        """
        # 第一步：LangChain 切分
        langchain_chunks = self.langchain_splitter.split_text(text)

        # 第二步：智能拼接
        final_chunks = []
        i = 0

        while i < len(langchain_chunks):
            current = langchain_chunks[i]

            # 如果是小片段，向后拼接
            if len(current) < self.small_threshold:
                # 开始拼接
                merged = current
                j = i + 1

                # 向后找能拼接的片段
                while j < len(langchain_chunks):
                    next_chunk = langchain_chunks[j]
                    # 检查拼接后是否超限
                    if len(merged) + len(next_chunk) + 1 > self.max_chars:
                        break
                    # 可以拼接
                    merged += "\n" + next_chunk
                    j += 1

                final_chunks.append(merged)
                i = j  # 跳过已拼接的
            else:
                # 正常片段直接保留
                final_chunks.append(current)
                i += 1

        return final_chunks

    # def split_all_files(self) -> List[str]:
    #     """处理txt文件夹中的所有txt文件"""
    #     current_script_path = Path(__file__).resolve()
    #     input_dir = current_script_path.parent.parent.parent / "txt"
    #     input_dir.mkdir(exist_ok=True)
    #
    #     print(f"输入目录: {input_dir}")
    #
    #     txt_files = list(input_dir.glob("*.txt"))
    #
    #     if not txt_files:
    #         print("在输入目录中未找到txt文件")
    #         return []  # 返回空列表
    #
    #     print(f"找到 {len(txt_files)} 个txt文件")
    #
    #     all_chunks = []  # 收集所有文件的chunks
    #
    #     for txt_file in txt_files:
    #         print(f"正在处理: {txt_file.name}")
    #         with open(txt_file, 'r', encoding='utf-8') as f:
    #             text = f.read()
    #
    #         chunks = self.split(text)
    #         all_chunks.extend(chunks)  # 添加到总列表
    #
    #     return all_chunks
    def split_all_files(self) -> List[Document]:
        """处理txt文件夹中的所有txt文件，返回Document对象列表"""
        current_script_path = Path(__file__).resolve()
        input_dir = current_script_path.parent.parent.parent / "txt"
        input_dir.mkdir(exist_ok=True)

        # print(f"输入目录: {input_dir}")

        txt_files = list(input_dir.glob("*.txt"))

        if not txt_files:
            print("在输入目录中未找到txt文件")
            return []

        print(f"找到 {len(txt_files)} 个txt文件")

        all_documents = []

        for txt_file in txt_files:
            print(f"正在处理: {txt_file.name}")
            with open(txt_file, 'r', encoding='utf-8') as f:
                text = f.read()

            chunks = self.split(text)

            # 为每个chunk创建Document对象
            for i, chunk in enumerate(chunks):
                document = Document(
                    page_content=chunk,
                    metadata={
                        "source": txt_file.name,  # 文件名
                        "chunk_id": i,  # 块编号
                        # "file_path": str(txt_file),  # 完整路径（便于查找）
                    }
                )
                all_documents.append(document)

            # print(f"  - 生成 {len(chunks)} 个Document对象")

        # print(f"总共生成 {len(all_documents)} 个Document对象")
        return all_documents

    def split_file(self, file_path: str) -> List[Document]:

        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if file_path.suffix != '.txt':
            print(f"警告: 文件 {file_path.name} 不是txt文件")

        print(f"正在处理: {file_path.name}")

        # 读取文件
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # 切分文本
        chunks = self.split(text)

        # 创建Document对象
        documents = []
        for i, chunk in enumerate(chunks):
            document = Document(
                page_content=chunk,
                metadata={
                    "source": file_path.name,  # 文件名
                    "chunk_id": i,  # 块编号
                    # "file_path": str(file_path),  # 完整路径
                }
            )
            documents.append(document)

        return documents


if __name__ == '__main__':
    # 使用（切分参数默认从 configs/model_config.yaml 读）
    splitter = Splitter()

    # 处理txt文件夹中的所有文件
    splitter.split_all_files()
