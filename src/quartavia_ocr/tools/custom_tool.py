import pdfplumber
import asyncio
import os
import tempfile
import requests
from urllib.parse import urlparse
from typing import Type, Any, ClassVar
from crewai.tools import BaseTool
from dotenv import load_dotenv
import traceback # Para logs de erro mais detalhados

# --- IMPORTS PARA A FERRAMENTA DE OCR ---
try:
    from mistralai import Mistral
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("AVISO: Falta 'mistralai'. Execute: pip install mistralai")
# -------------------------------------

load_dotenv()

# Constantes e função de filtro (inalteradas)
IGNORE_KEYWORDS_GLOBAL = [
    'total', 'data', 'movimentação', 'beneficiário', 'valor', 'limite de crédito', 
    'pagamento mínimo', 'encargos', 'fale com a gente', 'ouvidoria', 'sac', 
    'vencimento', 'saldo por transação', 'agência / cedente', 'n° documento', 
    'resumo da fatura', 'despesas do mês', 'pontos loop', 'fatura anterior', 
    'créditos e estornos', 'total da fatura', 'juros', 'iof', 'taxas', 
    'lançamentos nacionais', 'compras à vista', 'outros valores', 'histórico',
    'moeda de origem', 'cotação us$', 'aplicativo bradesco', 'situação do extrato'
]
KEEP_KEYWORDS_GLOBAL = ['saldo do dia']
def clean_and_filter_lines(text_lines: list[str]) -> str:
    # (Função inalterada)
    filtered_data = []
    for line in text_lines:
        line_strip = line.strip()
        if not line_strip or (len(line_strip) < 3 and not line_strip.lower() in ['r$', 'rs', 'usd', 'us$', 'uss']): continue
        line_lower = line_strip.lower(); is_junk = any(keyword in line_lower for keyword in IGNORE_KEYWORDS_GLOBAL)
        is_context_header = any(keyword in line_lower for keyword in KEEP_KEYWORDS_GLOBAL)
        if is_junk and not is_context_header: continue
        has_numbers_or_currency = (any(char.isdigit() for char in line_strip) or line_strip.lower() in ['r$', 'rs', 'usd', 'us$', 'uss'])
        has_letters = any(c.isalpha() for c in line_strip)
        if is_context_header or has_numbers_or_currency or (has_letters and not is_junk):
             noise = ['rs', 'uss', 'usd', 'us$']
             if line_lower not in noise or has_numbers_or_currency: filtered_data.append(line_strip)
    return "\n".join(filtered_data)

