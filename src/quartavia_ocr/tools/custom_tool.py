import pdfplumber
import asyncio
import os
import tempfile
import requests
import re  # Para expressões regulares na filtragem
from urllib.parse import urlparse
from typing import Type, Any, ClassVar
from crewai.tools import BaseTool
from dotenv import load_dotenv
import traceback # Para logs de erro mais detalhados

# --- IMPORTS PARA A FERRAMENTA DE OCR ---
try:
    from openai import OpenAI
    import base64
    import fitz  # PyMuPDF para converter PDF em imagens
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("AVISO: Falta 'openai' ou 'PyMuPDF'. Execute: pip install openai PyMuPDF")
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
    'moeda de origem', 'cotação us$', 'aplicativo bradesco', 'situação do extrato',
    # Novos filtros para remover informações irrelevantes
    'pagamento via', 'qr code', 'boleto', 'escaneie', 'autenticação mecânica',
    'ficha de compensação', 'força para pagar', 'parcelamento', 'parcela',
    'próximo agendamento', 'simulação', 'super app', 'fatura atual',
    'descritivo detalhado', 'pontos em', 'pontos a receber', 'débito automático',
    'termos e condições', 'loop', 'elegíveis para pontuação', 'creditados',
    'clientes inter', 'pagamento integral', 'dias úteis', 'olá', 'sua fatura chegou',
    'caso o pagamento', 'prazo para reconhecimento', 'liberação do limite',
    'faça o pagamento', 'limite será liberado', 'precisa de uma força',
    'confira as opções', 'disponíveis pra você', 'caso opte pelo',
    'importante saber', 'você pode acessar', 'essa é a soma', 'suas despesas',
    'durante esse mês', 'mês passado', 'consulte os termos', 'após realizar',
    'rotativo'
]
KEEP_KEYWORDS_GLOBAL = [
    'saldo do dia', 'pix enviado', 'pix recebido', 'deposito', 'saque', 'ted',
    'doc', 'transferencia', 'resgate', 'aplicacao', 'investimento', 'cartao',
    'compra', 'posto', 'drogaria', 'supermercado', 'loja', 'pagamento on line',
    'debito automatico', 'tarifa', 'anuidade', 'iof', 'saldo anterior',
    'saldo atual', 'extrato', 'conta corrente', 'poupanca'
]
def clean_and_filter_lines(text_lines: list[str]) -> str:
    """Filtra linhas para manter apenas transações e informações financeiras relevantes"""
    filtered_data = []
    
    for line in text_lines:
        line_strip = line.strip()
        if not line_strip or len(line_strip) < 3:
            continue
            
        line_lower = line_strip.lower()
        
        # Verifica se é uma linha de transação ou informação relevante
        is_transaction = (
            # Linhas com datas e valores (padrão de transação)
            bool(re.search(r'\d{2}.*de.*\d{4}.*r\$', line_lower)) or
            # Linhas com valores monetários significativos
            bool(re.search(r'r\$\s*\d+[.,]\d{2}', line_lower)) or
            # Linhas com operações financeiras específicas
            any(op in line_lower for op in ['pix enviado', 'pix recebido', 'deposito', 'saque', 'ted', 'doc', 'transferencia', 'resgate', 'aplicacao']) or
            # Linhas com estabelecimentos comerciais
            bool(re.search(r'(posto|drogaria|supermercado|loja|shopping|mercado)', line_lower)) or
            # Linhas com saldo
            'saldo' in line_lower
        )
        
        # Verifica se deve ser ignorada (palavras-chave irrelevantes)
        should_ignore = any(keyword in line_lower for keyword in IGNORE_KEYWORDS_GLOBAL)
        
        # Força manter se for palavra-chave importante
        force_keep = any(keyword in line_lower for keyword in KEEP_KEYWORDS_GLOBAL)
        
        # Ignora linhas com apenas códigos de barras ou hashes
        if re.match(r'^[\d\s\.\*]+$', line_strip) and len(line_strip) > 20:
            continue
            
        # Ignora linhas com apenas asteriscos e números (número de cartão mascarado sozinho)
        if re.match(r'^\d{4}\*+\d{4}$', line_strip):
            continue
            
        # Adiciona à lista se for transação relevante e não deve ser ignorada
        if (is_transaction or force_keep) and not should_ignore:
            filtered_data.append(line_strip)
        elif force_keep:  # Força manter mesmo se houver palavras para ignorar
            filtered_data.append(line_strip)
            
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
            # Primeira tentativa: extração com layout preservado
            text = pdf_page.extract_text(layout=True, use_text_flow=True, x_tolerance=1, y_tolerance=3)
            print(f"DEBUG: Primeira tentativa (layout=True): {text[:100] if text else 'None'}...")
            
            # Segunda tentativa: extração simples
            if not text or text.strip() == "":
                text = pdf_page.extract_text()
                print(f"DEBUG: Segunda tentativa (simples): {text[:100] if text else 'None'}...")
            
            # Terceira tentativa: extração com diferentes tolerâncias
            if not text or text.strip() == "":
                text = pdf_page.extract_text(x_tolerance=3, y_tolerance=3)
                print(f"DEBUG: Terceira tentativa (tolerância maior): {text[:100] if text else 'None'}...")
            
            # Quarta tentativa: extração de caracteres individuais
            if not text or text.strip() == "":
                chars = pdf_page.chars
                if chars:
                    text = " ".join([c.get('text', '') for c in chars if c.get('text', '').strip()])
                    print(f"DEBUG: Quarta tentativa (chars): {text[:100] if text else 'None'}...")
            
            if not text or text.strip() == "":
                print(f"DEBUG: TODAS as tentativas de extração falharam.")
                return None
                
            print(f"DEBUG: Texto extraído com sucesso: {len(text)} caracteres")
            return text.split('\n')
            
        except Exception as e: 
            print(f"DEBUG: pdfplumber falhou ao extrair texto: {e}")
            return None
    def _download_from_url(self, url: str) -> str | None:
        try:
            response = requests.get(url, stream=True); response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: tmp_file.write(chunk)
                return tmp_file.name
        except Exception: return None
    def _extract_from_path(self, file_path: str) -> str:
        print(f"DEBUG: _extract_from_path iniciado com: {file_path}")
        if not isinstance(file_path, str): 
            print("DEBUG: file_path não é string")
            return "Erro: 'file_path' deve ser uma string válida."
        
        parsed_url = urlparse(file_path)
        is_url = parsed_url.scheme in ['http', 'https']
        temp_path_to_clean = None
        
        if is_url:
            print(f"DEBUG: NativeTool baixando URL: {file_path}")
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path: 
                print("DEBUG: Falha no download")
                return f"Erro: Falha ao baixar PDF da URL."
            temp_path_to_clean = local_pdf_path
            print(f"DEBUG: PDF baixado para: {local_pdf_path}")
        elif os.path.exists(file_path): 
            print(f"DEBUG: NativeTool usando path local: {file_path}")
            local_pdf_path = file_path
        else: 
            print(f"DEBUG: Arquivo não encontrado: {file_path}")
            return f"Erro: arquivo não encontrado: {file_path}"
        all_filtered_data = []
        has_relevant_content = False
        pdf_seems_empty_or_image = True 
        total_text_chars = 0
        all_raw_text = []  # Para armazenar texto bruto caso o filtro seja muito restritivo
        
        print(f"DEBUG: Iniciando processamento do PDF: {local_pdf_path}")
        
        try:
            print(f"DEBUG: Tentando abrir PDF com pdfplumber...")
            with pdfplumber.open(local_pdf_path) as pdf:
                print(f"DEBUG: PDF aberto com sucesso! Número de páginas: {len(pdf.pages)}")
                print(f"DEBUG: Tentando extrair texto nativo com pdfplumber de {len(pdf.pages)} páginas...")
                
                for i, page in enumerate(pdf.pages):
                    extracted_lines = self._extract_text(page) 
                    
                    if extracted_lines is None: 
                        continue 
                    
                    # Se conseguiu extrair algo, marca que o PDF não é uma imagem
                    pdf_seems_empty_or_image = False 
                    
                    raw_page_text = "\n".join(extracted_lines).strip()
                    total_text_chars += len(raw_page_text)
                    
                    if raw_page_text:
                        all_raw_text.append(f"\n--- PÁGINA {i+1} (BRUTO) ---\n{raw_page_text}")
                        
                        filtered_text = self._clean_and_filter(extracted_lines)
                        
                        if filtered_text:
                            all_filtered_data.append(f"\n--- DADOS (PÁGINA {i+1}) ---\n")
                            all_filtered_data.append("Método: Texto Nativo\n")
                            all_filtered_data.append(filtered_text)
                            has_relevant_content = True
                        
            # Análise dos resultados
            if not pdf_seems_empty_or_image:
                if has_relevant_content: 
                    final_result = "\n".join(all_filtered_data)
                    return final_result
                else: 
                    # Retorna pelo menos o texto bruto se o filtro removeu tudo
                    if total_text_chars > 50:  # Se há texto suficiente, retorna sem filtro
                        return "\n--- DADOS (SEM FILTRO) ---\n" + "\n".join(all_raw_text)
                    else:
                        return "Texto nativo extraído, mas nenhum dado relevante encontrado após o filtro." 
            else: 
                return "Erro: O PDF parece ser uma imagem ou está vazio/ilegível. Tente a ferramenta de OCR."
                
        except Exception as e: 
            print(f"ERRO: pdfplumber falhou ao processar PDF: {e}")
            return "Erro: O PDF parece ser uma imagem ou está corrompido. Tente a ferramenta de OCR."
        finally:
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try: os.unlink(temp_path_to_clean)
                except: pass
    def _run(self, file_path: str) -> str:
        if not file_path or not isinstance(file_path, str): 
            return "Erro: 'file_path' deve ser uma string válida."
        return self._extract_from_path(file_path)
    async def _arun(self, file_path: str) -> str: return await asyncio.to_thread(self._run, file_path=file_path)


