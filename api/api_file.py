from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from pathlib import Path
import shutil
import sys
from utils.docs.txt_main import main as txt_parse_main
from uvicorn import run

# 初始化FastAPI
app = FastAPI(
    title="文档批量上传+解析API",
    description="批量上传文件到documents目录（保留原文件名），自动调用txt_main完整流程处理",
    version="1.0"
)

# 设置输入输出目录
current_script_path = Path(__file__).resolve()
input_dir = current_script_path.parent.parent / "documents"
output_dir = current_script_path.parent.parent / "txt"
# 确保目录存在
input_dir.mkdir(exist_ok=True)
output_dir.mkdir(exist_ok=True)

# 支持的文件类型（与txt_main的Scanner一致）
SUPPORTED_FILE_TYPES = {".txt", ".md", ".docx", ".pdf"}

# ------------------- 批量上传+触发解析API -------------------
@app.post("/batch-upload-and-parse", summary="批量上传文件并触发txt_main完整处理流程")
async def batch_upload_and_parse(
    files: list[UploadFile] = File(..., description=f"支持批量上传，文件类型：{', '.join(SUPPORTED_FILE_TYPES)}"),
    overwrite: bool = Query(
        default=False,
        description="是否覆盖documents目录中已存在的同名文件（默认False：跳过同名文件，避免误删）"
    )
):
    """
    批量上传文件到documents目录，并调用txt_main处理流程。
    """
    # 1. 批量处理上传文件
    uploaded_files = []  # 记录成功上传的文件
    skipped_files = []   # 记录跳过的文件（同名未覆盖）
    failed_uploads = []  # 记录上传失败的文件

    for file in files:
        file_suffix = Path(file.filename).suffix.lower()
        save_filename = file.filename  # 直接用原文件名保存
        save_path = input_dir / save_filename

        # 路径穿越校验：resolve() 后必须在 input_dir 内
        try:
            resolved = (input_dir / save_filename).resolve()
            input_dir_resolved = input_dir.resolve()
            if not str(resolved).startswith(str(input_dir_resolved)):
                failed_uploads.append({
                    "filename": file.filename,
                    "reason": "文件名包含非法路径字符"
                })
                continue
        except Exception:
            failed_uploads.append({
                "filename": file.filename,
                "reason": "路径解析失败"
            })
            continue

        # 校验文件类型
        if file_suffix not in SUPPORTED_FILE_TYPES:
            failed_uploads.append({
                "filename": file.filename,
                "reason": f"不支持的文件类型（仅支持：{', '.join(SUPPORTED_FILE_TYPES)}）"
            })
            continue

        # 处理同名文件
        if save_path.exists():
            if not overwrite:
                skipped_files.append({
                    "filename": file.filename,
                    "reason": "documents目录中已存在同名文件，已跳过（可设置overwrite=True强制覆盖）"
                })
                file.file.close()
                continue
            else:
                # 强制覆盖：删除原有文件
                save_path.unlink()
                print(f"已覆盖同名文件：{save_filename}")

        # 保存文件（使用原文件名）
        try:
            with open(save_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            uploaded_files.append({
                "filename": file.filename,
                "save_path": str(save_path.resolve()),
                "status": "覆盖" if overwrite and save_path.exists() else "新增"
            })
        except Exception as e:
            failed_uploads.append({
                "filename": file.filename,
                "reason": f"保存失败：{str(e)}"
            })
        finally:
            file.file.close()  # 关闭文件流

    # 2. 上传完成后，调用txt_main完整处理流程
    try:
        parse_results = txt_parse_main()  # 依赖txt_main的main()返回结果字典
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"调用txt_main处理失败：{str(e)}"
        )

    # 3. 组装响应结果
    return JSONResponse(
        status_code=200,
        content={
            "status": "completed",
            "message": (
                f"批量上传完成：{len(uploaded_files)}个成功，{len(skipped_files)}个跳过，"
                f"{len(failed_uploads)}个失败"
            ),
            "upload_details": {
                "uploaded_files": uploaded_files,
                "skipped_files": skipped_files,
                "failed_uploads": failed_uploads
            },
            "parse_results": parse_results,
            "note": (
                "1. 上传文件保留原文件名，重复上传未修改的文件会被txt_main的哈希过滤跳过；"
                "2. 解析后的TXT文件命名由txt_main自动处理（基础名_格式_计数器.txt）；"
                "3. 如需覆盖同名文件，上传时添加参数overwrite=True。"
            )
        }
    )

# ------------------- 单文件上传接口（可选） -------------------
@app.post("/upload-and-parse", summary="单文件上传并触发txt_main处理")
async def upload_and_parse(
    file: UploadFile = File(..., description=f"支持文件类型：{', '.join(SUPPORTED_FILE_TYPES)}"),
    overwrite: bool = Query(default=False, description="是否覆盖同名文件")
):
    """单文件上传并触发txt_main处理流程。"""
    response = await batch_upload_and_parse(files=[file], overwrite=overwrite)
    return response

if __name__ == '__main__':
        run(app, host="127.0.0.1", port=8000)
