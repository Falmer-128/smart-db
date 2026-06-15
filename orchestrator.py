#!/usr/bin/env python3
import os
import subprocess
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

def stop_llm():
    logger.info("Stopping LLM services to free VRAM...")
    subprocess.run(["pkill", "-f", "upload_daemon.py"])
    subprocess.run(
        ["docker", "compose", "stop"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2) # Give VRAM time to free

def start_llm():
    logger.info("Starting LLM services...")
    cmd = ["docker", "compose", "--profile", "local_backend", "up", "-d"]
    subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    # Give AnythingLLM time to boot its API before starting upload daemon
    time.sleep(5)
    subprocess.Popen(
        ["python3", "upload_daemon.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=open("upload_daemon.log", "a"),
        stderr=subprocess.STDOUT
    )

def stop_ocr():
    logger.info("Stopping OCR (Ingestion Daemon) to free VRAM...")
    subprocess.run(["pkill", "-f", "ingestion_daemon.py"])
    subprocess.run(["pkill", "-f", "upload_daemon.py"])
    time.sleep(2) # Give VRAM time to free

def start_ocr():
    logger.info("Starting OCR (Ingestion Daemon)...")
    # Make sure we don't start multiple
    stop_ocr()
    subprocess.Popen(
        ["python3", "ingestion_daemon.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=open("daemon.log", "a"),
        stderr=subprocess.STDOUT
    )

def run_pipeline():
    input_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "INPUT"
    input_dir.mkdir(parents=True, exist_ok=True)
    
    current_mode = "OCR"
    start_ocr()
    logger.info("PIPELINE MODE: Starting in OCR mode...")
    empty_duration = 0
    
    while True:
        # Check if dir is empty (ignoring hidden files)
        files = [f for f in input_dir.glob("*") if not f.name.startswith('.')]
        
        if files:
            empty_duration = 0
            if current_mode == "LLM":
                logger.info("New files detected! Switching to OCR mode...")
                stop_llm()
                start_ocr()
                current_mode = "OCR"
        else:
            if current_mode == "OCR":
                empty_duration += 1
                if empty_duration >= 10:
                    logger.info("INPUT directory empty for 10 seconds. Switching to LLM mode...")
                    stop_ocr()
                    start_llm()
                    current_mode = "LLM"
                    
        time.sleep(1)

def main():
    load_dotenv(override=True)
    mode = os.getenv("SYSTEM_MODE", "OCR_ONLY")
    logger.info(f"Orchestrator starting in {mode} mode")
    
    if mode == "OCR_ONLY":
        stop_llm()
        start_ocr()
    elif mode == "LLM_ONLY":
        stop_ocr()
        start_llm()
    elif mode == "PIPELINE":
        stop_llm()
        run_pipeline()
    else:
        logger.error(f"Unknown SYSTEM_MODE: {mode}")

if __name__ == "__main__":
    main()
