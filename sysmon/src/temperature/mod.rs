use std::fs;

#[derive(Debug, Clone)]
pub struct TemperatureInfo {
    pub cpu_temp: f64,
    pub gpu_temp: f64,
    pub temps: Vec<(String, f64)>,
}

impl Default for TemperatureInfo {
    fn default() -> Self {
        Self {
            cpu_temp: 0.0,
            gpu_temp: 0.0,
            temps: Vec::new(),
        }
    }
}

pub fn get_temperature_info() -> TemperatureInfo {
    let mut info = TemperatureInfo::default();
    
    // Try to read from thermal zones
    for i in 0..20 {
        let path = format!("/sys/class/thermal/thermal_zone{}", i);
        if let Ok(temp_type) = fs::read_to_string(format!("{}/type", path)) {
            if let Ok(temp_str) = fs::read_to_string(format!("{}/temp", path)) {
                if let Ok(temp) = temp_str.trim().parse::<f64>() {
                    let temp_c = temp / 1000.0;
                    let type_name = temp_type.trim().to_string();
                    
                    info.temps.push((type_name.clone(), temp_c));
                    
                    if type_name.contains("x86") || type_name.contains("core") || type_name.contains("cpu") {
                        info.cpu_temp = temp_c;
                    }
                }
            }
        }
    }
    
    info
}