# ##################################################################
# FERRAMENTA 2: EXTRATOR OCR (PLANO B) - Debug Aprimorado no __init__
# ##################################################################

class PDFToOCRTool(BaseTool):
    name: str = "Extrator de PDF (OCR)"
    description: str = "LENTO. Usa a API OpenAI GPT-4.1-nano para OCR de PDFs através de análise de imagem."
    
    client: Any = None 
    api_key: str = None
    model_name: str = None

    IGNORE_KEYWORDS: ClassVar[list[str]] = IGNORE_KEYWORDS_GLOBAL
    KEEP_KEYWORDS: ClassVar[list[str]] = KEEP_KEYWORDS_GLOBAL

    def __init__(self):
        super().__init__()
        print("DEBUG: Iniciando __init__ da PDFToOCRTool (OpenAI)...")
        if not OCR_AVAILABLE: 
            print("ERRO FATAL: PDFToOCRTool __init__ falhou: Falta 'openai' ou 'PyMuPDF'."); self.client = None; return
            
        # --- DEBUG APRIMORADO ---
        try:
            self.api_key = os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                print("ERRO CRÍTICO no __init__: OPENAI_API_KEY não encontrada nas variáveis de ambiente.")
                self.client = None
                return

            self.model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4.1-nano")
            print(f"DEBUG no __init__: Usando modelo: {self.model_name}")

            # Loga a chave parcialmente mascarada
            masked_key = self.api_key[:5] + "****" + self.api_key[-4:] if len(self.api_key) > 9 else "****"
            print(f"DEBUG no __init__: OPENAI_API_KEY encontrada: '{masked_key}'")

            # Tenta inicializar o cliente e loga sucesso ou falha específica
            print("DEBUG no __init__: Tentando inicializar cliente OpenAI...")
            self.client = OpenAI(api_key=self.api_key)
            print("DEBUG no __init__: Cliente OpenAI inicializado com SUCESSO.")

        except Exception as e:
            # Loga o erro EXATO que ocorreu durante a inicialização
            print(f"ERRO CRÍTICO no __init__: Falha ao inicializar o cliente OpenAI. Verifique a API Key ou conectividade. Erro: {type(e).__name__} - {e}")
            print(f"DEBUG Traceback __init__:\n{traceback.format_exc()}")
            self.client = None
        # --- FIM DO DEBUG APRIMORADO ---
            
    def _clean_and_filter(self, text_lines: list[str]) -> str:
        return clean_and_filter_lines(text_lines)
    
    def _encode_image(self, image_bytes: bytes) -> str:
        """Codifica bytes de imagem em base64"""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def _pdf_to_images_base64(self, pdf_path: str) -> list[str]:
        """Converte PDF para lista de imagens em base64"""
        try:
            pdf_document = fitz.open(pdf_path)
            images_b64 = []
            
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                # Renderiza a página como imagem (PNG)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom para melhor qualidade
                img_data = pix.tobytes("png")
                b64_string = self._encode_image(img_data)
                images_b64.append(b64_string)
                
            pdf_document.close()
            return images_b64
            
        except Exception as e:
            print(f"ERRO ao converter PDF para imagens: {e}")
            print(f"DEBUG Traceback PDF->Imagem:\n{traceback.format_exc()}")
            return []
        
    def _run(self, file_path: str) -> str:
        """Executa a extração OCR via API OpenAI GPT-4.1-nano, aceitando URLs e arquivos locais."""
        print("DEBUG: Iniciando _run da PDFToOCRTool (OpenAI)...")
        if not OCR_AVAILABLE: 
            return "Erro: Falta 'openai' ou 'PyMuPDF'." 
        
        # Checa se o cliente foi inicializado com sucesso no __init__
        if not self.client: 
            print("ERRO no _run: Cliente OpenAI não está inicializado. Verifique logs do __init__.")
            return "Erro: Cliente OpenAI não inicializado. Verifique a configuração da API Key ou logs de inicialização."
            
        if not file_path or not isinstance(file_path, str): 
            return "Erro: 'file_path' deve ser uma string válida."

        parsed_url = urlparse(file_path)
        is_url = parsed_url.scheme in ['http', 'https']
        temp_path_to_clean = None
        
        # Determina o caminho local do PDF
        if is_url:
            print(f"DEBUG: OCR Tool baixando URL: {file_path}")
            local_pdf_path = self._download_from_url(file_path)
            if not local_pdf_path: 
                return "Erro: Falha ao baixar PDF da URL."
            temp_path_to_clean = local_pdf_path
        elif os.path.exists(file_path):
            print(f"DEBUG: OCR Tool usando path local: {file_path}")
            local_pdf_path = file_path
        else:
            return f"Erro: arquivo não encontrado: {file_path}"

        try:
            print(f"DEBUG: Convertendo PDF para imagens base64...")
            images_b64 = self._pdf_to_images_base64(local_pdf_path)
            
            if not images_b64:
                return "Erro: Falha ao converter PDF em imagens."
            
            print(f"DEBUG: {len(images_b64)} páginas convertidas. Processando com OpenAI...")
            
            all_extracted_text = []
            
            for i, img_b64 in enumerate(images_b64):
                try:
                    print(f"DEBUG: Processando página {i+1}/{len(images_b64)} com GPT-4.1-nano...")
                    
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text", 
                                        "text": "Analise esta imagem de um documento financeiro (extrato bancário, fatura de cartão, etc.) e extraia TODOS os dados textuais visíveis. Retorne apenas o texto extraído, sem comentários ou formatação adicional. Mantenha a estrutura original o máximo possível."
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{img_b64}"
                                        }
                                    }
                                ]
                            }
                        ],
                        max_tokens=4000,
                        temperature=0.1
                    )
                    
                    page_text = response.choices[0].message.content.strip()
                    if page_text:
                        all_extracted_text.append(f"\n--- PÁGINA {i+1} ---\n{page_text}")
                        print(f"DEBUG: Página {i+1} processada com sucesso.")
                    else:
                        print(f"DEBUG: Página {i+1} retornou texto vazio.")
                        
                except Exception as page_error:
                    print(f"ERRO ao processar página {i+1}: {page_error}")
                    continue
            
            if not all_extracted_text:
                return "Erro: Nenhum texto foi extraído de nenhuma página."
            
            # Junta todo o texto extraído
            raw_text = "\n".join(all_extracted_text)
            print(f"DEBUG: Texto bruto extraído: '{raw_text[:200]}...'")
            
            # Aplica filtro
            filtered_text = self._clean_and_filter(raw_text.split('\n'))
            print("DEBUG: Processamento OCR OpenAI concluído.")
            
            output = f"\n--- DADOS OCR (OpenAI GPT-4.1-nano) ---\n"
            if filtered_text: 
                output += filtered_text
            else: 
                output += "(Nenhum dado relevante encontrado após o filtro)"
                print("DEBUG: Texto filtrado/vazio.")
            
            return output
            
        except Exception as api_error: 
            error_message = f"Erro API OpenAI: {type(api_error).__name__} - {api_error}. Verifique API Key/Permissões/Conectividade."
            print(error_message)
            print(f"ERRO DETALHADO OCR:\n{traceback.format_exc()}") 
            return error_message
            
        finally:
            # Limpa arquivo temporário se foi baixado
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try: 
                    os.unlink(temp_path_to_clean)
                except: 
                    pass
    
    def _download_from_url(self, url: str) -> str | None:
        """Baixa PDF de uma URL e retorna o caminho do arquivo temporário"""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk: 
                        tmp_file.write(chunk)
                return tmp_file.name
        except Exception as e:
            print(f"ERRO ao baixar URL: {e}")
            return None
        
    async def _arun(self, file_path: str) -> str:
        """Versão assíncrona para OpenAI OCR."""
        return await asyncio.to_thread(self._run, file_path=file_path)