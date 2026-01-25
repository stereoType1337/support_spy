from . import callback_query
from . import command
from . import message
from . import my_chat_member
from . import stats

routers = [
    command.router,
    stats.router,  # Stats router before message to catch /stats command
    message.router,
    callback_query.router,
    my_chat_member.router,
]
