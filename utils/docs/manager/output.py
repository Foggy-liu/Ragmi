import json
from pathlib import Path


class OutputManager:
    """输出管理器：管理输出文件路径，解决文件名冲突"""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def get_output_path(self, source_file, format_suffix=""):
        """
        生成输出路径，解决文件名冲突
        """
        source_file = Path(source_file)

        # 生成基础输出名称
        base_name = source_file.stem
        if format_suffix:
            base_output_name = f"{base_name}_{format_suffix}.txt"
        else:
            base_output_name = f"{base_name}.txt"

        # 处理文件名冲突
        output_name = base_output_name
        counter = 0

        while (self.output_dir / output_name).exists():
            counter += 1
            if format_suffix:
                output_name = f"{base_name}_{format_suffix}_{counter}.txt"
            else:
                output_name = f"{base_name}_{counter}.txt"

        return self.output_dir / output_name
