// frontend/src-tauri/build.rs
use std::{env, fs, path::{Path, PathBuf}};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo::rustc-check-cfg=cfg(mobile)");
    println!("cargo:rerun-if-changed=../../backend/schema.proto");
    println!("cargo:rerun-if-env-changed=PROTOC");

    if env::var_os("PROTOC").is_none() {
        if let Some(protoc_path) = find_protoc() {
            env::set_var("PROTOC", &protoc_path);
        } else if let Some(wrapper_path) = write_protoc_wrapper()? {
            env::set_var("PROTOC", &wrapper_path);
        }
    }

    tonic_build::configure()
        .build_server(false)
        .compile(
            &["../../backend/schema.proto"],
            &["../../backend/"],
        )?;

    tauri_build::build();

    Ok(())
}

fn find_protoc() -> Option<PathBuf> {
    if let Ok(path) = env::var("PROTOC") {
        if !path.trim().is_empty() {
            return Some(PathBuf::from(path));
        }
    }

    for name in ["protoc", "protoc.exe"] {
        if let Ok(path) = which::which(name) {
            return Some(path);
        }
    }

    None
}

fn write_protoc_wrapper() -> Result<Option<PathBuf>, Box<dyn std::error::Error>> {
    let out_dir = PathBuf::from(env::var("OUT_DIR")?);
    let wrapper_path = if cfg!(windows) {
        out_dir.join("protoc.cmd")
    } else {
        out_dir.join("protoc")
    };

    let grpc_tools_protoc = PathBuf::from(r"C:\yhchiam\local-video-ai-assistant\backend\venv\Scripts\python-grpc-tools-protoc.exe");
    let script = if cfg!(windows) {
        format!("@echo off\r\n\"{}\" %*\r\n", grpc_tools_protoc.display())
    } else {
        format!("#!/bin/sh\nexec \"{}\" \"$@\"\n", grpc_tools_protoc.display())
    };

    fs::write(&wrapper_path, script)?;

    if !cfg!(windows) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = fs::metadata(&wrapper_path)?.permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(&wrapper_path, permissions)?;
        }
    }

    Ok(Some(wrapper_path))
}

fn find_python() -> Result<PathBuf, Box<dyn std::error::Error>> {
    if let Ok(path) = env::var("VIRTUAL_ENV") {
        let candidate = Path::new(&path).join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" });
        if candidate.exists() {
            return Ok(candidate);
        }
    }

    if let Ok(path) = env::var("CONDA_PREFIX") {
        let candidate = Path::new(&path).join(if cfg!(windows) { "python.exe" } else { "bin/python" });
        if candidate.exists() {
            return Ok(candidate);
        }
    }

    for name in ["python", "python3", "python.exe"] {
        if let Ok(path) = which::which(name) {
            return Ok(path);
        }
    }

    Err("Could not find a Python interpreter to provide protoc".into())
}