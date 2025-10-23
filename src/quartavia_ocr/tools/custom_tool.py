import pdfplumber
import asyncio
import os
import tempfile
import requests
from urllib.parse import urlparse
from typing import Type, Any, ClassVar
from crewai.tools import BaseTool

# --- IMPORTS PARA A FERRAMENTA DE OCR ---
try:
    import pytesseract 
    from pdf2image import convert_from_path
    import platform # Usado para checar o OS
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
# -------------------------------------


# ##################################################################
# FERRAMENTA 1: EXTRATOR DE TEXTO NATIVO (RÁPIDO)
# ##################################################################

class NativePDFExtractorTool(BaseTool): 
    name: str = "Extrator de Texto Nativo PDF"
    description: str = (
        "RÁPIDO. Extrai *todo* o texto de um PDF (NATIVO) usando extract_text(). "
        "Não usa extração de tabelas. Aplica heurísticas para pré-filtrar o lixo. "
        "Não funciona em PDFs scaneados/imagens."
    )
    
    IGNORE_KEYWORDS: ClassVar[list[str]] = [
        'total', 'data', 'movimentação', 'beneficiário', 'valor', 
        'limite de crédito', 'pagamento mínimo', 'encargos', 'fale com a gente',
        'ouvidoria', 'sac', 'vencimento', 'saldo por transação', 'agência / cedente',
        'n° documento', 'resumo da fatura', 'despesas do mês', 'pontos loop',
        'fatura anterior', 'créditos e estornos', 'total da fatura', 'juros', 'iof',
        'taxas', 'lançamentos nacionais', 'compras à vista', 'outros valores'
    ]
    KEEP_KEYWORDS: ClassVar[list[str]] = ['saldo do dia']

    def _clean_and_filter(self, text_lines: list[str]) -> str:
        # (Este método está correto)
        filtered_data = []
        for line in text_lines:
            if not line or not line.strip(): continue
            line_lower = line.lower()
            is_context_header = any(keyword in line_lower for keyword in self.KEEP_KEYWORDS)
            is_junk = any(keyword in line_lower for keyword in self.IGNORE_KEYWORDS)
            has_numbers = any(char.isdigit() for char in line_lower) or 'r$' in line_lower
            if is_context_header or (not is_junk and has_numbers):
                filtered_data.append(line)
        return "\n".join(filtered_data)

    def _extract_text(self, pdf_page: pdfplumber.page.Page) -> list[str]:
        # (Este método está correto)
        try:
            text = pdf_page.extract_text(layout=True, use_text_flow=True)
            if not text: return []
            return text.split('\n')
        except Exception:
            return []
    
    def _download_from_url(self, url: str) -> str | None:
        # (Este método está correto)
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception:
            return None
    
    def _extract_from_path(self, file_path: str) -> str:
        if not isinstance(file_path, str):
            return "Erro: 'file_path' deve ser uma string com o caminho do arquivo ou URL."

        parsed_url = urlparse(file_path)
        # --- CORREÇÃO 1 (Bug do 'httpsA') ---
        is_url = parsed_url.scheme in ['http', 'https']
        # --- FIM DA CORREÇÃO 1 ---
        temp_path_to_clean = None

        if is_url:
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path:
                return f"Erro: não foi possível baixar o arquivo da URL: {file_path}"
            temp_path_to_clean = local_pdf_path
        elif os.path.exists(file_path):
            local_pdf_path = file_path
        else:
            return f"Erro: arquivo não encontrado: {file_path}"
        
        all_filtered_data = []
        try:
            with pdfplumber.open(local_pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    all_filtered_data.append(f"\n--- DADOS (PÁGINA {i+1}) ---\n")
                    extracted_lines = self._extract_text(page)
                    extraction_method = "Texto Nativo"
                    if not extracted_lines:
                        all_filtered_data.append("Erro: O PDF parece ser uma imagem ou está vazio. Tente a ferramenta de OCR.")
                        continue 
                    filtered_text = self._clean_and_filter(extracted_lines)
                    if filtered_text:
                        all_filtered_data.append(f"Método: {extraction_method}\n")
                        all_filtered_data.append(filtered_text)
                    else:
                        all_filtered_data.append(f"Método: {extraction_method} (Sem dados transacionais encontrados)")
            
            return "\n".join(all_filtered_data)
        except Exception as e:
            if "cannot open" in str(e).lower() or "damaged" in str(e).lower():
                 return "Erro: O PDF parece ser uma imagem ou está corrompido. Tente a ferramenta de OCR."
            return f"Erro ao processar PDF nativo: {str(e)}"
        finally:
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try: os.unlink(temp_path_to_clean)
                except: pass

    def _run(self, file_path: str) -> str:
        if not file_path or not isinstance(file_path, str):
            return f"Erro: 'file_path' (string) é obrigatório. Recebido: {file_path}"
        return self._extract_from_path(file_path)
    
    async def _arun(self, file_path: str) -> str:
        return await asyncio.to_thread(self._run, file_path=file_path)


# ##################################################################
# FERRAMENTA 2: EXTRATOR OCR (PLANO B)
# ##################################################################

class PDFToOCRTool(BaseTool):
    name: str = "Extrator de PDF (OCR)"
    description: str = (
        "LENTO. Usa OCR para extrair texto de PDFs scaneados/de imagem. "
        "Use esta ferramenta *apenas* se o 'Extrator de PDF Nativo' falhar."
    )
    
    IGNORE_KEYWORDS: ClassVar[list[str]] = [
        'total', 'data', 'movimentação', 'beneficiário', 'valor', 
        'limite de crédito', 'pagamento mínimo', 'encargos', 'fale com a gente',
        'ouvidoria', 'sac', 'vencimento', 'saldo por transação', 'agência / cedente',
        'n° documento', 'resumo da fatura', 'despesas do mês', 'pontos loop',
        'fatura anterior', 'créditos e estornos', 'total da fatura', 'juros', 'iof',
        'taxas', 'lançamentos nacionais', 'compras à vista', 'outros valores'
    ]
    KEEP_KEYWORDS: ClassVar[list[str]] = ['saldo do dia']

    def __init__(self):
        super().__init__()
        if not OCR_AVAILABLE:
            print("ERRO FATAL: PDFToOCRTool não pode ser inicializada. Falta 'pytesseract' ou 'pdf2image'.")
            return
        
        # --- CORREÇÃO 2: Apontar o Pytesseract para a instalação do Tesseract ---
        # Isso resolve o erro 'tesseract is not installed' no Windows
        if platform.system() == "Windows":
            # Caminho padrão da instalação do Tesseract no Windows. 
            # Verifique se o seu está neste local.
            tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            if os.path.exists(tesseract_cmd):
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            else:
                print("AVISO: Tesseract não encontrado no caminho padrão 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'")
                print("Por favor, adicione o Tesseract ao seu PATH ou ajuste o caminho no custom_tool.py")
        # --- FIM DA CORREÇÃO 2 ---
    
    def _clean_and_filter(self, text_lines: list[str]) -> str:
        # (Este método está correto)
        filtered_data = []
        for line in text_lines:
            if not line or not line.strip(): continue
            line_lower = line.lower()
            is_context_header = any(keyword in line_lower for keyword in self.KEEP_KEYWORDS)
            is_junk = any(keyword in line_lower for keyword in self.IGNORE_KEYWORDS)
            has_numbers = any(char.isdigit() for char in line_lower) or 'r$' in line_lower
            if is_context_header or (not is_junk and has_numbers):
                filtered_data.append(line)
        return "\n".join(filtered_data)
        
    def _download_from_url(self, url: str) -> str | None:
        # (Este método está correto)
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception:
            return None

    def _run(self, file_path: str) -> str:
        """Executa a extração OCR no PDF."""
        if not OCR_AVAILABLE:
            return "Erro: Ferramentas de OCR (pytesseract, pdf2image) não estão instaladas."
             
        if not file_path or not isinstance(file_path, str):
            return f"Erro: 'file_path' (string) é obrigatório. Recebido: {file_path}"

        parsed_url = urlparse(file_path)
        # --- CORREÇÃO 1 (Bug do 'httpsA') ---
        is_url = parsed_url.scheme in ['http', 'https']
        # --- FIM DA CORREÇÃO 1 ---
        temp_pdf_path_to_clean = None

        if is_url:
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path:
                return f"Erro: não foi possível baixar o arquivo da URL: {file_path}"
            temp_pdf_path_to_clean = local_pdf_path
        elif os.path.exists(file_path):
            local_pdf_path = file_path
        else:
            return f"Erro: arquivo não encontrado: {file_path}"
        
        all_ocr_text = []
        try:
            images = convert_from_path(local_pdf_path)
            
            for i, img in enumerate(images):
                all_ocr_text.append(f"\n--- DADOS OCR (PÁGINA {i+1}) ---\n")
                
                # Chama o pytesseract direto com lang='por'
                text = pytesseract.image_to_string(img, lang='por')

                filtered_text = self._clean_and_filter(text.split('\n'))
                all_ocr_text.append(filtered_text)
            
            return "\n".join(all_ocr_text)

        except Exception as e:
            return (f"Erro durante o processo de OCR: {str(e)}. "
                    f"Verifique se Tesseract e Poppler estão instalados e no PATH. "
                    f"Certifique-se de que o pacote 'tesseract-ocr-por' (Linux) ou "
                    f"o idioma 'Portuguese' (Windows) está instalado.")
        
        finally:
            if temp_pdf_path_to_clean and os.path.exists(temp_pdf_path_to_clean):
                try: os.unlink(temp_pdf_path_to_clean)
                except: pass

    async def _arun(self, file_path: str) -> str:
        """Versão assíncrona."""
        return await asyncio.to_thread(self._run, file_path=file_path)