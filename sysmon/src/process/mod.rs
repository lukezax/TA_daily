use sysinfo::System;

#[derive(Debug, Clone)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    pub cpu_usage: f64,
    pub memory_usage: f64,
    pub memory_rss: u64,
    pub status: String,
    pub user: String,
}

pub fn get_process_info(sys: &System) -> Vec<ProcessInfo> {
    let mut processes = Vec::new();
    
    for (pid, process) in sys.processes() {
        let memory_rss = process.memory();
        let memory_usage = (memory_rss as f64 / sys.total_memory() as f64) * 100.0;
        
        processes.push(ProcessInfo {
            pid: pid.as_u32(),
            name: process.name().to_string_lossy().to_string(),
            cpu_usage: process.cpu_usage() as f64,
            memory_usage,
            memory_rss,
            status: format!("{:?}", process.status()),
            user: String::new(),
        });
    }
    
    // Sort by CPU usage
    processes.sort_by(|a, b| b.cpu_usage.partial_cmp(&a.cpu_usage).unwrap_or(std::cmp::Ordering::Equal));
    
    processes
}
