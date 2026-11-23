#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(code) = translator2k_lib::updater::maybe_run_apply_update_mode() {
        std::process::exit(code);
    }
    translator2k_lib::run();
}
