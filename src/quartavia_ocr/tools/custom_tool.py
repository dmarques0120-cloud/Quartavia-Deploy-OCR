from typing import Type, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import asyncio
import os
import tempfile
import requests
from urllib.parse import urlparse


class PDFExtractInput(BaseModel):
    """Schema para a PDFTableExtractorTool."""
    file_path: str = Field(..., description="Caminho para o arquivo PDF a ser processado")


class PDFTableExtractorTool(BaseTool): 
    
    name: str = "Extrator de Tabelas PDF"
    description: str = (
        "Extrai *apenas* o conteúdo de *todas as tabelas* de um arquivo PDF. "
        "Retorna os dados tabulares como uma única string de texto formatada, "
        "ignorando todo o texto que está fora das tabelas."
    )
    args_schema: Type[BaseModel] = PDFExtractInput

    def _download_from_url(self, url: str) -> str | None:
        """Baixa um arquivo de uma URL e retorna o caminho do arquivo temporário."""

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
        Helper interno que abre um caminho de arquivo, extrai *apenas tabelas* e retorna como texto formatado.
        """
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
            all_tables_data = []
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    
                    tables = page.extract_tables()
                    
                    if not tables:
                        continue # Pula páginas sem tabelas

                    all_tables_data.append(f"\n--- DADOS TABULARES (PÁGINA {i+1}) ---\n")
                    
                    for table in tables:
                        for row in table:
                            # Limpa a linha: remove None, converte para string, remove quebras de linha
                            clean_row = [
                                str(cell).replace('\n', ' ') 
                                for cell in row 
                                if cell is not None and str(cell).strip() # Ignora células vazias ou None
                            ]
                            
                            if not clean_row:
                                continue # Ignora linhas totalmente vazias
                                
                            # Junta as células com um separador claro para o LLM
                            line = " | ".join(clean_row)
                            all_tables_data.append(line)
                            
                        all_tables_data.append("\n--- FIM DA TABELA ---\n")

            if not all_tables_data:
                return "Erro: Nenhum dado tabular foi encontrado no PDF."

            # Retorna uma única string gigante, mas contendo *apenas* dados de tabelas
            return "\n".join(all_tables_data)

        except Exception as e:
            return f"Erro ao processar o arquivo: {str(e)}"
        
        finally:
            # Limpa o arquivo temporário se foi baixado
            if temp_path_to_clean and os.path.exists(temp_path_to_clean):
                try:
                    os.unlink(temp_path_to_clean)
                except:
                    pass # Ignora erros ao deletar
        # <<< FIM DA MODIFICAÇÃO PRINCIPAL >>>


    def _run(self, *args: Any, **kwargs: Any) -> str:
        """
        Executado de forma síncrona.
        """
        # (Seu código original - sem alterações)
        file_path: str | None = None

        if args:
            first = args[0]
            if isinstance(first, PDFExtractInput):
                file_path = first.file_path
            elif isinstance(first, str):
                file_path = first
            elif isinstance(first, dict) and "file_path" in first:
                file_path = first["file_path"]

        if not file_path and "file_path" in kwargs:
            file_path = kwargs.get("file_path")

        if not file_path:
            return "Erro: parâmetro 'file_path' não informado."

        return self._extract_from_path(file_path)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Versão assíncrona que delega para _run sem bloquear o event loop."""
        # (Seu código original - sem alterações)
        return await asyncio.to_thread(self._run, *args, **kwargs)