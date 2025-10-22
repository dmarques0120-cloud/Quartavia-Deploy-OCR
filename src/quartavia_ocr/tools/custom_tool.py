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
    """Schema para a PDFExtractTool."""
    file_path: str = Field(..., description="Caminho para o arquivo PDF a ser processado")


class PDFExtractTool(BaseTool):
    name: str = "Leitor de PDF"
    description: str = "Extrai todo o conteúdo de texto de um arquivo PDF sem qualquer processamento ou estruturação"
    args_schema: Type[BaseModel] = PDFExtractInput

    def _download_from_url(self, url: str) -> str | None:
        """Baixa um arquivo de uma URL e retorna o caminho do arquivo temporário."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            # Cria um arquivo temporário com extensão .pdf
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        tmp_file.write(chunk)
                return tmp_file.name
        except Exception as e:
            return None

    def _extract_from_path(self, file_path: str) -> str:
        """Internal helper that opens a file path and extracts text using pdfplumber."""
        if not isinstance(file_path, str):
            return "Erro: 'file_path' deve ser uma string com o caminho do arquivo ou URL."

        # Verifica se é uma URL
        parsed_url = urlparse(file_path)
        if parsed_url.scheme in ['http', 'https']:
            # Se for URL, baixa para arquivo temporário
            temp_path = self._download_from_url(file_path)
            if not temp_path:
                return f"Erro: não foi possível baixar o arquivo da URL: {file_path}"
            file_path = temp_path
        elif not os.path.exists(file_path):
            return f"Erro: arquivo não encontrado: {file_path}"

        try:
            full_text = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text.append(text)

            # Remove o arquivo temporário se foi baixado de uma URL
            if parsed_url.scheme in ['http', 'https'] and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except:
                    pass  # Ignora erros ao tentar deletar o arquivo temporário

            return "\n\n".join(full_text)
        except Exception as e:
            # Tenta limpar o arquivo temporário em caso de erro também
            if parsed_url.scheme in ['http', 'https'] and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except:
                    pass
            return f"Erro ao processar o arquivo: {str(e)}"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        """
        Executado de forma síncrona. Aceita as seguintes formas de entrada:
         - PDFExtractInput (instância Pydantic)
         - dict ou kwargs com chave 'file_path'
         - string com o caminho como primeiro argumento
        """
        file_path: str | None = None

        # 1) Pydantic, uma string ou um dict
        if args:
            first = args[0]
            # instância do modelo
            if isinstance(first, PDFExtractInput):
                file_path = first.file_path
            # string direta
            elif isinstance(first, str):
                file_path = first
            # dict com file_path
            elif isinstance(first, dict) and "file_path" in first:
                file_path = first["file_path"]

        # 2) kwargs
        if not file_path and "file_path" in kwargs:
            file_path = kwargs.get("file_path")

        if not file_path:
            return "Erro: parâmetro 'file_path' não informado."

        return self._extract_from_path(file_path)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Versão assíncrona que delega para _run sem bloquear o event loop."""
        return await asyncio.to_thread(self._run, *args, **kwargs)