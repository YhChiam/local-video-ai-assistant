import grpc
from concurrent import futures
import os
import socket
import schema_pb2
import schema_pb2_grpc
from mcp_server import MCPServerTools


def find_available_port(start_port=50051, max_attempts=20):
    """Return the first free TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Could not find an available port for the gRPC server")

class MultiAgentOrchestrator(schema_pb2_grpc.VideoAIServiceServicer):
    
    def ChatStream(self, request, context):
        query = request.user_query.strip().lower()
        video_path = request.video_path
        
        if not video_path or not os.path.exists(video_path):
            yield schema_pb2.ChatResponse(
                type=schema_pb2.ChatResponse.TEXT_CHUNK,
                content="❌ **Missing File Context**: Please supply or browse for a valid `.mp4` file path first."
            )
            return

        workspace = os.path.join(os.path.dirname(__file__), "outputs")

        # --- Human-in-the-Loop Ambiguity Guard ---
        if not request.is_clarification_response:
            if any(keyword in query for keyword in ["analyze", "process", "run"]):
                yield schema_pb2.ChatResponse(
                    type=schema_pb2.ChatResponse.CLARIFICATION_REQUIRED,
                    content="Your execution instruction is open-ended. Which downstream tool should we route to?",
                    clarification_options=["Transcribe Video Audio", "Extract Object and Graph Visuals", "Generate PDF Summary Report"]
                )
                return

        # Handle explicit choice from a previous clarification routing loop
        routed_intent = request.selected_option.lower() if request.is_clarification_response else query

        # --- Sub-Agent Routing Execution ---
        if "transcribe" in routed_intent or "audio" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Transcription Agent initializing audio processing via MCP Whisper tool...*\n\n")
            transcript = MCPServerTools.call_transcription_tool(video_path)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=f"### Transcription Summary:\n{transcript}")

        elif "object" in routed_intent or "graph" in routed_intent or "visual" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Vision Agent sampling frame layouts via MCP OpenCV tool...*\n\n")
            vision_data = MCPServerTools.call_vision_tool(video_path)
            graph_msg = "Graphs or line tracking matrices detected." if vision_data["graphs_detected"] else "No presentation graphs observed."
            res_md = f"### Vision Report:\n* **Scene Content**: {vision_data['description']}\n* **Identified Metrics**: {', '.join(vision_data['objects'])}\n* **Graph State**: {graph_msg}"
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=res_md)

        elif "pdf" in routed_intent or "summary report" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Generation Agent writing data stream to PDF layout template...*\n\n")
            t = MCPServerTools.call_transcription_tool(video_path)
            v = MCPServerTools.call_vision_tool(video_path)["description"]
            file_path = MCPServerTools.call_pdf_generation_tool(t, v, workspace)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.REPORT_GENERATED, content="### 📄 PDF Generation Complete!", file_url=os.path.abspath(file_path))

        elif "powerpoint" in routed_intent or "ppt" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Generation Agent packing slide presentations via python-pptx...*\n\n")
            t = MCPServerTools.call_transcription_tool(video_path)
            v = MCPServerTools.call_vision_tool(video_path)["description"]
            file_path = MCPServerTools.call_ppt_generation_tool(t, v, workspace)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.REPORT_GENERATED, content="### 📊 PowerPoint Slides Created!", file_url=os.path.abspath(file_path))

        else:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="I couldn't confidently route that action. Try asking me to: *Transcribe*, *Detect Objects*, or *Generate PDF Summary Reports*.")

def serve():
    port = find_available_port()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    schema_pb2_grpc.add_VideoAIServiceServicer_to_server(MultiAgentOrchestrator(), server)
    server.add_insecure_port(f'127.0.0.1:{port}')
    print(f"🚀 Standalone Backend Agent Server live at localhost:{port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()