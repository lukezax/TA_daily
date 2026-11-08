use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Cell, Row, Table, Gauge, Paragraph},
};

use crate::cpu::CpuInfo;
use crate::memory::MemoryInfo;
use crate::gpu::GpuInfo;
use crate::network::NetworkInfo;
use crate::process::ProcessInfo;

pub fn draw(frame: &mut Frame, cpu: &CpuInfo, memory: &MemoryInfo, gpus: &[GpuInfo], network: &NetworkInfo, processes: &[ProcessInfo]) {
    let size = frame.area();
    
    let main_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage(30),
            Constraint::Percentage(30),
            Constraint::Percentage(40),
        ])
        .split(size);
    
    // Top row: GPU + CPU
    let top_layout = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(50),
            Constraint::Percentage(50),
        ])
        .split(main_layout[0]);
    
    draw_gpu_panel(frame, top_layout[0], gpus);
    draw_cpu_panel(frame, top_layout[1], cpu);
    
    // Middle row: Memory + Network
    let middle_layout = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(50),
            Constraint::Percentage(50),
        ])
        .split(main_layout[1]);
    
    draw_memory_panel(frame, middle_layout[0], memory);
    draw_network_panel(frame, middle_layout[1], network);
    
    // Bottom row: Processes
    draw_process_panel(frame, main_layout[2], processes);
}

fn draw_gpu_panel(frame: &mut Frame, area: Rect, gpus: &[GpuInfo]) {
    let block = Block::default()
        .title(" GPU ")
        .borders(Borders::ALL)
        .style(Style::default().fg(Color::Cyan));
    
    if gpus.is_empty() {
        let text = Paragraph::new("No GPU detected").block(block);
        frame.render_widget(text, area);
        return;
    }
    
    let gpu = &gpus[0];
    
    let mut lines = vec![
        Line::from(vec![
            Span::styled("Name: ", Style::default().fg(Color::White)),
            Span::raw(&gpu.name),
        ]),
        Line::from(vec![
            Span::styled("Utilization: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.1}%", gpu.utilization)),
        ]),
        Line::from(vec![
            Span::styled("Memory: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.3} MB / {:.3} MB", gpu.memory_used, gpu.memory_total)),
        ]),
        Line::from(vec![
            Span::styled("Temperature: ", Style::default().fg(Color::White)),
            Span::styled(format!("{:.1}°C", gpu.temperature), 
                if gpu.temperature > 80.0 { Style::default().fg(Color::Red) }
                else if gpu.temperature > 60.0 { Style::default().fg(Color::Yellow) }
                else { Style::default().fg(Color::Green) }),
        ]),
        Line::from(vec![
            Span::styled("Power: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.1} W", gpu.power)),
        ]),
    ];
    
    if !gpu.processes.is_empty() {
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled("GPU Processes:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD))));
        
        for proc in gpu.processes.iter().take(5) {
            lines.push(Line::from(vec![
                Span::styled(format!("  PID {}: ", proc.pid), Style::default().fg(Color::Gray)),
                Span::raw(&proc.process_name),
                Span::styled(format!(" ({:.1} MB)", proc.memory_used), Style::default().fg(Color::Gray)),
            ]));
        }
    }
    
    let paragraph = Paragraph::new(lines).block(block);
    frame.render_widget(paragraph, area);
}

fn draw_cpu_panel(frame: &mut Frame, area: Rect, cpu: &CpuInfo) {
    let block = Block::default()
        .title(" CPU ")
        .borders(Borders::ALL)
        .style(Style::default().fg(Color::Green));
    
    let lines = vec![
        Line::from(vec![
            Span::styled("Model: ", Style::default().fg(Color::White)),
            Span::raw(&cpu.model_name),
        ]),
        Line::from(vec![
            Span::styled("Cores/Threads: ", Style::default().fg(Color::White)),
            Span::raw(format!("{}/{}", cpu.cores, cpu.threads)),
        ]),
        Line::from(vec![
            Span::styled("Frequency: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.2} MHz", cpu.frequency)),
        ]),
        Line::from(vec![
            Span::styled("Load Average: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.2}, {:.2}, {:.2}", cpu.load_avg[0], cpu.load_avg[1], cpu.load_avg[2])),
        ]),
        Line::from(""),
        Line::from(vec![
            Span::styled("CPU Usage: ", Style::default().fg(Color::White)),
            Span::styled(format!("{:.1}%", cpu.usage),
                if cpu.usage > 80.0 { Style::default().fg(Color::Red) }
                else if cpu.usage > 50.0 { Style::default().fg(Color::Yellow) }
                else { Style::default().fg(Color::Green) }),
        ]),
    ];
    
    let paragraph = Paragraph::new(lines).block(block);
    frame.render_widget(paragraph, area);
    
    // Usage bar below
    let bar_area = Rect {
        x: area.x + 1,
        y: area.y + area.height.saturating_sub(3),
        width: area.width.saturating_sub(2),
        height: 1,
    };
    
    let gauge = Gauge::default()
        .block(Block::default())
        .gauge_style(Style::default().fg(Color::Green).bg(Color::Black))
        .ratio(cpu.usage / 100.0);
    
    frame.render_widget(gauge, bar_area);
}

