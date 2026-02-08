import fitz  # PyMuPDF
from typing import List
import logging

logger = logging.getLogger(__name__)


class PDFParser:
    """PDFファイルからテキストを抽出するクラス"""
    
    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        """
        PDFバイトデータからテキストを抽出
        
        Args:
            pdf_bytes: PDFファイルのバイナリデータ
            
        Returns:
            抽出されたテキスト
        """
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text_parts = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
            
            doc.close()
            return "\n\n".join(text_parts)
        
        except Exception as e:
            logger.error(f"Failed to extract PDF text: {e}")
            return "[PDF解析エラー]"
    
    @staticmethod
    def extract_text_from_multiple(pdf_files: List[tuple[str, bytes]]) -> dict[str, str]:
        """
        複数のPDFファイルからテキストを抽出
        
        Args:
            pdf_files: [(filename, pdf_bytes), ...] のリスト
            
        Returns:
            {filename: extracted_text} の辞書
        """
        results = {}
        for filename, pdf_bytes in pdf_files:
            if filename.lower().endswith('.pdf'):
                text = PDFParser.extract_text(pdf_bytes)
                results[filename] = text
        return results
