use sysinfo::System;

#[derive(Debug, Clone)]
pub struct MemoryInfo {
    pub total: f64,
    pub used: f64,
    pub free: f64,
    pub buffers: f64,
    pub cached: f64,
    pub swap_total: f64,
    pub swap_used: f64,
    pub swap_free: f64,
}

impl Default for MemoryInfo {
    fn default() -> Self {
        Self {
            total: 0.0,
            used: 0.0,
            free: 0.0,
            buffers: 0.0,
            cached: 0.0,
            swap_total: 0.0,
            swap_used: 0.0,
            swap_free: 0.0,
        }
    }
}

pub fn get_memory_info(sys: &System) -> MemoryInfo {
    MemoryInfo {
        total: sys.total_memory() as f64 / 1024.0 / 1024.0,
        used: sys.used_memory() as f64 / 1024.0 / 1024.0,
        free: sys.available_memory() as f64 / 1024.0 / 1024.0,
        buffers: 0.0,
        cached: 0.0,
        swap_total: sys.total_swap() as f64 / 1024.0 / 1024.0,
        swap_used: sys.used_swap() as f64 / 1024.0 / 1024.0,
        swap_free: sys.free_swap() as f64 / 1024.0 / 1024.0,
    }
}