# ##################################################################
# FERRAMENTA 1: EXTRATOR DE TEXTO NATIVO (RÁPIDO)
# ##################################################################
class NativePDFExtractorTool(BaseTool): 
    # (Esta classe permanece INALTERADA)
    name: str = "Extrator de Texto Nativo PDF"; description: str = "RÁPIDO. Extrai texto de um PDF (NATIVO)..."
    IGNORE_KEYWORDS: ClassVar[list[str]] = IGNORE_KEYWORDS_GLOBAL; KEEP_KEYWORDS: ClassVar[list[str]] = KEEP_KEYWORDS_GLOBAL
    def _clean_and_filter(self, text_lines: list[str]) -> str: return clean_and_filter_lines(text_lines)
    def _extract_text(self, pdf_page: pdfplumber.page.Page) -> list[str] | None:
        try:
            text = pdf_page.extract_text(layout=True, use_text_flow=True, x_tolerance=1, y_tolerance=3) 
            if text is None: text = pdf_page.extract_text()
            if text is None: print(f"DEBUG: pdfplumber.extract_text retornou None."); return None 
            return text.split('\n')
        except Exception as e: print(f"DEBUG: pdfplumber falhou ao extrair texto: {e}"); return None
    def _download_from_url(self, url: str) -> str | None:
        try:
            response = requests.get(url, stream=True); response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception: return None
    def _extract_from_path(self, file_path: str) -> str:
        if not isinstance(file_path, str): return "Erro: 'file_path' ..."
        parsed_url = urlparse(file_path); is_url = parsed_url.scheme in ['http', 'https']
        temp_path_to_clean = None
        if is_url:
            print(f"DEBUG: NativeTool baixando URL: {file_path}"); local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path: return f"Erro: download..."; temp_path_to_clean = local_pdf_path
        elif os.path.exists(file_path): print(f"DEBUG: NativeTool usando path local: {file_path}"); local_pdf_path = file_path
        else: return f"Erro: arquivo não encontrado: {file_path}"
        all_filtered_data = []; has_relevant_content = False; pdf_seems_empty_or_image = True 
        try:
            with pdfplumber.open(local_pdf_path) as pdf:
                print("DEBUG: Tentando extrair texto nativo com pdfplumber...")
                for i, page in enumerate(pdf.pages):
                    extracted_lines = self._extract_text(page) 
                    if extracted_lines is None: print(f"DEBUG: Falha ao extrair texto nativo da página {i+1}."); continue 
                    pdf_seems_empty_or_image = False 
                    raw_page_text = "\n".join(extracted_lines).strip()
                    if raw_page_text:
                        filtered_text = self._clean_and_filter(extracted_lines)
                        if filtered_text:
                           all_filtered_data.append(f"\n--- DADOS (PÁGINA {i+1}) ---\n"); all_filtered_data.append("Método: Texto Nativo\n"); all_filtered_data.append(filtered_text); has_relevant_content = True 
            if not pdf_seems_empty_or_image:
                if has_relevant_content: print("DEBUG: pdfplumber extraiu conteúdo relevante."); return "\n".join(all_filtered_data)
                else: print("DEBUG: pdfplumber extraiu texto, mas filtro removeu tudo."); return "Texto nativo extraído, mas nenhum dado relevante encontrado após o filtro." 
            else: print("DEBUG: pdfplumber não extraiu NENHUM texto. Sugerindo OCR."); return "Erro: O PDF parece ser uma imagem ou está vazio/ilegível. Tente a ferramenta de OCR."
        except Exception as e: print(f"DEBUG: pdfplumber falhou ao abrir/processar: {e}. Sugerindo OCR."); return "Erro: O PDF parece ser uma imagem ou está corrompido. Tente a ferramenta de OCR."
        finally:
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try: os.unlink(temp_path_to_clean)
                except: pass
    def _run(self, file_path: str) -> str:
        if not file_path or not isinstance(file_path, str): return f"Erro: 'file_path' ..."; return self._extract_from_path(file_path)
    async def _arun(self, file_path: str) -> str: return await asyncio.to_thread(self._run, file_path=file_path)


# ##################################################################
# FERRAMENTA 2: EXTRATOR OCR (PLANO B) - Debug Aprimorado no __init__
# ##################################################################