fn draw_memory_panel(frame: &mut Frame, area: Rect, memory: &MemoryInfo) {
    let block = Block::default()
        .title(" Memory ")
        .borders(Borders::ALL)
        .style(Style::default().fg(Color::Magenta));
    
    let lines = vec![
        Line::from(vec![
            Span::styled("Physical: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.3} MB / {:.3} MB ({:.1}%)", 
                memory.used, memory.total, (memory.used / memory.total) * 100.0)),
        ]),
        Line::from(vec![
            Span::styled("Swap: ", Style::default().fg(Color::White)),
            Span::raw(format!("{:.3} MB / {:.3} MB ({:.1}%)", 
                memory.swap_used, memory.swap_total, 
                if memory.swap_total > 0.0 { (memory.swap_used / memory.swap_total) * 100.0 } else { 0.0 })),
        ]),
    ];
    
    let paragraph = Paragraph::new(lines).block(block);
    frame.render_widget(paragraph, area);
    
    // Memory bar
    let bar_area = Rect {
        x: area.x + 1,
        y: area.y + 2,
        width: area.width.saturating_sub(2),
        height: 1,
    };
    
    let mem_ratio = memory.used / memory.total;
    let gauge = Gauge::default()
        .block(Block::default())
        .gauge_style(Style::default().fg(Color::Magenta).bg(Color::Black))
        .ratio(mem_ratio);
    
    frame.render_widget(gauge, bar_area);
}

fn draw_network_panel(frame: &mut Frame, area: Rect, network: &NetworkInfo) {
    let block = Block::default()
        .title(" Network ")
        .borders(Borders::ALL)
        .style(Style::default().fg(Color::Yellow));
    
    let mut lines = vec![
        Line::from(vec![
            Span::styled("Total RX: ", Style::default().fg(Color::White)),
            Span::raw(format_bytes(network.total_rx)),
        ]),
        Line::from(vec![
            Span::styled("Total TX: ", Style::default().fg(Color::White)),
            Span::raw(format_bytes(network.total_tx)),
        ]),
        Line::from(""),
    ];
    
    for iface in &network.interfaces {
        lines.push(Line::from(vec![
            Span::styled(format!("{}: ", iface.name), Style::default().fg(Color::Yellow)),
            Span::styled(format!("↓{}", format_bytes(iface.rx_bytes)), Style::default().fg(Color::Green)),
            Span::raw("  "),
            Span::styled(format!("↑{}", format_bytes(iface.tx_bytes)), Style::default().fg(Color::Red)),
        ]));
    }
    
    let paragraph = Paragraph::new(lines).block(block);
    frame.render_widget(paragraph, area);
}

fn draw_process_panel(frame: &mut Frame, area: Rect, processes: &[ProcessInfo]) {
    let block = Block::default()
        .title(" Processes ")
        .borders(Borders::ALL)
        .style(Style::default().fg(Color::Blue));
    
    let header = Row::new(vec![
        Cell::from("PID").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Cell::from("Name").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Cell::from("CPU%").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Cell::from("MEM%").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Cell::from("RSS (MB)").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
    ]);
    
    let rows: Vec<Row> = processes.iter().take(20).map(|p| {
        let cpu_style = if p.cpu_usage > 50.0 { Style::default().fg(Color::Red) }
        else if p.cpu_usage > 20.0 { Style::default().fg(Color::Yellow) }
        else { Style::default().fg(Color::White) };
        
        let mem_style = if p.memory_usage > 10.0 { Style::default().fg(Color::Red) }
        else if p.memory_usage > 5.0 { Style::default().fg(Color::Yellow) }
        else { Style::default().fg(Color::White) };
        
        Row::new(vec![
            Cell::from(p.pid.to_string()),
            Cell::from(p.name.chars().take(20).collect::<String>()),
            Cell::from(format!("{:.1}", p.cpu_usage)).style(cpu_style),
            Cell::from(format!("{:.1}", p.memory_usage)).style(mem_style),
            Cell::from(format!("{:.1}", p.memory_rss as f64 / 1024.0 / 1024.0)),
            Cell::from(p.status.as_str()),
        ])
    }).collect();
    
    let table = Table::new(
        rows,
        [
            Constraint::Length(8),
            Constraint::Percentage(25),
            Constraint::Length(8),
            Constraint::Length(8),
            Constraint::Length(12),
            Constraint::Length(10),
        ]
    )
    .header(header)
    .block(block);
    
    frame.render_widget(table, area);
}

fn format_bytes(bytes: u64) -> String {
    if bytes >= 1024 * 1024 * 1024 {
        format!("{:.2} GB", bytes as f64 / 1024.0 / 1024.0 / 1024.0)
    } else if bytes >= 1024 * 1024 {
        format!("{:.2} MB", bytes as f64 / 1024.0 / 1024.0)
    } else if bytes >= 1024 {
        format!("{:.2} KB", bytes as f64 / 1024.0)
    } else {
        format!("{} B", bytes)
    }
}
