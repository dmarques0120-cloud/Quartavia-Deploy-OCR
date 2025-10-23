import pdfplumber
import asyncio
import os
import tempfile
import requests
from urllib.parse import urlparse
from typing import Type, Any, ClassVar
from crewai.tools import BaseTool
import io
import numpy as np

# --- IMPORTS PARA A FERRAMENTA DE OCR ---
try:
    import easyocr
    import fitz  # Importa PyMuPDF
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("AVISO: Falta 'easyocr' ou 'PyMuPDF'.")
    print("Execute: pip install easyocr PyMuPDF torch torchvision torchaudio")
# -------------------------------------

# Constantes de palavras-chave movidas para fora para serem usadas por ambas as tools
IGNORE_KEYWORDS_GLOBAL = [
    'total', 'data', 'movimentação', 'beneficiário', 'valor', 'limite de crédito', 
    'pagamento mínimo', 'encargos', 'fale com a gente', 'ouvidoria', 'sac', 
    'vencimento', 'saldo por transação', 'agência / cedente', 'n° documento', 
    'resumo da fatura', 'despesas do mês', 'pontos loop', 'fatura anterior', 
    'créditos e estornos', 'total da fatura', 'juros', 'iof', 'taxas', 
    'lançamentos nacionais', 'compras à vista', 'outros valores', 'histórico',
    'moeda de origem', 'cotação us$', 'aplicativo bradesco', 'situação do extrato' # Adicionadas do Bradesco.pdf
]
KEEP_KEYWORDS_GLOBAL = ['saldo do dia'] # Mantém cabeçalhos importantes


def clean_and_filter_lines(text_lines: list[str]) -> str:
    """Função helper refatorada para filtrar linhas."""
    filtered_data = []
    for line in text_lines:
        line_strip = line.strip()
        if not line_strip or len(line_strip) < 2 : continue # Pula vazias ou muito curtas

        line_lower = line_strip.lower()

        # Verifica se é explicitamente lixo (e NÃO é um header importante)
        is_junk = any(keyword in line_lower for keyword in IGNORE_KEYWORDS_GLOBAL)
        is_context_header = any(keyword in line_lower for keyword in KEEP_KEYWORDS_GLOBAL)
        
        if is_junk and not is_context_header:
            # print(f"DEBUG Filter: Discarding junk: '{line_strip}'")
            continue

        # Verifica se tem números ou símbolos de moeda comuns
        has_numbers_or_currency = (
            any(char.isdigit() for char in line_strip) or 
            'r$' in line_lower or 
            'usd' in line_lower or
            'us$' in line_lower
        )

        # Verifica se parece um nome/descrição (contém letras)
        has_letters = any(c.isalpha() for c in line_strip)

        # --- LÓGICA DE MANTER REFINADA ---
        # Mantém se:
        # 1. É um cabeçalho importante (saldo do dia)
        # 2. OU Tem números/moeda (provável data, valor, cotação)
        # 3. OU Tem letras E NÃO é apenas lixo curto (provável nome/descrição)
        if is_context_header or has_numbers_or_currency or (has_letters and len(line_strip) > 3):
            # Adiciona uma checagem final para ruídos comuns que passam
             noise = ['rs', 'uss', 'usd', 'us$']
             if line_lower not in noise or has_numbers_or_currency: # Mantem R$ 5,89 mas remove 'rs' sozinho
                filtered_data.append(line_strip)
                # print(f"DEBUG Filter: Keeping: '{line_strip}'")
            # else:
                # print(f"DEBUG Filter: Discarding noise: '{line_strip}'")

        # else:
            # print(f"DEBUG Filter: Discarding other: '{line_strip}'")
            
    return "\n".join(filtered_data)


# ##################################################################
# FERRAMENTA 1: EXTRATOR DE TEXTO NATIVO (RÁPIDO)
# ##################################################################

