use std::{path::Path, time::{Duration, Instant}};
fn main() {
    let a: Vec<String> = std::env::args().collect();
    assert_eq!(a.len(), 7, "usage: lock checkpoint manifest revision min-probability min-margin threads");
    let policy = pure_jeff::Policy {
        min_probability: a[4].parse().unwrap(),
        min_margin: a[5].parse().unwrap(),
        cpu_threads: a[6].parse().unwrap(),
    };
    let sha = pure_jeff::lock(Path::new(&a[1]), Path::new(&a[2]), &a[3], policy,
                              Instant::now() + Duration::from_secs(600)).unwrap();
    println!("{sha}");
}
