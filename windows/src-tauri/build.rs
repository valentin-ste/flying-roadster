// The report's build line: ROADSTER_GIT and ROADSTER_BUILD_TIME come from windows/build.sh; ROADSTER_SELFTEST
// (build.sh --test) puts Self-test in the tray menu (main.rs reads it with option_env!).
fn main() {
    println!("cargo:rerun-if-env-changed=ROADSTER_SELFTEST");
    for (k, fallback) in [("ROADSTER_GIT", "no git"), ("ROADSTER_BUILD_TIME", "unknown")] {
        println!("cargo:rerun-if-env-changed={k}");
        let v = std::env::var(k).unwrap_or_else(|_| fallback.to_string());
        println!("cargo:rustc-env={k}={v}");
    }
    tauri_build::build()
}
