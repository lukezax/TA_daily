use sysinfo::System;

#[derive(Debug, Clone)]
pub struct CpuInfo {
    pub usage: f64,
    pub cores: usize,
    pub threads: usize,
    pub frequency: f64,
    pub temperature: f64,
    pub load_avg: [f64; 3],
    pub model_name: String,
}

impl Default for CpuInfo {
    fn default() -> Self {
        Self {
            usage: 0.0,
            cores: 0,
            threads: 0,
            frequency: 0.0,
            temperature: 0.0,
            load_avg: [0.0, 0.0, 0.0],
            model_name: String::new(),
        }
    }
}

pub fn get_cpu_info(sys: &System) -> CpuInfo {
    let cpus = sys.cpus();
    let usage = cpus.iter().map(|c| c.cpu_usage()).sum::<f32>() / cpus.len() as f32;
    
    let frequency = cpus.first().map(|c| c.frequency()).unwrap_or(0) as f64;
    
    let load_avg = System::load_average();
    
    CpuInfo {
        usage: usage as f64,
        cores: cpus.len(),
        threads: cpus.len(),
        frequency,
        temperature: 0.0,
        load_avg: [load_avg.one, load_avg.five, load_avg.fifteen],
        model_name: cpus.first().map(|c| c.brand().to_string()).unwrap_or_default(),
    }
}
