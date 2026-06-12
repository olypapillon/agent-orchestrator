import uuid
import os
import subprocess
from dotenv import load_dotenv
from typing import TypedDict, Annotated, Literal
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command 
load_dotenv()
KNOWLEDGE = ["The LangChain Expression Language lets you compose a prompt, model, and output parser into a single runnable pipeline.",
             "Oly is an AI Engineer",
             "LangGraph models workflows as graphs that can loop. Unlike a simple chain (a DAG that runs once start-to-finish), LangGraph supports cycles",
             "RAG (Retrieval-Augmented Generation) lets a model answer using external knowledge it was never trained on"]
vector_store = InMemoryVectorStore(GoogleGenerativeAIEmbeddings(model='gemini-embedding-001'))
vector_store.add_documents([Document(page_content=text) for text in KNOWLEDGE])

llm = init_chat_model('google_genai:gemini-2.5-flash')
class IntentClassifier(BaseModel):
    message_intent: Literal['chat','knowledge','code'] = Field(...,description='Classify whether the user wants to \
    just chat, ask for knowledge or change code in the project')

#Pass to each node
class State(TypedDict):
    messages: Annotated[list,add_messages]
    message_intent: str | None
    next_node: str| None

def prepare_coding_request(state: State):
    messages = [{'role':'system', 'content':'Rewrite the latest user coding request into a clear instruction for Claude Code.\
                  Use the conversation history as context. Only output the instruction, no explanation'}] + state['messages']
    
    response = llm.invoke(messages)

    return {'messages': [{'role':'user','content':response.content}]}


def classify_intent(state: State):
    structured_llm = llm.with_structured_output(IntentClassifier)

    result = structured_llm.invoke([
        {'role':'system', 'content':'Determine/clasify whether the user wants to chat ("chat"), \
         retrive knowledge ("knowledge") or change code ("code")'},
         {'role' :'user', 'content': state['messages'][-1].content}
         ])
    
    return {'message_intent' : result.message_intent}

def accept_coding(state:State):
    user_prompt = state['messages'][-1].content
    decision = interrupt(f'About to run Claude Code with request: \n\n{user_prompt}\n\n Approve? (yes/no, or type a revised request)')
    
    text = str(decision).strip()
    if text in ['y','yes','approve','ok']:
        return {'next_node': 'coding'}
    if text in ['n','no','deny','cancel']:
        return {'messages':[{'role':'assistant', 'content': 'Coding request was denied by user.'}], 'next_node':'denied'}
    
    return {'messages':[{'role':'assistant', 'content': text}],'next_node':'accept_code'}
    
def prompt_llm_chat(state: State):
    messages = [{'role': 'system', 'content' : 'You are a talkative chatbot for fun. Be nice'}] + state['messages']

    response = llm.invoke(messages)
    return {'messages' :[{'role': 'assistant' , 'content' : response.content}]}

def prompt_llm_rag(state: State):
    query = state['messages'][-1].content
    documents = vector_store.similarity_search(query,k=3)
    context = '\n'.join(f'- {doc.page_content}' for doc in documents) 
    messages = [{'role': 'system', 'content' : f'You are a RAG agent. Answer the user using only the content below. \
                 If the answer is not in it say I don\'t know. \n\n Context:\n{context}'}] + state['messages']

    response = llm.invoke(messages)
    return {'messages' :[{'role': 'assistant' , 'content' : response.content}]}

def prompt_llm_code(state: State):
    user_prompt = state['messages'][-1].content
    workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)),'workspace')

    result = subprocess.run(
        ['claude', '-p', user_prompt , '--permission-mode' , 'acceptEdits'],
        cwd=workspace,
        capture_output=True,
        text=True)
    
    output = result.stdout.strip() or result.stderr.strip()

    return {'messages' :[{'role': 'assistant' , 'content' : output}]}

graph_builder = StateGraph(State)

graph_builder.add_node('classifier',classify_intent)
graph_builder.add_node('chat_agent',prompt_llm_chat)
graph_builder.add_node('rag_agent',prompt_llm_rag)
graph_builder.add_node('prepare_coding',prepare_coding_request)
graph_builder.add_node('coding_agent',prompt_llm_code)
graph_builder.add_node('accept_coding',accept_coding)


graph_builder.add_edge(START,'classifier')
graph_builder.add_edge('prepare_coding','accept_coding')
graph_builder.add_conditional_edges('accept_coding',lambda state: state.get('next_node'), {'denied':END, 'coding':'coding_agent','accept_code':'prepare_coding'})
graph_builder.add_conditional_edges('classifier' , lambda state: state['message_intent'], {'chat':'chat_agent',
                                                                                            'knowledge':'rag_agent',
                                                                                            'code':'prepare_coding'})

graph_builder.add_edge('chat_agent', END)
graph_builder.add_edge('coding_agent', END)
graph_builder.add_edge('rag_agent', END)

checkpointer = InMemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer)
graph.get_graph().draw_mermaid_png(output_file_path='graph.png')
config = {'configurable':{'thread_id':uuid.uuid4()}}

while True:
    user_message = input('Enter message : ')
    result = graph.invoke({'messages' : [{'role':'user', 'content': user_message}]},config=config)
    while '__interrupt__' in result:
        prompt = result['__interrupt__'][0].value
        decision = input(f'{prompt}\n> ')
        result = graph.invoke(Command(resume=decision),config=config)

    print(result['messages'][-1].content)