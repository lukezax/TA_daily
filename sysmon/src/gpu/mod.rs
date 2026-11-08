use std::process::Command;

#[derive(Debug, Clone)]
pub struct GpuInfo {
    pub id: usize,
    pub name: String,
    pub utilization: f64,
    pub memory_used: f64,
    pub memory_total: f64,
    pub temperature: f64,
    pub power: f64,
    pub processes: Vec<GpuProcess>,
}

#[derive(Debug, Clone)]
pub struct GpuProcess {
    pub pid: u32,
    pub process_name: String,
    pub memory_used: f64,
}

pub fn get_gpu_info() -> Vec<GpuInfo> {
    let mut gpus = Vec::new();
    
    // Query GPU info
    let output = Command::new("nvidia-smi")
        .args([
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits"
        ])
        .output();
    
    if let Ok(output) = output {
        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
            if parts.len() >= 7 {
                let gpu = GpuInfo {
                    id: parts[0].parse().unwrap_or(0),
                    name: parts[1].to_string(),
                    utilization: parts[2].parse().unwrap_or(0.0),
                    memory_used: parts[3].parse().unwrap_or(0.0),
                    memory_total: parts[4].parse().unwrap_or(0.0),
                    temperature: parts[5].parse().unwrap_or(0.0),
                    power: parts[6].parse().unwrap_or(0.0),
                    processes: Vec::new(),
                };
                gpus.push(gpu);
            }
        }
    }
    
    // Query GPU processes
    let output = Command::new("nvidia-smi")
        .args([
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits"
        ])
        .output();
    
    if let Ok(output) = output {
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut processes = Vec::new();
        
        for line in stdout.lines() {
            let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
            if parts.len() >= 3 {
                let process = GpuProcess {
                    pid: parts[0].parse().unwrap_or(0),
                    process_name: parts[1].to_string(),
                    memory_used: parts[2].parse().unwrap_or(0.0),
                };
                processes.push(process);
            }
        }
        
        // Assign processes to GPUs (simplified - all to GPU 0 for now)
        if !gpus.is_empty() {
            gpus[0].processes = processes;
        }
    }
    
    gpus
}
