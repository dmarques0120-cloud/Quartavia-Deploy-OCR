# Em seu projeto CrewAI
import base64
import io
from typing import Type, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pdfplumber
import asyncio

class PDFContentInput(BaseModel):
    """Schema para a PDFContentTool."""
    file_content_base64: str = Field(..., description="Conteúdo do arquivo PDF codificado em Base64.")

class PDFContentTool(BaseTool):
    name: str = "Leitor de Conteúdo de PDF"
    description: str = "Extrai todo o conteúdo de texto de um arquivo PDF fornecido como uma string Base64."
    args_schema: Type[BaseModel] = PDFContentInput

    def _run(self, file_content_base64: str) -> str:
        """Executado de forma síncrona, aceitando o conteúdo do arquivo em Base64."""
        if not isinstance(file_content_base64, str):
            return "Erro: 'file_content_base64' deve ser uma string."

        try:
            # Decodificar a string Base64 para bytes
            decoded_bytes = base64.b64decode(file_content_base64)
           
            # Usar io.BytesIO para tratar os bytes como um arquivo em memória
            pdf_file_in_memory = io.BytesIO(decoded_bytes)
           
            full_text = []
            # Abrir o PDF diretamente da memória
            with pdfplumber.open(pdf_file_in_memory) as pdf:
                if not pdf.pages:
                    return "Erro: O PDF parece estar vazio ou corrompido."
               
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text.append(text)

            if not full_text:
                return "Nenhum texto extraível encontrado no PDF."

            return "\n\n".join(full_text)
        except base64.binascii.Error:
            return "Erro: Falha ao decodificar a string Base64. Verifique se o conteúdo está formatado corretamente."
        except Exception as e:
            # pdfplumber pode lançar exceções específicas que você pode querer tratar
            return f"Erro ao processar o conteúdo do PDF: {str(e)}"

    # Você não precisa mais do _arun se _run for rápido o suficiente ou se a lógica for a mesma
    # Se a extração for muito lenta, manter a delegação para uma thread é uma boa ideia.
    async def _arun(self, file_content_base64: str) -> str:
        """Versão assíncrona que delega para _run."""
        # Esta implementação é simples, mas para I/O real, você poderia usar uma biblioteca async
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, file_content_base64)