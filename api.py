"""
FastAPI service for PageIndex: single POST /run endpoint to process a PDF and return structure as JSON.
Run with: uv run api.py
"""
import asyncio
import json
import logging
import os
import tempfile
import time

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

from pageindex import page_index_main
from pageindex.utils import ConfigLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App and config
# ---------------------------------------------------------------------------
app = FastAPI(title="PageIndex API", description="Process PDFs and return document structure.")

# Same defaults as run_pageindex.py (from config.yaml)
_config_loader = ConfigLoader()
_opt = _config_loader.load({})


@app.post("/run")
async def run(file: UploadFile = File(...)):
    """
    Accept a PDF file, run PageIndex, and return the structure (toc_with_page_number) as JSON.
    """
    filename = file.filename or "unknown"
    temp_dir = None
    temp_path = None

    try:
        # Validate PDF
        if not filename.lower().endswith(".pdf"):
            logger.warning("Rejected non-PDF file: %s", filename)
            raise HTTPException(status_code=400, detail="File must have a .pdf extension")

        # Read content and get size for logging
        content = await file.read()
        file_size = len(content)
        logger.info("Request received: filename=%s, size_bytes=%s", filename, file_size)

        # Write to temp directory
        temp_dir = tempfile.mkdtemp(prefix="pageindex_")
        # Use original filename if safe, else a generated name
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ") or "upload.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name = safe_name + ".pdf"
        temp_path = os.path.join(temp_dir, safe_name)
        with open(temp_path, "wb") as f:
            f.write(content)

        logger.info("Processing started: %s", filename)
        start = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            # page_index_main() uses asyncio.run() internally; run it in a thread so we don't
            # hit "asyncio.run() cannot be called from a running event loop"
            toc_with_page_number = await loop.run_in_executor(
                None, lambda: page_index_main(temp_path, _opt)
            )
        finally:
            elapsed = time.perf_counter() - start
            logger.info("PageIndex finished: elapsed_seconds=%.2f", elapsed)

        logger.info("Request finished: %s", filename)
        body = json.dumps(toc_with_page_number, ensure_ascii=False, indent=2)
        return Response(content=body, media_type="application/json")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            try:
                if temp_path and os.path.isfile(temp_path):
                    os.unlink(temp_path)
                os.rmdir(temp_dir)
            except OSError as e:
                logger.warning("Cleanup temp dir failed: %s", e)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