class NativePDFExtractorTool(BaseTool): 
    name: str = "Extrator de Texto Nativo PDF"
    description: str = (
        "RÁPIDO. Extrai *todo* o texto de um PDF (NATIVO) usando extract_text(). "
        "Aplica heurísticas para pré-filtrar o lixo. "
        "Não funciona em PDFs scaneados/imagens."
    )
    
    # Usa as constantes globais
    IGNORE_KEYWORDS: ClassVar[list[str]] = IGNORE_KEYWORDS_GLOBAL
    KEEP_KEYWORDS: ClassVar[list[str]] = KEEP_KEYWORDS_GLOBAL

    def _clean_and_filter(self, text_lines: list[str]) -> str:
        # Delega para a função helper
        return clean_and_filter_lines(text_lines)

    def _extract_text(self, pdf_page: pdfplumber.page.Page) -> list[str]:
        try:
            # Tentar com layout=True pode ajudar na estrutura
            text = pdf_page.extract_text(layout=True, use_text_flow=True, x_tolerance=1, y_tolerance=3) 
            if not text: 
                 text = pdf_page.extract_text() # Fallback
            if not text: return []
            return text.split('\n')
        except Exception as e:
            print(f"DEBUG: pdfplumber falhou: {e}")
            return []
    
    def _download_from_url(self, url: str) -> str | None:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception: return None
    
    def _extract_from_path(self, file_path: str) -> str:
        # (Lógica desta função permanece a mesma da versão anterior)
        if not isinstance(file_path, str): return "Erro: 'file_path' ..."
        parsed_url = urlparse(file_path)
        is_url = parsed_url.scheme in ['http', 'https']
        temp_path_to_clean = None
        if is_url:
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path: return f"Erro: download..."
            temp_path_to_clean = local_pdf_path
        elif os.path.exists(file_path): local_pdf_path = file_path
        else: return f"Erro: arquivo não encontrado..."
        all_filtered_data = []
        try:
            with pdfplumber.open(local_pdf_path) as pdf:
                print("DEBUG: Tentando extrair texto nativo com pdfplumber...")
                has_content = False
                for i, page in enumerate(pdf.pages):
                    page_data = []
                    extracted_lines = self._extract_text(page)
                    if extracted_lines:
                        filtered_text = self._clean_and_filter(extracted_lines)
                        if filtered_text:
                           page_data.append(f"\n--- DADOS (PÁGINA {i+1}) ---\n")
                           page_data.append("Método: Texto Nativo\n")
                           page_data.append(filtered_text)
                           has_content = True 
                    if page_data:
                       all_filtered_data.extend(page_data)
            if has_content:
                print("DEBUG: pdfplumber extraiu conteúdo. Retornando.")
                return "\n".join(all_filtered_data)
            else:
                print("DEBUG: pdfplumber não encontrou texto relevante. Sugerindo OCR.")
                return "Erro: O PDF parece ser uma imagem ou está vazio. Tente a ferramenta de OCR."
        except Exception as e:
            print(f"DEBUG: pdfplumber falhou ao abrir/processar: {e}. Sugerindo OCR.")
            return "Erro: O PDF parece ser uma imagem ou está corrompido. Tente a ferramenta de OCR."
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
# FERRAMENTA 2: EXTRATOR OCR (PLANO B) - Versão EasyOCR Ajustada
# ##################################################################

