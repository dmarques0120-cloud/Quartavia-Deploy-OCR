from typing import Type, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import asyncio
import base64
import io


class PDFExtractInput(BaseModel):
    """Schema para a PDFExtractTool."""
    pdf_content: str = Field(..., description="Conteúdo do PDF em base64")
    filename: str = Field(..., description="Nome do arquivo PDF")


class PDFExtractTool(BaseTool):
    name: str = "Leitor de PDF"
    description: str = "Extrai todo o conteúdo de texto de um arquivo PDF sem qualquer processamento ou estruturação"
    args_schema: Type[BaseModel] = PDFExtractInput

    def _extract_from_content(self, pdf_content: str) -> str:
        """Internal helper that processes PDF content from base64."""
        try:
            # Decodifica o conteúdo base64 para bytes
            pdf_bytes = base64.b64decode(pdf_content)
            
            # Usa BytesIO para criar um objeto arquivo em memória
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text.append(text)

                return "\n\n".join(full_text)
        except Exception as e:
            return f"Erro ao processar o arquivo: {str(e)}"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        """
        Executado de forma síncrona. Aceita as seguintes formas de entrada:
         - PDFExtractInput (instância Pydantic)
         - dict ou kwargs com chaves 'pdf_content' e 'filename'
        """
        pdf_content: str | None = None

        # 1) Primeiro argumento pode ser uma instância Pydantic ou um dict
        if args:
            first = args[0]
            # instância do modelo
            if isinstance(first, PDFExtractInput):
                pdf_content = first.pdf_content
            # dict com pdf_content
            elif isinstance(first, dict) and "pdf_content" in first:
                pdf_content = first["pdf_content"]

        # 2) kwargs
        if not pdf_content and "pdf_content" in kwargs:
            pdf_content = kwargs.get("pdf_content")

        if not pdf_content:
            return "Erro: parâmetro 'pdf_content' não informado."

        return self._extract_from_content(pdf_content)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Versão assíncrona que delega para _run sem bloquear o event loop."""
        return await asyncio.to_thread(self._run, *args, **kwargs)