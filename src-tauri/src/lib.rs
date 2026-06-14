// Native shell glue: spawn the Python FastAPI backend as a child process on a free
// localhost port, wait until it's healthy, then open the webview pointed at it. The
// existing React UI (built into ../frontend/dist) talks to the backend over HTTP exactly
// as it does in the webapp — the only difference is the base URL, injected below.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

// Holds the backend child so we can kill it when the app exits.
struct Backend(Mutex<Option<Child>>);

// Ask the OS for an unused TCP port (bind to :0, read the assigned port, drop the listener).
fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .expect("could not allocate a local port")
}

// Poll GET /api/stats until it answers 200 (uvicorn up + app imported) or we time out.
fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if probe(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn probe(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_millis(1500)));
    let req = format!(
        "GET /api/stats HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if s.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 64];
    match s.read(&mut buf) {
        Ok(n) if n > 0 => String::from_utf8_lossy(&buf[..n]).contains(" 200 "),
        _ => false,
    }
}

// Build the command that launches the backend. In dev we run the repo's uv project; in a
// bundled .app we run the embedded relocatable Python interpreter against the bundled source.
fn backend_command(app: &tauri::App, port: u16, data_dir: &Path, hf_dir: &Path) -> Command {
    let port_s = port.to_string();
    let mut cmd;

    if cfg!(debug_assertions) {
        // Dev: `uv run uvicorn ...` from the repo backend dir. uv + ffmpeg come from the
        // inherited PATH (Homebrew). CARGO_MANIFEST_DIR is .../src-tauri at compile time.
        let backend = PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../backend"));
        cmd = Command::new("uv");
        cmd.current_dir(backend);
        cmd.args([
            "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", &port_s,
        ]);
    } else {
        // Bundled: embedded Python interpreter + backend source shipped under Resources.
        let res = app.path().resource_dir().expect("resource_dir");
        let py = res.join("resources/pyenv/bin/python3.12");
        let backend = res.join("resources/backend");
        let bin = res.join("resources/bin");
        cmd = Command::new(py);
        cmd.current_dir(&backend);
        cmd.args([
            "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", &port_s,
        ]);
        // Prepend bundled ffmpeg/ffprobe so the backend's bare-name subprocess calls resolve.
        let path = std::env::var("PATH").unwrap_or_default();
        cmd.env("PATH", format!("{}:{}", bin.display(), path));
    }

    // Writable, persistent locations outside the read-only bundle.
    cmd.env("AUDIO_SEARCH_DATA", data_dir);
    cmd.env("HF_HOME", hf_dir);
    cmd.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    cmd
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let port = free_port();

            // ~/Library/Application Support/<identifier>/{data,hf}
            let support = app.path().app_data_dir().expect("app_data_dir");
            let data_dir = support.join("data");
            let hf_dir = support.join("hf");
            std::fs::create_dir_all(&data_dir).ok();
            std::fs::create_dir_all(&hf_dir).ok();

            let child = backend_command(app, port, &data_dir, &hf_dir)
                .spawn()
                .expect("failed to spawn the Python backend");
            app.manage(Backend(Mutex::new(Some(child))));

            // Block setup until the backend answers (or we give up) so the UI never loads
            // against a dead port. First launch can be slow if Python is cold.
            if !wait_for_health(port, Duration::from_secs(120)) {
                log::error!("backend did not become healthy on port {port}");
            }

            // Inject the backend base URL before any page script runs, then open the window.
            let init = format!(
                "window.__AUDIO_SEARCH_API__ = \"http://127.0.0.1:{port}\";"
            );
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Audio Search")
                .inner_size(1180.0, 780.0)
                .min_inner_size(720.0, 480.0)
                .initialization_script(&init)
                .build()?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Tauri application")
        .run(|app, event| {
            // Make sure the backend dies with the app.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(backend) = app.try_state::<Backend>() {
                    if let Some(mut child) = backend.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
