import grpc
from concurrent import futures
import os
import socket
import re
import schema_pb2
import schema_pb2_grpc
from mcp_server import MCPServerTools


def _is_no_speech_transcript(transcript: str) -> bool:
    text = (transcript or "").strip().lower()
    return text in {"", "(no speech detected)", "no speech detected"}


def _normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _clean_summary_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"[#*_`]+", "", cleaned)
    cleaned = cleaned.replace("📄", "").replace("📊", "").replace("🤖", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _intent_label(intent: str) -> str:
    label_map = {
        "transcribe": "Transcribe Video Audio",
        "vision": "Extract Object and Graph Visuals",
        "pdf": "Summarize Discussion and Generate PDF",
        "ppt": "Create PowerPoint with Key Points",
    }
    return label_map.get(intent, intent)


def _is_open_ended_request(query: str) -> bool:
    normalized = _normalize_query(query)
    generic_triggers = {"analyze", "process", "run", "handle", "do", "help"}
    tokens = set(normalized.split())
    return bool(tokens and tokens.issubset(generic_triggers))


def _build_clarification_options(ranked):
    top_two = [item[0] for item in ranked if item[1] > 0][:2]
    labels = [_intent_label(item) for item in top_two]
    if len(labels) >= 2:
        return labels[:2] + ["Can you provide more details?"]
    if len(labels) == 1:
        return [labels[0], "Can you provide more details?"]
    return [
        "Transcribe Video Audio",
        "Extract Object and Graph Visuals",
        "Can you provide more details?",
    ]


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

    def __init__(self):
        self.session_history = {}
        self.video_cache = {}

    def _history_for_video(self, video_path: str):
        return self.session_history.setdefault(video_path, [])

    def _cache_for_video(self, video_path: str):
        return self.video_cache.setdefault(video_path, {})

    def _append_history(self, video_path: str, role: str, text: str):
        history = self._history_for_video(video_path)
        history.append({"role": role, "text": text.strip()})
        if len(history) > 40:
            del history[:-40]

    def _build_discussion_summary(self, video_path: str) -> str:
        history = self._history_for_video(video_path)
        if not history:
            return "No prior discussion context available."

        lines = []
        user_items = [item["text"] for item in history if item["role"] == "user"]
        bot_items = [item["text"] for item in history if item["role"] == "assistant"]
        for idx, item in enumerate(user_items[-5:], start=1):
            lines.append(f"{idx}. User asked: {item}")
        for idx, item in enumerate(bot_items[-3:], start=1):
            cleaned_item = _clean_summary_text(item)
            trimmed = cleaned_item if len(cleaned_item) <= 180 else cleaned_item[:177] + "..."
            lines.append(f"{idx}. Assistant response: {trimmed}")
        return " ".join(lines) if lines else "No prior discussion context available."

    def _resolve_intent(self, query: str):
        normalized = _normalize_query(query)
        scores = {
            "transcribe": 0,
            "vision": 0,
            "pdf": 0,
            "ppt": 0,
        }

        keyword_map = {
            "transcribe": ["transcribe", "transcription", "speech", "audio", "captions"],
            "vision": ["object", "objects", "graph", "graphs", "visual", "image", "flag"],
            "pdf": ["pdf", "summary report", "summarize", "summarise", "discussion so far"],
            "ppt": ["powerpoint", "ppt", "slides", "deck", "key points"],
        }

        for intent, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword in normalized:
                    scores[intent] += 1

        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        top_intent, top_score = ranked[0]
        second_score = ranked[1][1]

        if top_score == 0:
            return None, True, ranked

        # Low confidence when multiple intents score similarly.
        low_confidence = second_score > 0 and (top_score - second_score) <= 1
        return top_intent, low_confidence, ranked

    def _get_cached_or_compute(self, video_path: str):
        cache = self._cache_for_video(video_path)
        transcript = cache.get("transcript")
        vision_data = cache.get("vision")
        if transcript is None:
            transcript = MCPServerTools.call_transcription_tool(video_path)
            cache["transcript"] = transcript
        if vision_data is None:
            vision_data = MCPServerTools.call_vision_tool(video_path)
            cache["vision"] = vision_data
        return transcript, vision_data
    
    def ChatStream(self, request, context):
        raw_query = request.user_query.strip()
        query = _normalize_query(raw_query)
        video_path = request.video_path
        
        if not video_path or not os.path.exists(video_path):
            yield schema_pb2.ChatResponse(
                type=schema_pb2.ChatResponse.TEXT_CHUNK,
                content="❌ **Missing File Context**: Please supply or browse for a valid `.mp4` file path first."
            )
            return

        workspace = os.path.join(os.path.dirname(__file__), "outputs")
        self._append_history(video_path, "user", raw_query)

        # --- Human-in-the-Loop Ambiguity Guard ---
        if not request.is_clarification_response:
            if _is_open_ended_request(query):
                yield schema_pb2.ChatResponse(
                    type=schema_pb2.ChatResponse.CLARIFICATION_REQUIRED,
                    content="Your request is open-ended. Did you mean transcription, visual analysis, PowerPoint generation, or PDF summarization?",
                    clarification_options=[
                        "Transcribe Video Audio",
                        "Extract Object and Graph Visuals",
                        "Create PowerPoint with Key Points",
                        "Summarize Discussion and Generate PDF",
                        "Can you provide more details?",
                    ],
                )
                return

            intent, low_confidence, ranked = self._resolve_intent(query)
            if low_confidence:
                clarification_options = _build_clarification_options(ranked)
                yield schema_pb2.ChatResponse(
                    type=schema_pb2.ChatResponse.CLARIFICATION_REQUIRED,
                    content=f"I found multiple possible actions. Did you mean {clarification_options[0]} or {clarification_options[1]}?",
                    clarification_options=clarification_options,
                )
                return
        else:
            intent = None

        # Handle explicit choice from a previous clarification routing loop
        if request.is_clarification_response:
            selected = _normalize_query(request.selected_option)
            if "transcribe" in selected or "audio" in selected:
                routed_intent = "transcribe"
            elif "object" in selected or "graph" in selected or "visual" in selected:
                routed_intent = "vision"
            elif "powerpoint" in selected or "ppt" in selected or "key points" in selected:
                routed_intent = "ppt"
            elif "pdf" in selected or "summarize discussion" in selected:
                routed_intent = "pdf"
            elif "more details" in selected:
                routed_intent = "clarify"
            else:
                routed_intent = query
        else:
            routed_intent = intent or query

        # --- Sub-Agent Routing Execution ---
        if routed_intent == "transcribe" or "transcribe" in routed_intent or "audio" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Transcription Agent initializing audio processing via MCP Whisper tool...*\n\n")
            transcript, _ = self._get_cached_or_compute(video_path)
            if _is_no_speech_transcript(transcript):
                msg = "### Transcription Summary:\nNo human speech detected in the provided video audio."
            else:
                msg = f"### Transcription Summary:\n{transcript}"
            self._append_history(video_path, "assistant", msg)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=msg)

        elif routed_intent == "vision" or "object" in routed_intent or "graph" in routed_intent or "visual" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Vision Agent sampling frame layouts via MCP OpenCV tool...*\n\n")
            _, vision_data = self._get_cached_or_compute(video_path)
            if vision_data.get("graphs_detected"):
                graph_msg = "Graph-like visuals were detected."
            elif vision_data.get("flags_detected"):
                graph_msg = "No graph detected, but other visual cues were found."
            else:
                graph_msg = "No graph-like visuals detected."
            ocr_lines = vision_data.get("ocr_text") or []
            ocr_msg = "None"
            if ocr_lines:
                ocr_msg = "; ".join(ocr_lines)
            res_md = (
                f"### Vision Report:\n"
                f"* **Scene Content**: {vision_data['description']}\n"
                f"* **Identified Metrics**: {', '.join(vision_data['objects'])}\n"
                f"* **Graph State**: {graph_msg}\n"
                f"* **Extracted Text (OCR)**: {ocr_msg}"
            )
            self._append_history(video_path, "assistant", res_md)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=res_md)

        elif routed_intent == "pdf" or "pdf" in routed_intent or "summary report" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Generation Agent writing data stream to PDF layout template...*\n\n")
            t, vision_data = self._get_cached_or_compute(video_path)
            v = vision_data["description"]
            discussion_summary = self._build_discussion_summary(video_path)
            file_path = MCPServerTools.call_pdf_generation_tool(
                t,
                v,
                workspace,
                discussion_summary=discussion_summary,
                source_name=os.path.basename(video_path),
            )
            msg = (
                "### PDF Generation Complete!\n"
                "Vision Agent capability included: object recognition, captioning, and text/graph extraction."
            )
            self._append_history(video_path, "assistant", msg)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.REPORT_GENERATED, content=msg, file_url=os.path.abspath(file_path))

        elif routed_intent == "ppt" or "powerpoint" in routed_intent or "ppt" in routed_intent:
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content="🤖 *Generation Agent packing slide presentations via python-pptx...*\n\n")
            t, vision_data = self._get_cached_or_compute(video_path)
            v = vision_data["description"]
            discussion_summary = self._build_discussion_summary(video_path)
            file_path = MCPServerTools.call_ppt_generation_tool(
                t,
                v,
                workspace,
                discussion_summary=discussion_summary,
                source_name=os.path.basename(video_path),
            )
            msg = (
                "### PowerPoint Slides Created with key points from the current analysis context!\n"
                "Vision Agent capability included: object recognition, captioning, and text/graph extraction."
            )
            self._append_history(video_path, "assistant", msg)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.REPORT_GENERATED, content=msg, file_url=os.path.abspath(file_path))

        elif routed_intent == "clarify":
            help_msg = "Can you provide more details about what you want me to do? For example: transcribe audio, extract visual objects/graphs, create PowerPoint key points, or generate a PDF summary."
            self._append_history(video_path, "assistant", help_msg)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=help_msg)

        else:
            help_msg = "I couldn't confidently route that action. Try: *Transcribe Video Audio*, *Extract Object and Graph Visuals*, *Create PowerPoint with Key Points*, or *Summarize Discussion and Generate PDF*."
            self._append_history(video_path, "assistant", help_msg)
            yield schema_pb2.ChatResponse(type=schema_pb2.ChatResponse.TEXT_CHUNK, content=help_msg)

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