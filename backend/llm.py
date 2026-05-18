from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, MessagesState, StateGraph

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", streaming=True)
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")


def _call_model(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


_builder = StateGraph(MessagesState)
_builder.add_node("agent", _call_model)
_builder.add_edge(START, "agent")
_builder.add_edge("agent", END)
graph = _builder.compile()
