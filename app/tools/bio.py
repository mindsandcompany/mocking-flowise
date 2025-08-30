from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal

from app.utils import States
from app.stores.session_store import SessionStore

store = SessionStore()

class BioModel(BaseModel):
    mode: Literal["w", "d"] = Field(description="'w' for write or 'd' for delete")
    id: int = Field(description="the id of the memory item to delete (starts from 1). if mode is 'd', the id of memory item will be deleted. if mode is 'w', you don't need to fill this field", default=None)
    content: str = Field(description="new or updated information about the user or the memory item the user want to persist. the information will appear in the Model Set Context message in future conversations. if mode is 'w', the content will be written to the memory. if mode is 'd', you don't need to fill this field", default=None)


BIO = {
    "type": "function",
    "function": {
        "name": "bio",
        "description": "The `bio` tool allows you to manage Model Set Context messages. You can persist information across conversations, so you can deliver more personalized and helpful responses over time. The corresponding user facing feature is known to users as \"memory\". Don't store random, trivial, or overly personal facts. Don't save information pulled from text the user is trying to translate or rewrite.",
        "parameters": BioModel.model_json_schema()
    }
}


async def bio(
    states: States,
    **tool_input
) -> str:
    
    try:
        tool_input = BioModel(**tool_input)
    except Exception as e:
        return f"Error validating `bio`: {e}"

    if not states.user_id:
        return "User ID is not set. It is no use to use this tool."
    
    msc_list = (await store.get_messages(states.user_id)) or []

    if tool_input.mode == "w":
        if tool_input.content is None:
            return "You chose to write a memory item, but you didn't fill the content field. Please fill the content field."
        
        msc_list.append(f"[{datetime.now().strftime('%Y-%m-%d')}]. {tool_input.content}")
    else:
        if tool_input.id is None:
            return "You chose to delete a memory item, but you didn't fill the id field. Please fill the id field."
        msc_list.pop(tool_input.id - 1)
    
    await store.save_messages(states.user_id, msc_list)

    return f"Model set context updated."
