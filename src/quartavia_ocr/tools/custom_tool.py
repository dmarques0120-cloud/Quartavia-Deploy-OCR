from typing import Type, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import base64
import io

class PDFExtractInput(BaseModel):
    """Schema para a PDFExtractTool."""
    file_content: str = Field(..., description="Conteúdo do arquivo PDF em base64")
    filename: str = Field(..., description="Nome do arquivo PDF")
    content_type: str = Field(..., description="Tipo do conteúdo do arquivo")

class PDFExtractTool(BaseTool):
    name: str = "Leitor de PDF"
    description: str = "Extrai todo o conteúdo de texto de um arquivo PDF sem qualquer processamento ou estruturação"
    args_schema: Type[BaseModel] = PDFExtractInput

    def _extract_from_content(self, file_content: str) -> str:
        """Extrai texto do conteúdo do PDF em base64."""
        try:
            # Decodifica o conteúdo base64
            pdf_bytes = base64.b64decode(file_content)
            
            # Usa BytesIO para criar um objeto arquivo em memória
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text.append(text)
                
                return "\n\n".join(full_text)
        except Exception as e:
            return f"Erro ao processar o arquivo PDF: {str(e)}"

    def _run(self, file_content: str, filename: str, content_type: str) -> str:
        """Executa a extração do texto do PDF."""
        if not file_content:
            return "Erro: conteúdo do arquivo não fornecido."
        
        return self._extract_from_content(file_content)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Versão assíncrona que delega para _run."""
        return self._run(*args, **kwargs)