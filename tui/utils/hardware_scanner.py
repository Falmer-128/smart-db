import platform
import subprocess
from dataclasses import dataclass

@dataclass
class HardwareSpecs:
    os_name: str
    gpu_present: bool
    raw_vram_mb: int
    usable_vram_mb: int
    assigned_tier: int

def get_hardware_specs() -> HardwareSpecs:
    """
    Safely queries the host OS for GPU VRAM and assigns an LLM tier.
    CPU must be reserved for Tesseract OCR, so the LLM must fit entirely into VRAM.
    """
    os_name = platform.system()
    gpu_present = False
    raw_vram_mb = 0
    usable_vram_mb = 0
    assigned_tier = 3 # Default to lowest tier (CPU/Low VRAM)
    
    # 1.5GB OS overhead margin + KV Cache buffer
    OS_OVERHEAD_MB = 1536 
    
    try:
        # Run nvidia-smi
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.total,memory.free', '--format=csv,noheader,nounits'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        output = result.stdout.strip()
        if output:
            # Parse the first GPU output
            first_gpu = output.split('\n')[0]
            total_vram_str, free_vram_str = first_gpu.split(',')
            
            raw_vram_mb = int(total_vram_str.strip())
            gpu_present = True
            
            # Calculate usable VRAM by subtracting the safety margin from the total
            usable_vram_mb = max(0, raw_vram_mb - OS_OVERHEAD_MB)
            
            # Assign tiers based on usable VRAM
            if usable_vram_mb >= 8192:  # Tier 1 (> 8GB Usable) -> e.g. Qwen 2.5 7B
                assigned_tier = 1
            elif usable_vram_mb >= 4096: # Tier 2 (4-8GB Usable) -> e.g. Qwen 2.5 3B
                assigned_tier = 2
            else:                        # Tier 3 (< 4GB Usable) -> e.g. Gemma 2 2B / CPU Fallback
                assigned_tier = 3
                
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        # Fallback to Tier 3 if nvidia-smi is not found, command fails, or parsing errors occur.
        # This safely catches systems without an NVIDIA GPU or missing drivers.
        pass

    return HardwareSpecs(
        os_name=os_name,
        gpu_present=gpu_present,
        raw_vram_mb=raw_vram_mb,
        usable_vram_mb=usable_vram_mb,
        assigned_tier=assigned_tier
    )

if __name__ == "__main__":
    # For testing the module independently
    specs = get_hardware_specs()
    print("Detected Hardware Specs:")
    print(specs)
