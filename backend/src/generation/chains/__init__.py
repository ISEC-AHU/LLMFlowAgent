"""
LangServe-compatible LangChain chain definitions.

These chains are used only by FastAPI LangServe routes (``add_routes``)
to preserve compatibility with frontend ``RemoteRunnable`` calls.
Core DAG generation is provided by ``generation.generator.dag_generator``
and ``workflow_dag_service``.
"""

from .utils import MODEL, escape_braces, InputChat
from .create_game import create_game_chain_with_history, CREATE_GAME_PROMPT
from .write_dag import write_dag_chain, WRITE_DAG_PROMPT
from .write_xml import write_xml_chain, WRITE_XML_PROMPT
from .custom_api import custom_api_chain
