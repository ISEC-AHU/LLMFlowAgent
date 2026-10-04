import dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from generation.chains.utils import MODEL

dotenv.load_dotenv()


WRITE_DAG_PROMPT = """You're a scientific workflow expert, and your role involves:
1. Analyzing the original workflow description and the associated API list, but you don't need to return them to me.
2. Choosing the suitable API from the following API list for each task execution and assessing the interdependencies among task executions, but you don't need to return them to me. Use the original workflow description as the authoritative source for task coverage, execution order, parallel activities, and synchronization requirements.
3. Ultimately, presenting the workflow task list and their dependencies in the following json markdown format:
```json {{
  "task_links": [
    {{
      "source": "source api name",
      "target": "target api name"
    }}
  ],
  "task_nodes": [
    {{
      "task": "api name",
      "arguments": [
        "input argument or <node-i>"
      ]
    }}
  ]
}}```

Don't output anything for step 1 and 2, only the answer in step 3. Return only one JSON markdown block. Do not output any explanation, note, or extra text. Let's work this out in a step by step way to be sure we have the right answer.

original workflow description: {text}
api list: {api_list}
additional coordinator requirements: {generation_feedback}
Answer:
"""

write_dag_chain = (
    ChatPromptTemplate.from_template(WRITE_DAG_PROMPT) | MODEL | StrOutputParser()
)
