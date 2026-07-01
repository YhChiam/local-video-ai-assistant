import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from pptx import Presentation
from ai_engine import LocalAIEngine

ai_engine = LocalAIEngine()

class MCPServerTools:
    """
    Self-developed Model Context Protocol capability mapping layer.
    Keeps application tooling local with no external cloud callbacks.
    """
    @staticmethod
    def call_transcription_tool(video_path: str) -> str:
        return ai_engine.run_whisper_stt(video_path)

    @staticmethod
    def call_vision_tool(video_path: str) -> dict:
        return ai_engine.run_vision_analysis(video_path)

    @staticmethod
    def call_pdf_generation_tool(transcript: str, vision_text: str, dest_dir: str) -> str:
        os.makedirs(dest_dir, exist_ok=True)
        pdf_path = os.path.join(dest_dir, "Video_Analysis_Report.pdf")
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("<b>Video Intelligence Summary Report</b>", styles['Title']),
            Spacer(1, 12),
            Paragraph("<b>Transcription Data:</b>", styles['Heading2']),
            Paragraph(transcript, styles['Normal']),
            Spacer(1, 12),
            Paragraph("<b>Vision Analysis Data:</b>", styles['Heading2']),
            Paragraph(vision_text, styles['Normal'])
        ]
        doc.build(story)
        return pdf_path

    @staticmethod
    def call_ppt_generation_tool(transcript: str, vision_text: str, dest_dir: str) -> str:
        os.makedirs(dest_dir, exist_ok=True)
        ppt_path = os.path.join(dest_dir, "Video_Presentation.pptx")
        prs = Presentation()
        
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Video Analytical Breakdown"
        slide.placeholders[1].text = f"Speech Analytics:\n{transcript}\n\nVisual Entities:\n{vision_text}"
        
        prs.save(ppt_path)
        return ppt_path