class PDFToOCRTool(BaseTool):
    name: str = "Extrator de PDF (OCR)"
    description: str = (
        "LENTO. Usa EasyOCR para ler PDFs scaneados/de imagem. "
        "Use esta ferramenta *apenas* se o 'Extrator de Texto Nativo PDF' falhar."
    )
    
    reader: Any = None 

    # Usa as constantes globais
    IGNORE_KEYWORDS: ClassVar[list[str]] = IGNORE_KEYWORDS_GLOBAL
    KEEP_KEYWORDS: ClassVar[list[str]] = KEEP_KEYWORDS_GLOBAL

    def __init__(self):
        super().__init__()
        if not OCR_AVAILABLE:
            print("ERRO FATAL: PDFToOCRTool não pode ser inicializada. Falta 'easyocr' ou 'PyMuPDF'.")
            self.reader = None
            return
        try:
            print("DEBUG: Inicializando EasyOCR Reader para Português...")
            # gpu=True tentará usar a GPU se disponível, caso contrário fallback para CPU
            self.reader = easyocr.Reader(['pt'], gpu=True) 
            print("DEBUG: EasyOCR Reader inicializado.")
        except Exception as e:
            print(f"ERRO CRÍTICO: Não foi possível inicializar o EasyOCR Reader. Erro: {e}")
            self.reader = None
    
    def _clean_and_filter(self, text_lines: list[str]) -> str:
         # Delega para a função helper
        return clean_and_filter_lines(text_lines)
        
    def _download_from_url(self, url: str) -> str | None:
        # (Este método está correto)
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception: return None

    def _run(self, file_path: str) -> str:
        """Executa a extração OCR no PDF usando EasyOCR."""
        if not OCR_AVAILABLE: return "Erro: Ferramentas..."
        if not self.reader: return "Erro: EasyOCR Reader..."
        if not file_path or not isinstance(file_path, str): return f"Erro: 'file_path'..."

        parsed_url = urlparse(file_path)
        is_url = parsed_url.scheme in ['http', 'https']
        temp_pdf_path_to_clean = None

        if is_url:
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path: return f"Erro: download..."
            temp_pdf_path_to_clean = local_pdf_path
        elif os.path.exists(file_path): local_pdf_path = file_path
        else: return f"Erro: arquivo não encontrado..."
        
        all_ocr_text = []
        try:
            print(f"DEBUG: Abrindo PDF com PyMuPDF: {local_pdf_path}")
            doc = fitz.open(local_pdf_path) 
            
            for i, page in enumerate(doc):
                print(f"DEBUG: Processando OCR na página {i+1}...")
                all_ocr_text.append(f"\n--- DADOS OCR (PÁGINA {i+1}) ---\n")
                
                pix = page.get_pixmap(dpi=300) 
                img_bytes = pix.tobytes("png") 
                
                # --- MUDANÇA: Tentar com paragraph=True ---
                # Isso pode ajudar a agrupar texto relacionado
                print("DEBUG: Chamando EasyOCR readtext com paragraph=True...")
                results = self.reader.readtext(img_bytes, detail=0, paragraph=True) 
                
                # Se paragraph=True retornar vazio ou pouco, tentar sem
                if not results or len(" ".join(results)) < 20: # Heurística simples
                    print("DEBUG: paragraph=True deu pouco resultado, tentando com paragraph=False...")
                    results = self.reader.readtext(img_bytes, detail=0, paragraph=False)
                
                # Junta as linhas/parágrafos detectados pelo EasyOCR
                page_text = "\n".join(results)
                print(f"DEBUG: Resultado bruto EasyOCR (Página {i+1}, após fallback se necessário): '{page_text[:150]}...'")

                filtered_text = self._clean_and_filter(page_text.split('\n'))
                all_ocr_text.append(filtered_text)
            
            doc.close()
            print("DEBUG: Processamento OCR concluído.")
            return "\n".join(all_ocr_text)

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"ERRO DETALHADO OCR: {tb_str}") 
            return (f"Erro durante o processo de OCR com EasyOCR: {str(e)}. Verifique deps.")
        
        finally:
            if temp_pdf_path_to_clean and os.path.exists(temp_pdf_path_to_clean):
                try: os.unlink(temp_pdf_path_to_clean)
                except: pass

    async def _arun(self, file_path: str) -> str:
        """Versão assíncrona."""
        return await asyncio.to_thread(self._run, file_path=file_path)