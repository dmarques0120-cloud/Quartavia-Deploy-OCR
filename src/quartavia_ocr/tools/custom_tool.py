from typing import Type, Any, Optional
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import base64
import io
import requests
import os

class PDFExtractInput(BaseModel):
    """Aceita file_content (base64) OU file_path (url ou caminho no servidor)."""
    file_content: Optional[str] = Field(None, description="Conteúdo do arquivo PDF em base64")
    filename: Optional[str] = Field(None, description="Nome do arquivo PDF")
    content_type: Optional[str] = Field(None, description="Tipo do conteúdo do arquivo")
    file_path: Optional[str] = Field(None, description="Caminho/URL para o PDF (opcional)")

class PDFExtractTool(BaseTool):
    name: str = "Leitor de PDF"
    description: str = "Extrai texto de um PDF (aceita base64 ou file_path)"
    args_schema: Type[BaseModel] = PDFExtractInput

    def _extract_from_bytes(self, pdf_bytes: bytes) -> str:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n\n".join(pages)
        except Exception as e:
            return f"Erro ao processar o arquivo PDF: {str(e)}"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        # recebe tanto a Pydantic model quanto dict/kwargs
        payload = None
        if args:
            first = args[0]
            if isinstance(first, PDFExtractInput):
                payload = first.dict()
            elif isinstance(first, dict):
                payload = first
        if not payload:
            payload = kwargs

        file_content = payload.get("file_content")
        file_path = payload.get("file_path")
        filename = payload.get("filename")
        content_type = payload.get("content_type")

        # 1) Preferir file_content (base64)
        if file_content:
            try:
                pdf_bytes = base64.b64decode(file_content)
            except Exception as e:
                return f"Erro ao decodificar base64: {e}"
            return self._extract_from_bytes(pdf_bytes)

        # 2) Se file_path presente, tentar obter bytes (suporta URL e caminho local)
        if file_path:
            # URL
            if str(file_path).lower().startswith(("http://", "https://")):
                try:
                    r = requests.get(file_path, timeout=15)
                    r.raise_for_status()
                    return self._extract_from_bytes(r.content)
                except Exception as e:
                    return f"Erro ao baixar PDF a partir da URL '{file_path}': {e}"
            # caminho local
            if os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        return self._extract_from_bytes(f.read())
                except Exception as e:
                    return f"Erro ao ler arquivo local '{file_path}': {e}"
            return f"file_path informado, mas não é URL e o caminho não existe no servidor: {file_path}"

        # 3) Nenhum input válido
        return "Erro: nenhum conteúdo de PDF fornecido. Envie 'file_content' (base64) ou 'file_path' (URL acessível)."

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return await __import__("asyncio").to_thread(self._run, *args, **kwargs)