class PDFToOCRTool(BaseTool):
    name: str = "Extrator de PDF (OCR)"
    description: str = "LENTO. Usa a API Mistral OCR..." # (inalterado)
    
    client: Any = None 
    api_key: str = None

    IGNORE_KEYWORDS: ClassVar[list[str]] = IGNORE_KEYWORDS_GLOBAL
    KEEP_KEYWORDS: ClassVar[list[str]] = KEEP_KEYWORDS_GLOBAL

    def __init__(self):
        super().__init__()
        print("DEBUG: Iniciando __init__ da PDFToOCRTool...") # Log de início
        if not OCR_AVAILABLE: 
            print("ERRO FATAL: PDFToOCRTool __init__ falhou: Falta 'mistralai'."); self.client = None; return
            
        # --- DEBUG APRIMORADO ---
        try:
            self.api_key = os.getenv("MISTRAL_API_KEY")
            if not self.api_key:
                print("ERRO CRÍTICO no __init__: MISTRAL_API_KEY não encontrada nas variáveis de ambiente.")
                self.client = None
                return # Sai se a chave não for encontrada

            # Loga a chave parcialmente mascarada
            masked_key = self.api_key[:5] + "****" + self.api_key[-4:] if len(self.api_key) > 9 else "****"
            print(f"DEBUG no __init__: MISTRAL_API_KEY encontrada: '{masked_key}'")

            # Tenta inicializar o cliente e loga sucesso ou falha específica
            print("DEBUG no __init__: Tentando inicializar cliente Mistral...")
            self.client = Mistral(api_key=self.api_key)
            print("DEBUG no __init__: Cliente Mistral inicializado com SUCESSO.")

        except Exception as e:
            # Loga o erro EXATO que ocorreu durante a inicialização
            print(f"ERRO CRÍTICO no __init__: Falha ao inicializar o cliente Mistral. Verifique a API Key ou conectividade. Erro: {type(e).__name__} - {e}")
            print(f"DEBUG Traceback __init__:\n{traceback.format_exc()}") # Log completo do erro
            self.client = None # Garante que client é None se a inicialização falhar
        # --- FIM DO DEBUG APRIMORADO ---
            
    def _clean_and_filter(self, text_lines: list[str]) -> str:
        # (Inalterado)
        return clean_and_filter_lines(text_lines)
        
    def _run(self, file_path: str) -> str:
        """Executa a extração OCR via API Mistral, aceitando apenas URLs."""
        print("DEBUG: Iniciando _run da PDFToOCRTool...") # Log de início do run
        if not OCR_AVAILABLE: return "Erro: Falta 'mistralai'." 
        
        # Checa se o cliente foi inicializado com sucesso no __init__
        if not self.client: 
            print("ERRO no _run: Cliente Mistral não está inicializado. Verifique logs do __init__.")
            return "Erro: Cliente Mistral não inicializado. Verifique a configuração da API Key ou logs de inicialização."
            
        if not file_path or not isinstance(file_path, str): return f"Erro: 'file_path'..."

        parsed_url = urlparse(file_path); is_url = parsed_url.scheme in ['http', 'https']
        if not is_url: print(f"DEBUG: OCR Tool só aceita URLs."); return "Erro: OCR só funciona com URLs."

        try:
            print(f"DEBUG: Preparando para chamar Mistral OCR SDK para URL: {file_path}...")
            ocr_response = self.client.ocr.process(
                model="mistral-ocr-latest", 
                document={"type": "document_url", "document_url": file_path }
            )
            # (Resto da lógica de processamento da resposta e filtro - inalterado)
            # ...
            print("--- DEBUG RESPOSTA MISTRAL OCR ---")
            print(f"Tipo da Resposta: {type(ocr_response)}")
            try: print(f"Conteúdo (vars): {vars(ocr_response)}") 
            except TypeError: print(f"Conteúdo (raw): {ocr_response}")
            print("--- FIM DEBUG RESPOSTA ---")
            extracted_text = ""; 
            if hasattr(ocr_response, 'pages') and isinstance(ocr_response.pages, list) and ocr_response.pages:
                all_markdowns = [getattr(page, "markdown", "") for page in ocr_response.pages]
                extracted_text = "\n\n".join(md for md in all_markdowns if md)
                if not extracted_text: print(f"AVISO: 'markdown' vazio em pages. Resp: {ocr_response}")
            else: print(f"AVISO: 'pages' não encontrado/vazio. Resp: {ocr_response}")
            print(f"DEBUG: Texto bruto API: '{extracted_text[:150]}...'")
            filtered_text = self._clean_and_filter(extracted_text.split('\n'))
            print("DEBUG: Processamento OCR API concluído.")
            output = f"\n--- DADOS OCR (API Mistral) ---\n"
            if filtered_text: output += filtered_text
            else: output += "(Nenhum dado relevante encontrado após o filtro)"; print("DEBUG: Texto API filtrado/vazio.")
            return output
        except Exception as api_error: 
            error_message = f"Erro API Mistral (SDK): {type(api_error).__name__} - {api_error}. Verifique API Key/Permissões/URL."
            if hasattr(api_error, 'response') and api_error.response is not None: error_message += f" Status: {api_error.response.status_code}. Detalhe: {api_error.response.text}"
            print(error_message); print(f"ERRO DETALHADO OCR:\n{traceback.format_exc()}") 
            return error_message
        
    async def _arun(self, file_path: str) -> str:
        """Versão assíncrona."""
        return await asyncio.to_thread(self._run, file_path=file_path)