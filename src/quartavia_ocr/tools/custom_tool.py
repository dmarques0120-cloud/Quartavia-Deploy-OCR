from typing import Type, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import asyncio
import os
import tempfile
import requests
from urllib.parse import urlparse

# --- NÃO PRECISAMOS MAIS DESTA CLASSE ---
# class PDFExtractInput(BaseModel):
#     """Schema para a PDFTableExtractorTool."""
#     file_path: str = Field(..., description="Caminho para o arquivo PDF a ser processado")


class PDFTableExtractorTool(BaseTool): 
    
    name: str = "Extrator de Tabelas PDF"
    description: str = (
        "Extrai *apenas* o conteúdo de *todas as tabelas* de um arquivo PDF. "
        "Use esta ferramenta passando *apenas* a string do file_path (URL)."
    )
    
    # --- MUDANÇA 1: REMOVER O ARGS_SCHEMA ---
    # O schema será inferido automaticamente do método _run abaixo.
    # args_schema: Type[BaseModel] = PDFExtractInput

    def _download_from_url(self, url: str) -> str | None:
        """Baixa um arquivo de uma URL e retorna o caminho do arquivo temporário."""
        # (Seu código original - sem alterações)
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        tmp_file.write(chunk)
                return tmp_file.name
        except Exception as e:
            return None

    def _extract_from_path(self, file_path: str) -> str:
        """
        Helper interno que abre um caminho, extrai dados de tabelas E 
        pré-filtra o lixo usando heurísticas.
        """
        # (Seu código _extract_from_path da resposta anterior está perfeito - NENHUMA MUDANÇA AQUI)
        if not isinstance(file_path, str):
            return "Erro: 'file_path' deve ser uma string com o caminho do arquivo ou URL."

        parsed_url = urlparse(file_path)
        is_url = parsed_url.scheme in ['http', 'https']
        temp_path_to_clean = None

        if is_url:
            temp_path = self._download_from_url(file_path)
            if not temp_path:
                return f"Erro: não foi possível baixar o arquivo da URL: {file_path}"
            file_path = temp_path
            temp_path_to_clean = temp_path 
        elif not os.path.exists(file_path):
            return f"Erro: arquivo não encontrado: {file_path}"

        try:
            all_filtered_data = []
            IGNORE_KEYWORDS = [
                'total', 'saldo do dia', 'data', 'movimentação', 'beneficiário', 'valor', 
                'limite de crédito', 'pagamento mínimo', 'encargos', 
                'fale com a gente', 'ouvidoria', 'sac', 'vencimento', 
                'saldo por transação', 'agência / cedente', 'n° documento',
                'resumo da fatura', 'despesas do mês', 'pontos loop'
            ]
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    if not tables: continue
                    page_header_added = False
                    for table in tables:
                        for row in table:
                            clean_row_items = [
                                str(cell).replace('\n', ' ').strip() 
                                for cell in row 
                                if cell is not None and str(cell).strip()
                            ]
                            if not clean_row_items: continue
                            line_text = " | ".join(clean_row_items).lower()
                            is_date_header = 'saldo do dia' in line_text
                            is_junk = any(keyword in line_text for keyword in IGNORE_KEYWORDS)
                            has_numbers = any(char.isdigit() for char in line_text) or 'r$' in line_text
                            
                            if is_date_header or (not is_junk and has_numbers):
                                if not page_header_added:
                                    all_filtered_data.append(f"\n--- DADOS FILTRADOS (PÁGINA {i+1}) ---\n")
                                    page_header_added = True
                                all_filtered_data.append(" | ".join(clean_row_items))
            
            if not any(item for item in all_filtered_data if not item.startswith('---')):
                return "Erro: Nenhum dado de transação filtrado foi encontrado no PDF."
            return "\n".join(all_filtered_data)
        except Exception as e:
            return f"Erro ao processar o arquivo: {str(e)}"
        finally:
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try:
                    os.unlink(temp_path_to_clean)
                except:
                    pass

    # --- MUDANÇA 2: SIMPLIFICAR _run E _arun ---
    
    def _run(self, file_path: str) -> str:
        """
        Executado de forma síncrona.
        O schema é inferido automaticamente a partir daqui: 
        espera um único argumento chamado 'file_path' do tipo 'str'.
        """
        if not file_path or not isinstance(file_path, str):
            return f"Erro: 'file_path' (string) é obrigatório. Recebido: {file_path}"
        
        # Chama a lógica principal
        return self._extract_from_path(file_path)

    async def _arun(self, file_path: str) -> str:
        """Versão assíncrona."""
        # Delega para o _run síncrono em uma thread separada
        return await asyncio.to_thread(self._run, file_path=file_path)