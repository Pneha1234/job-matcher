//! Desktop shell for Job Matcher.
//!
//! Shows a loading page, starts the FastAPI backend and the built Next.js UI as child
//! processes (unless they are already running, e.g. under `make dev`), then points the
//! window at the UI. Everything stays on this machine; the children are stopped when the
//! app quits.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const API_PORT: u16 = 8000;
const UI_PORT: u16 = 3000;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);

/// Child processes this app started, stopped again on exit.
struct Children(Mutex<Vec<Child>>);

/// The repository the app runs from: `JM_HOME`, or where this crate was built.
fn repo_root() -> PathBuf {
    if let Ok(home) = std::env::var("JM_HOME") {
        return PathBuf::from(home);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repository root")
}

fn port_open(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// Runs a command through a login shell so a Finder-launched app gets the user's PATH
/// (Homebrew node, pyenv). Each child leads its own process group, so stopping the group
/// also stops whatever it spawned (npm starts node, which starts Next.js).
fn spawn(cwd: PathBuf, command: &str, log: &str) -> std::io::Result<Child> {
    use std::os::unix::process::CommandExt;

    let log_dir = repo_root().join("data").join("logs");
    std::fs::create_dir_all(&log_dir)?;
    let out = std::fs::File::create(log_dir.join(log))?;
    Command::new("/bin/zsh")
        .args(["-lc", &format!("exec {command}")])
        .current_dir(cwd)
        .stdout(Stdio::from(out.try_clone()?))
        .stderr(Stdio::from(out))
        .process_group(0)
        .spawn()
}

fn start_services() -> Result<Vec<Child>, String> {
    let root = repo_root();
    let mut children = Vec::new();
    if !port_open(API_PORT) {
        let uvicorn = root.join(".venv/bin/uvicorn");
        if !uvicorn.exists() {
            return Err(format!(
                "{} is missing. Run `make setup` first.",
                uvicorn.display()
            ));
        }
        let cmd = format!("'{}' app.main:app --port {API_PORT}", uvicorn.display());
        children.push(spawn(root.clone(), &cmd, "api.log").map_err(|e| e.to_string())?);
    }
    if !port_open(UI_PORT) {
        let ui = root.join("ui");
        if !ui.join(".next/BUILD_ID").exists() {
            return Err(
                "The UI isn't built. Run `make desktop` (or `cd ui && npm run build`).".into(),
            );
        }
        let cmd = format!("npm run start -- --port {UI_PORT}");
        children.push(spawn(ui, &cmd, "ui.log").map_err(|e| e.to_string())?);
    }
    Ok(children)
}

fn wait_until_ready() -> bool {
    let started = Instant::now();
    while started.elapsed() < STARTUP_TIMEOUT {
        if port_open(API_PORT) && port_open(UI_PORT) {
            return true;
        }
        thread::sleep(Duration::from_millis(400));
    }
    false
}

fn stop(children: &mut Vec<Child>) {
    for child in children.iter_mut() {
        // Negative pid = the whole process group started for this child.
        let _ = Command::new("/bin/kill")
            .args(["-TERM", &format!("-{}", child.id())])
            .status();
        let _ = child.wait();
    }
    children.clear();
}

fn show_error(window: &tauri::WebviewWindow, message: &str) {
    let text = serde_json::to_string(message).unwrap_or_default();
    let _ = window.eval(format!(
        "const s = document.getElementById('status'); s.className = 'error'; s.textContent = {text};"
    ));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(Children(Mutex::new(Vec::new())))
        .setup(|app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Job Matcher")
                .inner_size(1360.0, 900.0)
                .min_inner_size(900.0, 600.0)
                .build()?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                match start_services() {
                    Ok(children) => handle.state::<Children>().0.lock().unwrap().extend(children),
                    Err(message) => return show_error(&window, &message),
                }
                if wait_until_ready() {
                    let url = format!("http://localhost:{UI_PORT}/jobs");
                    let _ = window.navigate(url.parse().expect("valid URL"));
                } else {
                    show_error(
                        &window,
                        "The API or UI didn't start within 90 seconds. See data/logs/api.log and data/logs/ui.log.",
                    );
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop(&mut app.state::<Children>().0.lock().unwrap());
            }
        });
}
