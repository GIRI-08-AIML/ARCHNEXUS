"""Document text extraction for .pdf, .docx, .md, and .txt files."""
import io
from pathlib import Path
from pypdf import PdfReader
from docx import Document


class DocumentExtractError(ValueError):
    pass


MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB limit


def extract_document_text(filename: str, content: bytes) -> str:
    """Extract clean text from uploaded .pdf, .docx, .md, or .txt files.
    
    Validates file extension, checks size, and detects empty or scanned PDFs.
    """
    if len(content) == 0:
        raise DocumentExtractError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE:
        raise DocumentExtractError("File size exceeds 10 MB limit.")

    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception as exc:
                raise DocumentExtractError("Could not decode text file.") from exc
        clean = text.strip()
        if not clean:
            raise DocumentExtractError("The uploaded text document has no content.")
        return clean

    elif ext == ".docx":
        try:
            doc = Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n\n".join(paragraphs).strip()
            if not text:
                raise DocumentExtractError("The Word document (.docx) does not contain readable text.")
            return text
        except Exception as exc:
            if isinstance(exc, DocumentExtractError):
                raise
            raise DocumentExtractError(f"Could not read Word document: {exc}") from exc

    elif ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) == 0:
                raise DocumentExtractError("PDF has no pages.")
            extracted_pages = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text.strip())

            full_text = "\n\n".join(extracted_pages).strip()
            if not full_text or len(full_text) < 20:
                raise DocumentExtractError(
                    "This PDF appears to be scanned or contains no extractable text. Please upload a searchable PDF or Markdown file."
                )
            return full_text
        except Exception as exc:
            if isinstance(exc, DocumentExtractError):
                raise
            raise DocumentExtractError(f"Could not read PDF: {exc}") from exc

    else:
        raise DocumentExtractError(
            f"Unsupported file format '{ext}'. Supported formats: .pdf, .docx, .md, .txt"
        )
