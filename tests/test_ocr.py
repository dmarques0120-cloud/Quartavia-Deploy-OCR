import sys
import os

# diretório raiz do projeto
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.quartavia_ocr.tools.custom_tool import PDFExtractTool

def test_pdf_extract():
    # instância da ferramenta
    pdf_tool = PDFExtractTool()
    
    pdf_path = "C:/Users/dmarq/Downloads/Extrato-21-09-2025-a-21-10-2025-PDF.pdf"
    
    # extrai o texto
    result = pdf_tool._run(pdf_path)
    
    print("=== Texto Extraído do PDF ===")
    print(result)
    print("============================")

if __name__ == "__main__":
    test_pdf_extract()