#!/usr/bin/env python
import sys
import warnings
import base64

from datetime import datetime

from quartavia_ocr.crew import QuartaviaOcr

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

file_path = input("Enter the path to the PDF file: ")

def run():
    """
    Run the crew.
    """
    # Quando chamado via API, os inputs já virão no formato correto
    # Esta função apenas passa os inputs adiante
    def process_inputs(inputs):
        # Verifica se recebemos os campos necessários
        required_fields = ['file_content', 'filename', 'content_type']
        for field in required_fields:
            if field not in inputs:
                raise ValueError(f"Missing required field: {field}")
        
        return inputs

    try:
        # Se estivermos rodando via linha de comando, podemos adicionar essa lógica
        if __name__ == "__main__":
            file_path = input("Enter the path to the PDF file: ")
            # Lê o arquivo e converte para base64
            with open(file_path, 'rb') as f:
                file_content = base64.b64encode(f.read()).decode('utf-8')
            
            inputs = {
                'file_content': file_content,
                'filename': file_path.split('/')[-1],
                'content_type': 'application/pdf'
            }
        
        # Processa os inputs (seja da API ou da linha de comando)
        processed_inputs = process_inputs(inputs)

        QuartaviaOcr().crew().kickoff(inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        QuartaviaOcr().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        QuartaviaOcr().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }

    try:
        QuartaviaOcr().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "topic": "",
        "current_year": ""
    }

    try:
        result = QuartaviaOcr().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")

run()