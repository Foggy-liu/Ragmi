# txt/

`documents/` 里原始文档的**解析产物**（纯文本）。程序运行时生成，不是源代码。

## 谁写它、谁读它

```text
documents/*.pdf|docx|md|txt
        │
        │  utils/docs/txt_main.py  ← 上传接口 api/api_file.py 会触发它
        │  （pdf_txt / word_txt / md_txt 三个处理器 + TextCleaner）
        ▼
txt/<原文件名>_<原扩展名>.txt      ← 这个目录
        │
        │  utils/txt_spliter/vector_main.py
        │  spliter.split_all_files() 只读 txt/*.txt
        ▼
Milvus（切分 → 嵌入 → 建索引 → 移动 alias）
```

## 为什么只入库目录本身（`.gitkeep` + 这份说明）

1. **内容是运行时产物**：换一次语料就整体重写，没有版本价值。
2. **它就是语料本体**：评测快照里的 `corpus_sha256` = `txt/*.txt` 按文件名排序后
   逐个拼接的字节 sha256（`test/eval_quality/run_answer_quality_eval.py::corpus_sha256()`）。
   入库等于把语料公开，而且改了内容指纹就变了 —— 线 A 的历史数字会变得不可比。
3. **体积随语料变**：当前语料约 1.2MB / 14 个文件。

## 目录本身不是可选的

- `main.py` 的 lifespan 里 `upload_dir.mkdir(parents=True, exist_ok=True)` 建 `documents/`
- `api/api_file.py` 导入时 `input_dir.mkdir()` / `output_dir.mkdir()` 建这两个目录
- `docker-compose.yml` 里 api 服务按 volume 挂载 `./documents` 与 `./txt` —— 宿主机和
  容器共用同一份，宿主机的 `.file_filter.json`（MD5 去重索引）因此对容器也生效

## 为什么 `documents/` 里没有这份说明

`documents/` 下的 `*.md` 会被 `md_txt.py` 当成语料解析（`input_dir.glob("*.md")`），
放一个 README 进去 = 往语料里掺一条无关文本 = 指纹变。所以说明只放在产出侧 `txt/`。
