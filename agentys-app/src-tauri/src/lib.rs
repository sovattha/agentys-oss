use std::env;
use std::collections::HashMap;
use std::sync::Mutex;
use std::process::{Child, Command};
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use serde::{Deserialize, Serialize};

/// State to hold the Python backend child process
pub struct BackendProcess(pub Mutex<Option<Child>>);

/// Walk up the directory tree from the exe to find the folder containing run_api.py
fn find_backend_dir() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent()?.to_path_buf();
    for _ in 0..8 {
        if dir.join("run_api.py").exists() {
            return Some(dir);
        }
        match dir.parent() {
            Some(p) => dir = p.to_path_buf(),
            None => break,
        }
    }
    None
}

/// Find the Python executable: prefer venv, fall back to system python
fn find_python(backend_dir: &std::path::Path) -> String {
    #[cfg(target_os = "windows")]
    {
        let venv = backend_dir.join(".venv/Scripts/python.exe");
        if venv.exists() {
            return venv.to_string_lossy().to_string();
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        let venv = backend_dir.join(".venv/bin/python");
        if venv.exists() {
            return venv.to_string_lossy().to_string();
        }
    }
    "python".to_string()
}

/// State to store shortcuts configuration
pub struct ShortcutsState {
    config: Mutex<HashMap<String, String>>,
}

impl Default for ShortcutsState {
    fn default() -> Self {
        Self {
            config: Mutex::new(HashMap::new()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShortcutBinding {
    pub id: String,
    pub binding: String,
}

/// Check if the app was launched with --minimized flag
/// This is used for autostart - app launches in background with tray icon only
fn is_minimized_launch() -> bool {
    env::args().any(|arg| arg == "--minimized")
}

#[tauri::command]
fn is_minimized_start() -> bool {
    is_minimized_launch()
}

#[tauri::command]
fn trigger_sync(app_handle: tauri::AppHandle) {
    // Emit event to frontend to trigger sync
    if let Some(window) = app_handle.get_webview_window("main") {
        let _ = window.emit("trigger-sync", ());
    }
}

#[tauri::command]
fn get_shortcuts_config(state: State<ShortcutsState>) -> Result<String, String> {
    let config = state.config.lock().map_err(|e| e.to_string())?;
    serde_json::to_string(&*config).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_shortcuts_config(
    config: String,
    state: State<ShortcutsState>,
) -> Result<(), String> {
    let parsed: HashMap<String, String> = serde_json::from_str(&config).map_err(|e| e.to_string())?;
    let mut current = state.config.lock().map_err(|e| e.to_string())?;
    *current = parsed;
    log::info!("Shortcuts config updated: {:?}", *current);
    Ok(())
}

#[tauri::command]
fn update_tray_unread_count(app_handle: tauri::AppHandle, count: u32) {
    if let Some(tray) = app_handle.tray_by_id("main-tray") {
        let tooltip = if count > 0 {
            format!(
                "Agentys - {} email{} non lu{}",
                count,
                if count > 1 { "s" } else { "" },
                if count > 1 { "s" } else { "" }
            )
        } else {
            "Agentys - Assistant IA Email".to_string()
        };
        let _ = tray.set_tooltip(Some(&tooltip));

        // On macOS, show count in menu bar
        if count > 0 {
            let title = if count > 99 {
                "99+".to_string()
            } else {
                count.to_string()
            };
            let _ = tray.set_title(Some(&title));
        } else {
            let _ = tray.set_title(None::<&str>);
        }
    }
}

/// Open a URL in the system's default browser
/// This uses the native OS command to ensure it opens in a real browser,
/// Validate a URL before passing it to the OS URL handler.
/// Extracted for unit-testability — see `#[cfg(test)]` at the bottom of this file.
fn validate_url_for_browser(url: &str) -> Result<(), String> {
    let lower = url.to_ascii_lowercase();
    if !(lower.starts_with("http://") || lower.starts_with("https://")) {
        return Err("Only http(s) URLs are allowed".into());
    }
    // Defense-in-depth: reject literal shell metacharacters.
    // Note: percent-encoded forms (e.g. %26 for '&') are NOT caught here because
    // '%', '2', '6' are safe chars. This is intentional — rundll32
    // url.dll,FileProtocolHandler passes the URL verbatim to the browser without
    // shell interpretation, so %26 is never decoded as '&' at the OS level.
    // If this ever regresses to `cmd /C start`, the test
    // `url_validator_percent_encoded_passthrough` will document the gap and prompt
    // the developer to add percent-decoding before the check.
    for c in url.chars() {
        if c.is_control()
            || c == '"'
            || c == '\''
            || c == '&'
            || c == '|'
            || c == '<'
            || c == '>'
            || c == '^'
            || c == '`'
            || c == '\n'
            || c == '\r'
        {
            return Err("URL contains forbidden characters".into());
        }
    }
    Ok(())
}

/// not in an embedded webview
#[tauri::command]
fn open_url_in_browser(url: String) -> Result<(), String> {
    validate_url_for_browser(&url)?;

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {}", e))?;
    }

    #[cfg(target_os = "windows")]
    {
        // rundll32 url.dll,FileProtocolHandler does NOT spawn cmd.exe, so the
        // metachar parsing that made `cmd /C start "" <url>` injection-prone
        // is gone. The validation above is still the primary gate.
        std::process::Command::new("rundll32")
            .args(["url.dll,FileProtocolHandler", &url])
            .spawn()
            .map_err(|e| format!("Failed to open URL: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {}", e))?;
    }

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .plugin(tauri_plugin_keyring::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state != ShortcutState::Pressed {
                        return;
                    }

                    // Cmd/Ctrl+Shift+A: Toggle window visibility (AC2)
                    if shortcut.matches(Modifiers::SUPER | Modifiers::SHIFT, Code::KeyA)
                        || shortcut.matches(Modifiers::CONTROL | Modifiers::SHIFT, Code::KeyA)
                    {
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.unminimize();
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }

                    // Cmd/Ctrl+N: Open compose window (AC3)
                    if shortcut.matches(Modifiers::SUPER, Code::KeyN)
                        || shortcut.matches(Modifiers::CONTROL, Code::KeyN)
                    {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("navigate", "/compose");
                        }
                    }

                    // Cmd/Ctrl+Shift+R: Trigger sync (AC4)
                    if shortcut.matches(Modifiers::SUPER | Modifiers::SHIFT, Code::KeyR)
                        || shortcut.matches(Modifiers::CONTROL | Modifiers::SHIFT, Code::KeyR)
                    {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.emit("trigger-sync", ());
                        }
                    }

                    // Cmd/Ctrl+/: Show keyboard shortcuts help (AC5)
                    if shortcut.matches(Modifiers::SUPER, Code::Slash)
                        || shortcut.matches(Modifiers::CONTROL, Code::Slash)
                    {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("show-shortcuts-help", ());
                        }
                    }
                })
                .build(),
        )
        .manage(ShortcutsState::default())
        .plugin(tauri_plugin_store::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            is_minimized_start,
            trigger_sync,
            update_tray_unread_count,
            get_shortcuts_config,
            set_shortcuts_config,
            open_url_in_browser
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // --- Spawn Python backend ---
            match find_backend_dir() {
                Some(backend_dir) => {
                    let python = find_python(&backend_dir);
                    log::info!("[backend] Démarrage avec {} dans {:?}", python, backend_dir);
                    match Command::new(&python)
                        .arg("run_api.py")
                        .current_dir(&backend_dir)
                        .spawn()
                    {
                        Ok(child) => {
                            log::info!("[backend] Démarré (pid: {})", child.id());
                            app.manage(BackendProcess(Mutex::new(Some(child))));
                        }
                        Err(e) => {
                            log::error!("[backend] Échec du démarrage : {}", e);
                            app.manage(BackendProcess(Mutex::new(None)));
                        }
                    }
                }
                None => {
                    log::warn!("[backend] run_api.py introuvable — backend non démarré");
                    app.manage(BackendProcess(Mutex::new(None)));
                }
            }

            // Build tray menu items with keyboard shortcuts displayed
            // Section: Main actions
            let open_item = MenuItemBuilder::with_id("open", "Ouvrir Agentys")
                .accelerator("CmdOrCtrl+Shift+A")
                .build(app)?;

            let new_message_item = MenuItemBuilder::with_id("new-message", "Nouveau message")
                .accelerator("CmdOrCtrl+N")
                .build(app)?;

            let separator1 = PredefinedMenuItem::separator(app)?;

            // Section: Status and recent emails
            let status_item = MenuItemBuilder::with_id("status", "0 email non lu")
                .enabled(false)
                .build(app)?;

            // Recent emails submenu (initially empty, will be populated by frontend)
            let recent_email_placeholder =
                MenuItemBuilder::with_id("recent-empty", "Aucun email récent")
                    .enabled(false)
                    .build(app)?;

            let recent_submenu = SubmenuBuilder::with_id(app, "recent-emails", "Récents")
                .item(&recent_email_placeholder)
                .build()?;

            let separator2 = PredefinedMenuItem::separator(app)?;

            // Section: Actions
            let sync_item = MenuItemBuilder::with_id("sync", "Sync maintenant")
                .accelerator("CmdOrCtrl+Shift+S")
                .build(app)?;

            let my_style_item = MenuItemBuilder::with_id("my-style", "Mon Style").build(app)?;

            let settings_item = MenuItemBuilder::with_id("settings", "Paramètres...")
                .accelerator("CmdOrCtrl+,")
                .build(app)?;

            let shortcuts_help_item = MenuItemBuilder::with_id("shortcuts-help", "Raccourcis clavier")
                .accelerator("CmdOrCtrl+/")
                .build(app)?;

            let separator3 = PredefinedMenuItem::separator(app)?;

            // Section: About and Quit
            let about_item = MenuItemBuilder::with_id("about", "À propos").build(app)?;

            let quit_item = MenuItemBuilder::with_id("quit", "Quitter")
                .accelerator("CmdOrCtrl+Q")
                .build(app)?;

            // Build the menu with all items
            let menu = MenuBuilder::new(app)
                .items(&[
                    &open_item,
                    &new_message_item,
                    &separator1,
                    &status_item,
                    &recent_submenu,
                    &separator2,
                    &sync_item,
                    &my_style_item,
                    &settings_item,
                    &shortcuts_help_item,
                    &separator3,
                    &about_item,
                    &quit_item,
                ])
                .build()?;

            // If launched with --minimized (autostart), hide the main window
            // User can open it via tray icon click
            if is_minimized_launch() {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                    log::info!("Started in minimized mode - window hidden");
                }
            }

            // Register global shortcuts (AC1, AC6)
            // These work even when the app is not focused
            #[cfg(desktop)]
            {
                let global_shortcut = app.global_shortcut();

                // Define shortcuts to register
                let shortcuts_to_register = [
                    // Toggle window: Cmd/Ctrl+Shift+A
                    Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyA),
                    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyA),
                    // New message: Cmd/Ctrl+N
                    Shortcut::new(Some(Modifiers::SUPER), Code::KeyN),
                    Shortcut::new(Some(Modifiers::CONTROL), Code::KeyN),
                    // Sync: Cmd/Ctrl+Shift+R
                    Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyR),
                    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR),
                    // Shortcuts help: Cmd/Ctrl+/
                    Shortcut::new(Some(Modifiers::SUPER), Code::Slash),
                    Shortcut::new(Some(Modifiers::CONTROL), Code::Slash),
                ];

                // Register each shortcut, handling conflicts gracefully (AC6)
                for shortcut in shortcuts_to_register {
                    match global_shortcut.register(shortcut) {
                        Ok(_) => {
                            log::info!("Global shortcut registered: {:?}", shortcut);
                        }
                        Err(e) => {
                            // Log warning but continue - don't fail app startup (AC6)
                            log::warn!(
                                "Failed to register global shortcut {:?}: {}. May conflict with system shortcut.",
                                shortcut,
                                e
                            );
                        }
                    }
                }
            }

            // Build the tray icon
            let _tray = TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("Agentys - Assistant IA Email")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "new-message" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("navigate", "/compose");
                        }
                    }
                    "sync" => {
                        // Emit sync event to frontend
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.emit("trigger-sync", ());
                        }
                    }
                    "my-style" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("navigate", "/my-style");
                        }
                    }
                    "settings" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("navigate", "/settings");
                        }
                    }
                    "shortcuts-help" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("show-shortcuts-help", ());
                        }
                    }
                    "about" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("show-about", ());
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    id => {
                        // Handle recent email clicks (id format: "recent-email-{index}")
                        if id.starts_with("recent-email-") {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.unminimize();
                                let _ = window.show();
                                let _ = window.set_focus();
                                // Emit event with email index to navigate to specific email
                                let _ = window.emit("open-recent-email", id);
                            }
                        }
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    // Left click opens the main window
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            log::info!("[backend] Processus Python arrêté");
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::validate_url_for_browser;

    #[test]
    fn url_validator_blocks_non_http_schemes() {
        assert!(validate_url_for_browser("javascript:alert(1)").is_err());
        assert!(validate_url_for_browser("file:///etc/passwd").is_err());
        assert!(validate_url_for_browser("mailto:x@y.com").is_err());
    }

    #[test]
    fn url_validator_blocks_literal_shell_metachars() {
        assert!(validate_url_for_browser("https://x.com/page&evil=1").is_err());
        assert!(validate_url_for_browser("https://x.com/<script>").is_err());
        assert!(validate_url_for_browser("https://x.com/a|b").is_err());
        assert!(validate_url_for_browser("https://x.com/a^b").is_err());
    }

    #[test]
    fn url_validator_percent_encoded_passthrough() {
        // Audit 2026-04-25 Caveat A: percent-encoded metacharacters (%26 for '&',
        // %3C for '<') pass the literal-char check because '%', '2', '6' are not
        // in the denylist. This is safe because rundll32 url.dll,FileProtocolHandler
        // does NOT interpret percent-sequences as shell metacharacters — it passes
        // the URL verbatim to the registered browser.
        // IMPORTANT: if this validator is ever called before `cmd /C start`,
        // percent-decoding MUST be added before the char check.
        assert!(validate_url_for_browser("https://x.com/%26calc.exe").is_ok());
        assert!(validate_url_for_browser("https://x.com/%3Cscript%3E").is_ok());
    }

    #[test]
    fn url_validator_allows_clean_https() {
        assert!(validate_url_for_browser("https://app.agentys.io/email/123").is_ok());
        assert!(validate_url_for_browser("http://localhost:5050/api/health").is_ok());
    }
}
