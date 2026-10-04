from generation.chains.postgres_history import PostgresChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory

from generation.chains.utils import InputChat, escape_braces
from src.llm_factory.factory import LLMFactory


TASK_DECOMPOSITION_MODEL = LLMFactory.get_langchain_chat_model("task_decomposition")


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    return PostgresChatMessageHistory(
        session_id,
        table_name="chat_message_store",
    )


demonstration = """Human: The Lotka-Volterra workflow solves the classic Lotka-Volterra predator prey dynamics model, which describes the relative populations of a predator and its prey over time using two coupled differential equations: one that describes how predator population changes (dn2/dt = -d*n2 + b*n1*n2); and one that describes how prey population changes (dn1/dt = r*n1 - a*n1*n2). The results are plotted as they are calculated, showing the two populations versus time (using the TimedPlotter) and versus each other (using the XYPlotter).
AI:
Define the differential equation describing the change in predator population: (dn2/dt = -d*n2 + b*n1*n2)
Define the differential equation describing the change in prey population: (dn1/dt = r*n1 - a*n1*n2)
Calculate the solution for equation 1.
Calculate the solution for equation 2.
Present the results showing the evolution of both populations over time.
Present the results illustrating the relationship between the two populations.
"""

# Task Set: {1, 2, 3, 4, 5}
# Task Relationships: {1:{3}, 2:{3}, 3:{4,5}}

CREATE_GAME_PROMPT = """You are the Task Decomposition Tool of a workflow Generation Agent.
When the current input begins with 'workflow:', convert its natural-language description into an ordered list of atomic workflow tasks.
Keep the tasks one level deep, without nesting. Each line must contain exactly one action and must be understandable without referring to step numbers.
Preserve explicitly stated start, end, approval, confirmation, parallel, and synchronization activities. Do not invent activities that are not supported by the description.
Return only the task list, with one task per line. Do not explain the result and do not reply with 'OK'.
Here is an example for your reference: {Demonstration}
"""

init_prompt = CREATE_GAME_PROMPT.format(Demonstration=escape_braces(demonstration)).replace("{}", "{{}}")

prompt = ChatPromptTemplate.from_messages(
    [
        ("human", init_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ]
)

chain = prompt | TASK_DECOMPOSITION_MODEL | StrOutputParser()

create_game_chain_with_history = RunnableWithMessageHistory(
    chain,  # Wrapped source chain.
    get_session_history,  # Resolve history from the session ID.
    input_messages_key="input",  # Field containing the current user input.
    history_messages_key="history",  # Field receiving prior messages.
).with_types(input_type=InputChat)
