//! Local evaluation only: a Python interpreter whose start-up takes SLOW_PYTHON_DELAY_MS longer.
//! Sleeps, then runs REAL_PYTHON with the same arguments and exits with its status.
use std::{env, process::{exit, Command}, thread, time::Duration};
fn main() {
    let delay: u64 = env::var("SLOW_PYTHON_DELAY_MS").ok().and_then(|v| v.parse().ok()).unwrap_or(0);
    thread::sleep(Duration::from_millis(delay));
    let status = Command::new(env::var("REAL_PYTHON").unwrap()).args(env::args().skip(1)).status().unwrap();
    exit(status.code().unwrap_or(1));
}
