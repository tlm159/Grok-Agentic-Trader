import os


class LiveSearchUnavailable(RuntimeError):
    pass


def fetch_live_context(query, model, api_key=None, max_sources=None):
    key = api_key or os.getenv("XAI_API_KEY")
    if not key:
        raise LiveSearchUnavailable("Missing XAI_API_KEY for live search")
    try:
        from xai_sdk import Client
        from xai_sdk.chat import user
        from xai_sdk.tools import web_search
    except ImportError as exc:
        raise LiveSearchUnavailable("Missing xai-sdk package") from exc

    client = Client(api_key=key)
    search_tool = None
    if max_sources is not None:
        try:
            search_tool = web_search(max_results=int(max_sources))
        except TypeError:
            try:
                search_tool = web_search(max_sources=int(max_sources))
            except TypeError:
                search_tool = web_search()
    else:
        search_tool = web_search()
    chat = client.chat.create(model=model, tools=[search_tool])
    chat.append(user(query))
    response = chat.sample()
    return response.content
