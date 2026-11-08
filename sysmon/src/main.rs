mod cpu;
mod memory;
mod gpu;
mod temperature;
mod network;
mod process;
mod ui;

use std::io;
use std::time::Duration;
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    Terminal,
};
use sysinfo::System;

fn main() -> io::Result<()> {
    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    
    // Create system info
    let mut sys = System::new_all();
    sys.refresh_all();
    
    // Main loop
    loop {
        // Refresh system info
        sys.refresh_all();
        
        // Get all system info
        let cpu = cpu::get_cpu_info(&sys);
        let memory = memory::get_memory_info(&sys);
        let gpus = gpu::get_gpu_info();
        let network = network::get_network_info();
        let processes = process::get_process_info(&sys);
        
        // Draw UI
        terminal.draw(|frame| {
            ui::draw(frame, &cpu, &memory, &gpus, &network, &processes);
        })?;
        
        // Handle input
        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('q') | KeyCode::Char('Q') => {
                            // Restore terminal
                            disable_raw_mode()?;
                            execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
                            terminal.show_cursor()?;
                            return Ok(());
                        }
                        _ => {}
                    }
                }
            }
        }
    }
}
