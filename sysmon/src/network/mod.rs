use std::fs;

#[derive(Debug, Clone)]
pub struct NetworkInfo {
    pub interfaces: Vec<NetworkInterface>,
    pub total_rx: u64,
    pub total_tx: u64,
}

#[derive(Debug, Clone)]
pub struct NetworkInterface {
    pub name: String,
    pub rx_bytes: u64,
    pub tx_bytes: u64,
    pub rx_rate: f64,
    pub tx_rate: f64,
}

impl Default for NetworkInfo {
    fn default() -> Self {
        Self {
            interfaces: Vec::new(),
            total_rx: 0,
            total_tx: 0,
        }
    }
}

pub fn get_network_info() -> NetworkInfo {
    let mut info = NetworkInfo::default();
    
    if let Ok(stat_content) = fs::read_to_string("/proc/net/dev") {
        for line in stat_content.lines().skip(2) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 10 {
                let name = parts[0].trim_end_matches(':').to_string();
                if name == "lo" {
                    continue;
                }
                
                let rx_bytes: u64 = parts[1].parse().unwrap_or(0);
                let tx_bytes: u64 = parts[9].parse().unwrap_or(0);
                
                info.total_rx += rx_bytes;
                info.total_tx += tx_bytes;
                
                info.interfaces.push(NetworkInterface {
                    name,
                    rx_bytes,
                    tx_bytes,
                    rx_rate: 0.0,
                    tx_rate: 0.0,
                });
            }
        }
    }
    
    info
}
