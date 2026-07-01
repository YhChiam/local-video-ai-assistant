#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use tauri::{WebviewWindow, Emitter};
use tonic::transport::Channel;

pub mod video_ai {
    // Pulls in the stubs generated cleanly by tonic
    tonic::include_proto!("videoai"); 
}

use video_ai::video_ai_service_client::VideoAiServiceClient;
use video_ai::ChatRequest;

#[derive(Clone, Serialize, Deserialize)]
struct FrontendChunkPayload {
    r#type: String,
    content: String,
    clarification_options: Vec<String>,
    file_url: String,
}

async fn connect_with_fallback() -> Result<VideoAiServiceClient<Channel>, String> {
    for port in 50051..50061 {
        let address = format!("http://127.0.0.1:{}", port);
        match VideoAiServiceClient::connect(address.clone()).await {
            Ok(client) => return Ok(client),
            Err(err) => {
                println!("⏳ Trying gRPC endpoint {}: {}", address, err);
            }
        }
    }

    Err("Could not connect to the Python backend on any expected gRPC port".to_string())
}

#[tauri::command]
async fn route_agent_query(
    window: WebviewWindow, 
    user_query: String,
    video_path: String,
    is_clarification: bool,
    selected_option: String,
) -> Result<(), String> {
    println!("📡 Forwarding UI query to live Python gRPC server: {}", user_query);

    // 1. Establish connection to your active local Python server channel
    let mut client = connect_with_fallback().await?;

    // 2. Build the exact Request format required by your proto contract
    let request = tonic::Request::new(ChatRequest {
        user_query,
        video_path,
        is_clarification_response: is_clarification,
        selected_option,
    });

    // 3. Call the streaming endpoint on your backend
    let mut stream = client.chat_stream(request)
        .await
        .map_err(|e| format!("gRPC Stream Error: {}", e))?
        .into_inner();

    // 4. Listen asynchronously and push chunks straight to React
    while let Some(response) = stream.message().await.map_err(|e| e.to_string())? {
        let payload = FrontendChunkPayload {
            // Converts the proto response integer cleanly to standard text strings safely
            r#type: format!("{}", response.r#type), 
            content: response.content,
            clarification_options: response.clarification_options,
            file_url: response.file_url,
        };
        
        let _ = window.emit("grpc-chunk-received", payload);
    }

    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_shell::init()) 
        .plugin(tauri_plugin_dialog::init()) 
        .invoke_handler(tauri::generate_handler![route_agent_query])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}