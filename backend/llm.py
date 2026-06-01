from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", streaming=True)
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")
