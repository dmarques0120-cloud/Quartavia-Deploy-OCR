#!/usr/bin/env python
import sys
import warnings
import base64
from datetime import datetime
from quartavia_ocr.crew import QuartaviaOcr

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

def run():
    def process_inputs(inputs):
        # aceita file_content OR file_path
        if inputs is None:
            raise ValueError("Inputs vazios")
        if "file_content" in inputs:
            return inputs
        if "file_path" in inputs:
            return {"file_path": inputs["file_path"]}
        raise ValueError("Envie 'file_content' (base64) ou 'file_path' (URL/caminho acessível).")

    try:
        # quando chamado localmente por CLI
        if __name__ == "__main__":
            file_path = input("Enter the path to the PDF file: ")
            with open(file_path, "rb") as f:
                file_content = base64.b64encode(f.read()).decode("utf-8")
            inputs = {
                "file_content": file_content,
                "filename": file_path.split("\\")[-1],
                "content_type": "application/pdf"
            }

        processed_inputs = process_inputs(inputs)
        QuartaviaOcr().crew().kickoff(inputs=processed_inputs)

    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")

run()