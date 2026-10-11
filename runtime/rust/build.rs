use std::{env, process::Command};
fn main() {
    let rustc = Command::new(env::var_os("RUSTC").unwrap())
        .arg("--version")
        .output()
        .expect("rustc version");
    assert!(rustc.status.success());
    let info = format!(
        "{};{};{};{:?}",
        String::from_utf8(rustc.stdout).unwrap().trim(),
        env::var("TARGET").unwrap(),
        env::var("PROFILE").unwrap(),
        env::var("CARGO_ENCODED_RUSTFLAGS").unwrap_or_default()
    );
    println!("cargo:rustc-env=KAZE_JEFF_BUILD_INFO={info}");
    println!("cargo:rerun-if-env-changed=CARGO_ENCODED_RUSTFLAGS");
}
