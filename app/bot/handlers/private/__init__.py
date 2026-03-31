from . import callback_query
from . import command
from . import message
from . import my_chat_member
from . import stats

routers = [
    command.router_dev,  # Dev commands (stats, delete_topics) — work in any chat type
    command.router,
    stats.router,  # Stats router — works in any chat type
    message.router,
    callback_query.router,
    my_chat_member.router,
]
